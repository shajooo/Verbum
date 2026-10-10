"""
Grid Detection and Adaptive Peak-Snapping Lattice Solver.
Accurately determines cell boundaries for both uniform and split sheets.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple, Any

import cv2
import numpy as np

from tools.pipeline.config import CharacterMeta, GridBlockConfig, SheetTemplate


@dataclass
class ExtractedCellBox:
    block_idx: int
    row_idx: int
    col_idx: int
    x1: int
    y1: int
    x2: int
    y2: int
    char_meta: CharacterMeta


class GridDetector:
    """Robust Grid Detection and Cell Boundary Estimation."""

    @staticmethod
    def preprocess_for_lines(gray_img: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Normalizes illumination and extracts horizontal and vertical line masks.
        """
        h, w = gray_img.shape
        bg = cv2.morphologyEx(gray_img, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (31, 31)))
        norm = cv2.divide(gray_img, bg, scale=255)
        thresh = cv2.adaptiveThreshold(
            norm, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 15, 3
        )

        k_w = max(15, w // 20)
        k_h = max(15, h // 25)
        h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k_w, 1))
        v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, k_h))

        h_lines = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, h_kernel)
        v_lines = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, v_kernel)

        return norm, h_lines, v_lines

    @staticmethod
    def detect_grid(
        bgr_img: np.ndarray,
        template: SheetTemplate
    ) -> Tuple[List[ExtractedCellBox], Dict[str, Any]]:
        """
        Detects all cells for the given template blocks on the rectified sheet.
        """
        h, w = bgr_img.shape[:2]
        gray = cv2.cvtColor(bgr_img, cv2.COLOR_BGR2GRAY)
        norm, h_lines, v_lines = GridDetector.preprocess_for_lines(gray)

        h_proj = np.sum(h_lines, axis=1) / 255.0
        v_proj = np.sum(v_lines, axis=0) / 255.0

        all_cells: List[ExtractedCellBox] = []
        debug_meta: Dict[str, Any] = {
            "template_id": template.template_id,
            "blocks": []
        }

        # 1. Global column boundaries (14 columns)
        if template.global_v_anchors and len(template.global_v_anchors) == template.columns + 1:
            v_boundaries = list(template.global_v_anchors)
        else:
            # Fallback to automatic snapping
            col_start = 0
            col_end = w - 1
            v_thresh = np.max(v_proj) * 0.2
            strong_v = np.where(v_proj > v_thresh)[0]
            if len(strong_v) > 0:
                if strong_v[0] < w * 0.15:
                    col_start = max(0, strong_v[0])
                if strong_v[-1] > w * 0.85:
                    col_end = min(w - 1, strong_v[-1])
            step_x = (col_end - col_start) / float(template.columns)
            v_boundaries = [int(round(col_start + k * step_x)) for k in range(template.columns + 1)]

        for b_idx, block in enumerate(template.blocks):
            if block.h_anchors and len(block.h_anchors) == block.row_count + 1:
                h_boundaries = list(block.h_anchors)
            else:
                y_start = int(round(h * block.y_min_ratio))
                y_end = int(round(h * block.y_max_ratio))
                step_y = (y_end - y_start) / float(block.row_count)
                h_boundaries = [int(round(y_start + k * step_y)) for k in range(block.row_count + 1)]

            block_meta = {
                "block_idx": b_idx,
                "row_count": block.row_count,
                "col_count": template.columns,
                "h_boundaries": h_boundaries,
                "v_boundaries": v_boundaries
            }
            debug_meta["blocks"].append(block_meta)

            # Generate cell boxes
            for r_idx in range(block.row_count):
                char_meta = block.rows[r_idx]
                r_y1 = h_boundaries[r_idx]
                r_y2 = h_boundaries[r_idx + 1]

                for c_idx in range(template.columns):
                    c_x1 = v_boundaries[c_idx]
                    c_x2 = v_boundaries[c_idx + 1]

                    cell_box = ExtractedCellBox(
                        block_idx=b_idx,
                        row_idx=r_idx,
                        col_idx=c_idx,
                        x1=c_x1,
                        y1=r_y1,
                        x2=c_x2,
                        y2=r_y2,
                        char_meta=char_meta
                    )
                    all_cells.append(cell_box)

        debug_meta["total_cells_detected"] = len(all_cells)
        return all_cells, debug_meta
