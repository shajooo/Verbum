"""
Image Loading and IO utilities for handwriting sheets.
Preserves non-destructive image quality and handles EXIF orientation.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Tuple, Any

import cv2
import numpy as np
from PIL import Image, ImageOps


class ImageLoader:
    """Robust image loader handling EXIF orientation and format differences."""

    @staticmethod
    def load_image(image_path: str | Path) -> Tuple[np.ndarray, Dict[str, Any]]:
        """
        Loads an image from disk.
        Returns:
            bgr_image: OpenCV BGR uint8 numpy array
            metadata: dictionary of raw image properties
        """
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"Image file does not exist: {path}")

        # Open via PIL first to handle EXIF orientation safely
        with Image.open(path) as pil_img:
            # Transpose if EXIF orientation is present
            pil_img = ImageOps.exif_transpose(pil_img)
            # Ensure RGB
            if pil_img.mode != "RGB":
                pil_img = pil_img.convert("RGB")
            rgb_arr = np.array(pil_img)
            
            # Convert RGB to BGR for OpenCV
            bgr_img = cv2.cvtColor(rgb_arr, cv2.COLOR_RGB2BGR)

        h, w = bgr_img.shape[:2]
        metadata = {
            "source_path": str(path.resolve()),
            "file_name": path.name,
            "width": w,
            "height": h,
            "aspect_ratio": round(w / float(h), 4),
            "channels": 3,
            "file_size_bytes": path.stat().st_size
        }
        return bgr_img, metadata
