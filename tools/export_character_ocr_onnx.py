from pathlib import Path
import torch
from torch import nn
from torchvision import models

root=Path(r"C:\Projects\Transcriber")
out=root/"models"/"character_ocr"/"character_ocr.onnx"
ck=torch.load(root/"models"/"character_ocr"/"character_ocr_best.pt",map_location="cpu",weights_only=False)
labels=ck["labels"]
model=models.resnet18(weights=None)
model.conv1=nn.Conv2d(1,64,kernel_size=7,stride=2,padding=3,bias=False)
model.fc=nn.Linear(model.fc.in_features,len(labels))
model.load_state_dict(ck["model_state"])
model.eval()
dummy=torch.zeros(1,1,int(ck["image_size"]),int(ck["image_size"]),dtype=torch.float32)
torch.onnx.export(model,dummy,str(out),input_names=["image"],output_names=["logits"],opset_version=18,dynamo=False)
print("EXPORTED",out,"BYTES",out.stat().st_size)
