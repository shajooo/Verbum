from __future__ import annotations
import json, random, time
from pathlib import Path
from collections import Counter, defaultdict

import torch
from torch import nn
from torch.utils.data import Dataset, DataLoader
from torchvision import models, transforms
from PIL import Image

ROOT = Path(r"C:\Projects\Transcriber")
MANIFEST = ROOT / "metadata" / "glyph_manifest.json"
OUT = ROOT / "models" / "character_ocr"
OUT.mkdir(parents=True, exist_ok=True)
SEED = 20261008
random.seed(SEED)
torch.manual_seed(SEED)

data = json.loads(MANIFEST.read_text(encoding="utf-8"))
entries = [e for e in data["entries"] if e.get("review_status") == "GOOD" and e.get("output_path")]
records = [(str(e["char"]), Path(e["output_path"])) for e in entries if Path(e["output_path"]).is_file()]
labels = sorted({label for label, _ in records})
label_to_id = {label:i for i,label in enumerate(labels)}
by_label = defaultdict(list)
for label, path in records:
    by_label[label].append((label, path))
train, val = [], []
for label in labels:
    items = by_label[label][:]
    random.shuffle(items)
    n = len(items)
    if n >= 5:
        nv = max(1, round(n * 0.2))
        val.extend(items[:nv]); train.extend(items[nv:])
    else:
        val.extend(items[:1]); train.extend(items[1:])
random.shuffle(train); random.shuffle(val)

class GlyphDataset(Dataset):
    def __init__(self, items, tfm):
        self.items, self.tfm = items, tfm
    def __len__(self): return len(self.items)
    def __getitem__(self, i):
        label, path = self.items[i]
        img = Image.open(path).convert("L")
        return self.tfm(img), label_to_id[label]

train_tf = transforms.Compose([
    transforms.Resize((96,96)),
    transforms.RandomAffine(degrees=7, translate=(0.07,0.07), scale=(0.90,1.10), shear=5, fill=255),
    transforms.RandomPerspective(distortion_scale=0.12, p=0.25, fill=255),
    transforms.ToTensor(),
    transforms.Normalize((0.5,), (0.5,))
])
val_tf = transforms.Compose([
    transforms.Resize((96,96)),
    transforms.ToTensor(),
    transforms.Normalize((0.5,), (0.5,))
])

train_ds, val_ds = GlyphDataset(train, train_tf), GlyphDataset(val, val_tf)
train_dl = DataLoader(train_ds, batch_size=64, shuffle=True, num_workers=0, pin_memory=torch.cuda.is_available())
val_dl = DataLoader(val_ds, batch_size=64, shuffle=False, num_workers=0, pin_memory=torch.cuda.is_available())

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
model = models.resnet18(weights=None)
model.conv1 = nn.Conv2d(1, 64, kernel_size=7, stride=2, padding=3, bias=False)
model.fc = nn.Linear(model.fc.in_features, len(labels))
model.to(device)

# Inverse-frequency class weights prevent abundant classes dominating the small dataset.
counts = Counter(label_to_id[label] for label, _ in train)
weights = torch.tensor([len(train) / (len(labels) * max(1, counts[i])) for i in range(len(labels))], dtype=torch.float32, device=device)
criterion = nn.CrossEntropyLoss(weight=weights, label_smoothing=0.04)
optimizer = torch.optim.AdamW(model.parameters(), lr=3e-4, weight_decay=1e-4)
scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=35)
scaler = torch.amp.GradScaler("cuda", enabled=device.type=="cuda")

best_acc = -1.0
best_path = OUT / "character_ocr_best.pt"
history = []
epochs = 35
start = time.time()

for epoch in range(1, epochs+1):
    model.train()
    seen = correct = 0
    loss_sum = 0.0
    for x,y in train_dl:
        x,y = x.to(device, non_blocking=True), y.to(device, non_blocking=True)
        optimizer.zero_grad(set_to_none=True)
        with torch.autocast(device_type="cuda", dtype=torch.float16, enabled=device.type=="cuda"):
            logits = model(x)
            loss = criterion(logits,y)
        scaler.scale(loss).backward()
        scaler.step(optimizer); scaler.update()
        loss_sum += loss.item() * y.size(0)
        correct += (logits.argmax(1)==y).sum().item(); seen += y.size(0)

    model.eval()
    vseen = vcorr = 0
    per = Counter(); per_correct = Counter()
    vloss = 0.0
    with torch.no_grad():
        for x,y in val_dl:
            x,y = x.to(device, non_blocking=True), y.to(device, non_blocking=True)
            with torch.autocast(device_type="cuda", dtype=torch.float16, enabled=device.type=="cuda"):
                logits = model(x); loss = criterion(logits,y)
            vloss += loss.item()*y.size(0)
            pred = logits.argmax(1)
            for yi,pi in zip(y.tolist(),pred.tolist()):
                per[yi]+=1
                per_correct[yi]+=int(yi==pi)
            vcorr += (pred==y).sum().item(); vseen += y.size(0)
    scheduler.step()
    train_acc=correct/seen; val_acc=vcorr/vseen
    history.append({"epoch":epoch,"train_loss":loss_sum/seen,"train_acc":train_acc,"val_loss":vloss/vseen,"val_acc":val_acc,"lr":optimizer.param_groups[0]["lr"]})
    print(f"EPOCH {epoch:02d}/{epochs} train_acc={train_acc:.4f} val_acc={val_acc:.4f} val_loss={vloss/vseen:.4f}", flush=True)
    if val_acc > best_acc:
        best_acc=val_acc
        torch.save({"model_state":model.state_dict(),"labels":labels,"image_size":96,"normalization_mean":0.5,"normalization_std":0.5,"architecture":"resnet18_gray","seed":SEED,"dataset_good":len(records),"train_count":len(train),"val_count":len(val),"best_val_accuracy":best_acc}, best_path)

# Load best and produce final per-class metrics.
ckpt=torch.load(best_path,map_location=device,weights_only=False)
model.load_state_dict(ckpt["model_state"]); model.eval()
per=Counter(); pc=Counter()
with torch.no_grad():
    for x,y in val_dl:
        x,y=x.to(device),y.to(device)
        pred=model(x).argmax(1)
        for yi,pi in zip(y.tolist(),pred.tolist()):
            per[yi]+=1; pc[yi]+=int(yi==pi)
per_class={labels[i]: {"correct":pc[i],"total":per[i],"accuracy":pc[i]/per[i] if per[i] else 0.0} for i in range(len(labels))}
report={"dataset_total_good":len(records),"classes":len(labels),"train_count":len(train),"val_count":len(val),"best_val_accuracy":best_acc,"per_class":per_class,"history":history,"device":str(device),"torch":torch.__version__,"cuda":torch.version.cuda,"gpu":torch.cuda.get_device_name(0) if device.type=="cuda" else "CPU","elapsed_seconds":round(time.time()-start,1)}
(OUT/"training_report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
(OUT/"labels.json").write_text(json.dumps({"labels":labels,"label_to_id":label_to_id},indent=2),encoding="utf-8")
print("DONE best_val_accuracy=",round(best_acc,4),"elapsed=",round(time.time()-start,1),"s",flush=True)
