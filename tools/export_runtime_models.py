from pathlib import Path
import torch
from torch import nn
from transformers import AutoModelForMaskedLM
from tokenizers import Tokenizer

ROOT=Path(r"C:\Projects\Transcriber")

# Word CRNN
word_src=ROOT/"models"/"word_ocr"/"word_crnn.pt"
word_out=ROOT/"models"/"word_ocr"/"word_crnn.onnx"
ck=torch.load(word_src,map_location="cpu",weights_only=False)
class CRNN(nn.Module):
    def __init__(self):
        super().__init__()
        self.cnn=nn.Sequential(
            nn.Conv2d(1,32,3,padding=1),nn.BatchNorm2d(32),nn.ReLU(),nn.MaxPool2d(2),
            nn.Conv2d(32,64,3,padding=1),nn.BatchNorm2d(64),nn.ReLU(),nn.MaxPool2d(2),
            nn.Conv2d(64,96,3,padding=1),nn.BatchNorm2d(96),nn.ReLU(),
            nn.Conv2d(96,128,3,padding=1),nn.BatchNorm2d(128),nn.ReLU(),nn.MaxPool2d((2,1)))
        self.rnn=nn.LSTM(1024,128,2,bidirectional=True,batch_first=True,dropout=.15)
        self.fc=nn.Linear(256,27)
    def forward(self,x):
        z=self.cnn(x).permute(0,3,1,2).contiguous()
        z=z.view(z.size(0),z.size(1),-1)
        z,_=self.rnn(z)
        return self.fc(z).log_softmax(2)
m=CRNN(); m.load_state_dict(ck["model"]); m.eval()
dummy=torch.zeros(1,1,64,244)
torch.onnx.export(m,dummy,str(word_out),input_names=["image"],output_names=["logits"],dynamic_axes={"image":{3:"width"},"logits":{1:"time"}},opset_version=18,dynamo=False)
print("WORD_ONNX",word_out.stat().st_size)

# Context BERT
ctx=ROOT/"models"/"context_ocr"
bert=AutoModelForMaskedLM.from_pretrained(ctx,local_files_only=True).eval()
tokenizer=Tokenizer.from_file(str(ctx/"tokenizer.json"))
mask_id=tokenizer.token_to_id("[MASK]")
print("MASK_ID",mask_id)
enc=tokenizer.encode("[MASK] is your name")
ids=torch.tensor([enc.ids],dtype=torch.long)
attn=torch.tensor([enc.attention_mask],dtype=torch.long)
types=torch.tensor([enc.type_ids],dtype=torch.long)
class Wrapper(nn.Module):
    def __init__(self,model): super().__init__(); self.model=model
    def forward(self,input_ids,attention_mask,token_type_ids): return self.model(input_ids=input_ids,attention_mask=attention_mask,token_type_ids=token_type_ids).logits
w=Wrapper(bert).eval()
ctx_out=ctx/"context_bert.onnx"
torch.onnx.export(w,(ids,attn,types),str(ctx_out),input_names=["input_ids","attention_mask","token_type_ids"],output_names=["logits"],dynamic_axes={"input_ids":{1:"sequence"},"attention_mask":{1:"sequence"},"token_type_ids":{1:"sequence"},"logits":{1:"sequence"}},opset_version=18,dynamo=False)
print("CTX_ONNX",ctx_out.stat().st_size)
