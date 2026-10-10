"""
Cell Extraction, Grid-Line Suppression, and Multi-Component Glyph Grouping.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any

import cv2
import numpy as np

from tools.pipeline.config import CharacterMeta
from tools.pipeline.grid_detector import ExtractedCellBox


@dataclass
class ExtractedGlyphResult:
    cell_box: ExtractedCellBox
    raw_cell_crop: np.ndarray        # BGR crop
    norm_gray_cell: np.ndarray       # Illumination-normalized grayscale
    isolated_binary_mask: np.ndarray # Clean binary mask (255 foreground, 0 bg)
    glyph_bbox: Tuple[int, int, int, int] # (gx1, gy1, gx2, gy2) within cell
    component_count: int
    is_empty: bool = False
    clipped_border: bool = False


class CellExtractor:
    """Isolates character content within each cell, suppresses grid lines, and groups glyph components."""

    @staticmethod
    def extract_glyph_from_cell(
        sheet_bgr: np.ndarray,
        cell_box: ExtractedCellBox,
        safe_inset_px: int = 4
    ) -> ExtractedGlyphResult:
        """
        Extracts and cleans the glyph inside a cell.
        """
        h_sheet, w_sheet = sheet_bgr.shape[:2]
        
        # Crop raw cell
        x1 = max(0, cell_box.x1)
        y1 = max(0, cell_box.y1)
        x2 = min(w_sheet, cell_box.x2)
        y2 = min(h_sheet, cell_box.y2)

        raw_crop = sheet_bgr[y1:y2, x1:x2].copy()
        ch, cw = raw_crop.shape[:2]

        if ch < 10 or cw < 10:
            empty_mask = np.zeros((max(1, ch), max(1, cw)), dtype=np.uint8)
            empty_gray = np.full((max(1, ch), max(1, cw)), 255, dtype=np.uint8)
            return ExtractedGlyphResult(
                cell_box=cell_box,
                raw_cell_crop=raw_crop,
                norm_gray_cell=empty_gray,
                isolated_binary_mask=empty_mask,
                glyph_bbox=(0, 0, 0, 0),
                component_count=0,
                is_empty=True
            )

        gray = cv2.cvtColor(raw_crop, cv2.COLOR_BGR2GRAY)

        # 1. Illumination normalization via background division
        k_sz = max(15, min(cw, ch) // 2 * 2 + 1)
        bg = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (k_sz, k_sz)))
        norm_gray = cv2.divide(gray, bg, scale=255)

        # 2. Adaptive Binarization
        blurred = cv2.GaussianBlur(norm_gray, (3, 3), 0)
        thresh = cv2.adaptiveThreshold(
            blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 15, 6
        )

        # 3. Safe Inset & Grid-Line Suppression
        inset_y = min(safe_inset_px, max(2, ch // 8))
        inset_x = min(safe_inset_px, max(2, cw // 8))
        
        sub_mask = thresh[inset_y:ch-inset_y, inset_x:cw-inset_x]
        sub_h, sub_w = sub_mask.shape

        if sub_h < 5 or sub_w < 5:
            empty_mask = np.zeros((ch, cw), dtype=np.uint8)
            return ExtractedGlyphResult(
                cell_box=cell_box,
                raw_cell_crop=raw_crop,
                norm_gray_cell=norm_gray,
                isolated_binary_mask=empty_mask,
                glyph_bbox=(0, 0, 0, 0),
                component_count=0,
                is_empty=True
            )

        # 4. Connected Components & Advanced Grid Artifact Filtering
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(sub_mask, connectivity=8)

        is_small_punct = cell_box.char_meta.is_small_punct
        min_area = 3 if is_small_punct else 8

        candidate_components = []
        for lbl in range(1, num_labels):
            cx, cy, cc_w, cc_h, area = stats[lbl]

            if area < min_area:
                continue

            top = (cy <= 1)
            bot = (cy + cc_h >= sub_h - 1)
            left = (cx <= 1)
            right = (cx + cc_w >= sub_w - 1)
            touches_border = (top or bot or left or right)
            aspect = max(cc_w / float(cc_h + 1e-5), cc_h / float(cc_w + 1e-5))
            fill_ratio = area / float(cc_w * cc_h + 1e-5)

            # Identification of grid line fragments, L-junctions, and full frames
            is_grid_artifact = touches_border and (
                (cc_w >= sub_w - 3) or (cc_h >= sub_h - 3) or
                (top and bot) or (left and right) or
                aspect > 2.6 or
                (sum([top, bot, left, right]) >= 2 and fill_ratio < 0.28) or
                (cc_w > sub_w * 0.35 and cc_h < 7) or
                (cc_h > sub_h * 0.35 and cc_w < 7) or
                (cell_box.char_meta.char in ('z', 'Z') and (cc_w / float(cc_h + 1e-5)) < 0.45 and (left or right))
            )

            if not is_grid_artifact:
                candidate_components.append({
                    "lbl": lbl,
                    "x": cx, "y": cy, "w": cc_w, "h": cc_h, "area": area,
                    "cx": centroids[lbl][0], "cy": centroids[lbl][1],
                    "touches_border": touches_border
                })

        if not candidate_components:
            empty_mask = np.zeros((ch, cw), dtype=np.uint8)
            return ExtractedGlyphResult(
                cell_box=cell_box,
                raw_cell_crop=raw_crop,
                norm_gray_cell=norm_gray,
                isolated_binary_mask=empty_mask,
                glyph_bbox=(0, 0, 0, 0),
                component_count=0,
                is_empty=True
            )

        # 5. Glyph Grouping & Noise Speck Rejection
        char_meta = cell_box.char_meta
        selected_lbls = []

        # Sort candidate components by area descending
        candidate_components.sort(key=lambda c: c["area"], reverse=True)
        main_comp = candidate_components[0]
        selected_lbls.append(main_comp["lbl"])

        if char_meta.multi_component:
            # For characters like 'i', 'j', ':', '()', '{}', '[]'
            char_str = char_meta.char
            for other in candidate_components[1:]:
                # If colon ':', second dot is vertically aligned
                if char_str == ":":
                    if abs(other["cx"] - main_comp["cx"]) < 12 and other["area"] >= min_area:
                        selected_lbls.append(other["lbl"])
                # If 'i' or 'j', dot is above stem
                elif char_str in ("i", "j"):
                    if abs(other["cx"] - main_comp["cx"]) < 14 and other["cy"] < main_comp["cy"] and other["area"] >= min_area:
                        selected_lbls.append(other["lbl"])
                # If paired brackets '()', '{}', '[]', side by side
                elif char_str in ("()", "{}", "[]"):
                    if abs(other["cy"] - main_comp["cy"]) < 18 and other["area"] >= main_comp["area"] * 0.25:
                        selected_lbls.append(other["lbl"])
                else:
                    # General multi-component proximity
                    dist = np.hypot(other["cx"] - main_comp["cx"], other["cy"] - main_comp["cy"])
                    if dist < max(sub_w, sub_h) * 0.55 and other["area"] >= min_area * 1.5:
                        selected_lbls.append(other["lbl"])
        else:
            # Single component character: only keep secondary components if significant and very close (accents/crosses)
            for other in candidate_components[1:]:
                dist = np.hypot(other["cx"] - main_comp["cx"], other["cy"] - main_comp["cy"])
                if dist < max(main_comp["w"], main_comp["h"]) * 0.9 and other["area"] > main_comp["area"] * 0.20:
                    selected_lbls.append(other["lbl"])

        # Render selected components onto cleaned_sub
        cleaned_sub = np.zeros_like(sub_mask)
        for lbl in selected_lbls:
            cleaned_sub[labels == lbl] = 255

        # Check clipping: count non-zero pixels on perimeter
        top_c = int(np.count_nonzero(cleaned_sub[0, :] > 0))
        bot_c = int(np.count_nonzero(cleaned_sub[-1, :] > 0))
        left_c = int(np.count_nonzero(cleaned_sub[:, 0] > 0))
        right_c = int(np.count_nonzero(cleaned_sub[:, -1] > 0))
        clipped_detected = (top_c + bot_c + left_c + right_c) > 8

        # Embed into full cell coordinate frame
        full_isolated = np.zeros_like(thresh)
        full_isolated[inset_y:inset_y+sub_h, inset_x:inset_x+sub_w] = cleaned_sub

        pts = cv2.findNonZero(full_isolated)
        if pts is None:
            return ExtractedGlyphResult(
                cell_box=cell_box,
                raw_cell_crop=raw_crop,
                norm_gray_cell=norm_gray,
                isolated_binary_mask=full_isolated,
                glyph_bbox=(0, 0, 0, 0),
                component_count=0,
                is_empty=True
            )

        gx, gy, gw, gh = cv2.boundingRect(pts)
        pad = 2
        gx1 = max(0, gx - pad)
        gy1 = max(0, gy - pad)
        gx2 = min(cw, gx + gw + pad)
        gy2 = min(ch, gy + gh + pad)

        return ExtractedGlyphResult(
            cell_box=cell_box,
            raw_cell_crop=raw_crop,
            norm_gray_cell=norm_gray,
            isolated_binary_mask=full_isolated,
            glyph_bbox=(gx1, gy1, gx2, gy2),
            component_count=len(selected_lbls),
            is_empty=False,
            clipped_border=clipped_detected
        )
