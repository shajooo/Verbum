from pathlib import Path
import math,re
import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

class ContextWordResolver:
    def __init__(self,model_dir=None,device=None):
        self.model_dir=Path(model_dir or Path(__file__).resolve().parents[1]/"models"/"context_ocr")
        providers=["CUDAExecutionProvider","CPUExecutionProvider"] if device in ("cuda","cuda:0") and "CUDAExecutionProvider" in ort.get_available_providers() else ["CPUExecutionProvider"]
        self.session=ort.InferenceSession(str(self.model_dir/"context_bert.onnx"),providers=providers)
        self.tokenizer=Tokenizer.from_file(str(self.model_dir/"tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=128)
        self.mask_id=self.tokenizer.token_to_id("[MASK]")
        self.vocabulary=tuple(sorted(w for w in self.tokenizer.get_vocab() if re.fullmatch(r"[a-z]{2,24}",w)))

    @staticmethod
    def _distance(pattern,word):
        if len(pattern)!=len(word): return abs(len(pattern)-len(word))+2
        return sum(a!="*" and a!=b for a,b in zip(pattern.lower(),word.lower()))

    def candidate_words(self,raw,limit=24,max_distance=2):
        raw=re.sub(r"[^a-z*?]","",raw.lower()).replace("?","*")
        if not raw:return []
        exact=[w for w in self.vocabulary if len(w)==len(raw) and all(a=="*" or a==b for a,b in zip(raw,w))]
        if "*" in raw:return exact[:limit]
        scored=[(self._distance(raw,w),w) for w in self.vocabulary if abs(len(w)-len(raw))<=max_distance and self._distance(raw,w)<=max_distance]
        scored.sort(key=lambda x:(x[0],-len(x[1])))
        return [w for _,w in scored[:limit]]

    def _context_score(self,candidate,left_words,right_words):
        pieces=self.tokenizer.encode(candidate,add_special_tokens=False).ids
        if not pieces:return -math.inf
        masks=" ".join(["[MASK]"]*len(pieces))
        enc=self.tokenizer.encode(" ".join([*left_words,masks,*right_words]),add_special_tokens=True)
        ids=np.asarray([enc.ids],dtype=np.int64)
        attn=np.ones_like(ids,dtype=np.int64)
        types=np.zeros_like(ids,dtype=np.int64)
        positions=[i for i,v in enumerate(enc.ids) if v==self.mask_id]
        if len(positions)!=len(pieces):return -math.inf
        logits=self.session.run(["logits"],{"input_ids":ids,"attention_mask":attn,"token_type_ids":types})[0][0]
        mx=logits.max(axis=1,keepdims=True); logp=logits-mx-np.log(np.exp(logits-mx).sum(axis=1,keepdims=True))
        return float(sum(logp[pos,piece] for pos,piece in zip(positions,pieces))/len(pieces))

    def resolve(self,raw,left_words,right_words,candidates=None):
        candidates=list(candidates or self.candidate_words(raw))
        if not candidates:return {"word":raw,"confidence":0.0,"candidates":[]}
        scored=[]
        for word in candidates:
            visual=-float(self._distance(raw,word))
            context=self._context_score(word,left_words,right_words)
            scored.append({"word":word,"score":context+0.65*visual,"context_score":context,"visual_score":visual})
        scored.sort(key=lambda x:x["score"],reverse=True)
        best=scored[0]; margin=best["score"]-(scored[1]["score"] if len(scored)>1 else best["score"]-1)
        confidence=1/(1+math.exp(-max(-12,min(12,margin))))
        return {"word":best["word"],"confidence":confidence,"candidates":scored}
