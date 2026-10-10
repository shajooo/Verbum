"""Local custom handwriting character recognizer using the project-local ONNX model."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import onnxruntime as ort
from PIL import Image


class CustomCharacterOCR:
    def __init__(self, model_dir: str | Path | None = None, device: str | None = None) -> None:
        root = Path(model_dir) if model_dir else Path(__file__).resolve().parents[1] / "models" / "character_ocr"
        self.root = root.resolve()
        model_path = self.root / "character_ocr.onnx"
        labels_path = self.root / "labels.json"
        if not model_path.is_file() or not labels_path.is_file():
            raise FileNotFoundError("Custom character OCR model is not installed in the project.")
        labels_data = json.loads(labels_path.read_text(encoding="utf-8"))
        self.labels = list(labels_data["labels"])
        providers = ["CPUExecutionProvider"]
        if device == "cuda" and "CUDAExecutionProvider" in ort.get_available_providers():
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        self.session = ort.InferenceSession(str(model_path), providers=providers)
        self.input_name = self.session.get_inputs()[0].name
        self.image_size = 96
        self.mean = 0.5
        self.std = 0.5

    def predict(self, image: Image.Image) -> dict[str, Any]:
        gray = image.convert("L").resize((self.image_size, self.image_size), Image.Resampling.BILINEAR)
        array = np.asarray(gray, dtype=np.float32) / 255.0
        array = (array - self.mean) / self.std
        logits = self.session.run(None, {self.input_name: array[None, None, :, :]})[0][0]
        logits = logits - np.max(logits)
        probs = np.exp(logits)
        probs /= np.sum(probs)
        index = int(np.argmax(probs))
        top_indices = np.argsort(probs)[::-1][:min(5, len(self.labels))]
        return {
            "character": self.labels[index],
            "confidence": float(probs[index]),
            "top_k": [
                {"character": self.labels[int(i)], "confidence": float(probs[int(i)])}
                for i in top_indices
            ],
        }
