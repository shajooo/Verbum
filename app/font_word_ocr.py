from pathlib import Path
from PIL import Image, ImageOps
import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer
import math,re

class WordOCR:
    def __init__(self, model_path, device=None, context_model_dir=None):
        self.device_name=device or ("cuda" if "CUDAExecutionProvider" in ort.get_available_providers() else "cpu")
        providers=["CUDAExecutionProvider","CPUExecutionProvider"] if self.device_name in ("cuda","cuda:0") and "CUDAExecutionProvider" in ort.get_available_providers() else ["CPUExecutionProvider"]
        self.session=ort.InferenceSession(str(model_path),providers=providers)
        self.chars="abcdefghijklmnopqrstuvwxyz_"
        self.blank=26
        self._context_resolver=None
        self.context_model_dir=context_model_dir

    def _tensor(self,image):
        if isinstance(image,(str,Path)): image=Image.open(image)
        image=image.convert("L")
        if np.asarray(image,dtype=np.uint8).mean()>127: image=ImageOps.invert(image)
        h=64; w=max(16,int(image.width*h/image.height))
        image=image.resize((w,h),Image.Resampling.BILINEAR)
        a=np.asarray(image,dtype=np.float32)/255.0
        return a[None,None,:,:],image

    def predict(self,image):
        x,img=self._tensor(image)
        out=self.session.run(["logits"],{"image":x})[0][0]
        ids=out.argmax(1).tolist()
        probs=np.exp(out-out.max(1,keepdims=True)); probs/=probs.sum(1,keepdims=True)
        runs=[]; text=[]; start=None; prev=None; T=len(ids); width=img.width
        for t,k in enumerate(ids+[self.blank]):
            if k==self.blank:
                if prev is not None and start is not None:
                    center=((start+t-1)/2.0)/T*width; runs.append((prev,center)); text.append(self.chars[prev])
                prev=None; start=None
            elif k!=prev:
                if prev is not None and start is not None:
                    center=((start+t-1)/2.0)/T*width; runs.append((prev,center)); text.append(self.chars[prev])
                prev=k; start=t
        spans=[]
        for i,(k,c) in enumerate(runs):
            left=0 if i==0 else (runs[i-1][1]+c)/2
            right=width if i==len(runs)-1 else (c+runs[i+1][1])/2
            spans.append({"char":self.chars[k],"x1":max(0,int(left)),"x2":min(width,int(right))})
        return {"text":"".join(text),"confidence":float(probs.max(1).mean()),"spans":spans,"normalized_width":width}

    @property
    def context_resolver(self):
        if self._context_resolver is None:
            from .context_word_resolver import ContextWordResolver
            self._context_resolver=ContextWordResolver(self.context_model_dir)
        return self._context_resolver

    def resolve_word_context(self,raw,left_words,right_words,candidates=None,resolver=None):
        return (resolver or self.context_resolver).resolve(raw,left_words,right_words,candidates)

    def extract_aligned(self,image,result,out_dir):
        if isinstance(image,(str,Path)): image=Image.open(image)
        image=image.convert("L"); out=Path(out_dir); out.mkdir(parents=True,exist_ok=True)
        saved=[]
        for i,s in enumerate(result["spans"]):
            x1,x2=s["x1"],s["x2"]
            if x2<=x1+2: continue
            pad=max(1,int((x2-x1)*.18)); crop=image.crop((max(0,x1-pad),0,min(image.width,x2+pad),image.height))
            p=out/f"{i:02d}_{s['char']}.png"; crop.save(p); saved.append((s["char"],p))
        return saved
