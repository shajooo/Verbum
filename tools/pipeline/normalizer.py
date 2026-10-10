"""
Aspect-Ratio-Preserving Glyph Normalizer.
Centers characters on a standardized canvas without distortion.
"""
from __future__ import annotations

from typing import Tuple, Dict, Any

import cv2
import numpy as np

from tools.pipeline.cell_extractor import ExtractedGlyphResult


class GlyphNormalizer:
    """Normalizes glyphs onto a uniform canvas preserving natural aspect ratios."""

    def __init__(self, target_size: int = 128, margin: int = 16):
        self.target_size = target_size
        self.margin = margin
        self.content_size = target_size - 2 * margin

    def normalize(
        self,
        glyph_result: ExtractedGlyphResult
    ) -> Tuple[np.ndarray, np.ndarray, Dict[str, Any]]:
        """
        Normalizes extracted glyph.
        Returns:
            antialias_gray: 128x128 uint8 image (255 white bg, dark ink)
            binary_mask: 128x128 uint8 binary mask (0 white bg, 255 ink)
            meta: normalization metrics (scale, bounds, ink pixels)
        """
        if glyph_result.is_empty:
            empty_gray = np.full((self.target_size, self.target_size), 255, dtype=np.uint8)
            empty_bin = np.zeros((self.target_size, self.target_size), dtype=np.uint8)
            return empty_gray, empty_bin, {
                "scale": 0.0,
                "norm_w": 0,
                "norm_h": 0,
                "ink_pixels": 0,
                "aspect_ratio": 0.0
            }

        gx1, gy1, gx2, gy2 = glyph_result.glyph_bbox
        gw = gx2 - gx1
        gh = gy2 - gy1

        if gw <= 0 or gh <= 0:
            empty_gray = np.full((self.target_size, self.target_size), 255, dtype=np.uint8)
            empty_bin = np.zeros((self.target_size, self.target_size), dtype=np.uint8)
            return empty_gray, empty_bin, {
                "scale": 0.0,
                "norm_w": 0,
                "norm_h": 0,
                "ink_pixels": 0,
                "aspect_ratio": 0.0
            }

        # Crop isolated binary mask and normalized gray
        mask_crop = glyph_result.isolated_binary_mask[gy1:gy2, gx1:gx2]
        gray_crop = glyph_result.norm_gray_cell[gy1:gy2, gx1:gx2]

        # Dilate mask slightly to capture anti-aliased stroke fringes
        fringe_mask = cv2.dilate(mask_crop, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
        clean_gray_crop = np.where(fringe_mask > 0, gray_crop, 255).astype(np.uint8)

        # Scale calculation preserving aspect ratio
        scale = self.content_size / float(max(gw, gh))
        new_w = max(1, int(round(gw * scale)))
        new_h = max(1, int(round(gh * scale)))

        # Resample
        interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
        resized_gray = cv2.resize(clean_gray_crop, (new_w, new_h), interpolation=interp)
        resized_bin = cv2.resize(mask_crop, (new_w, new_h), interpolation=cv2.INTER_NEAREST)

        # Center on canvas
        canvas_gray = np.full((self.target_size, self.target_size), 255, dtype=np.uint8)
        canvas_bin = np.zeros((self.target_size, self.target_size), dtype=np.uint8)

        ox = self.margin + (self.content_size - new_w) // 2
        oy = self.margin + (self.content_size - new_h) // 2

        canvas_gray[oy:oy+new_h, ox:ox+new_w] = resized_gray
        canvas_bin[oy:oy+new_h, ox:ox+new_w] = resized_bin

        ink_pixels = int(np.count_nonzero(canvas_bin > 0))
        aspect_ratio = round(gw / float(gh), 3)

        meta = {
            "scale": round(scale, 3),
            "norm_w": new_w,
            "norm_h": new_h,
            "ox": ox,
            "oy": oy,
            "ink_pixels": ink_pixels,
            "aspect_ratio": aspect_ratio
        }
        return canvas_gray, canvas_bin, meta
