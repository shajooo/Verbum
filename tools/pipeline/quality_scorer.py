"""
Quality Scoring and Outlier Classification for Extracted Glyphs.
Labels samples as GOOD, REVIEW, or REJECT with detailed metrics.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple, Dict, Any

import cv2
import numpy as np

from tools.pipeline.cell_extractor import ExtractedGlyphResult


@dataclass
class QualityAssessment:
    score: float             # 0.0 to 1.0
    status: str              # GOOD, REVIEW, REJECT
    confidence: float        # 0.0 to 1.0
    issues: List[str]
    contrast: float
    blur_variance: float
    ink_area: int


class QualityScorer:
    """Evaluates glyph visual fidelity, ink continuity, and segmentation sanity."""

    @staticmethod
    def assess_glyph(
        glyph_result: ExtractedGlyphResult,
        norm_gray: np.ndarray,
        norm_bin: np.ndarray,
        norm_meta: Dict[str, Any]
    ) -> QualityAssessment:
        issues: List[str] = []
        char_meta = glyph_result.cell_box.char_meta
        
        # 1. Empty cell check
        if glyph_result.is_empty or norm_meta["ink_pixels"] == 0:
            return QualityAssessment(
                score=0.0,
                status="REJECT",
                confidence=0.0,
                issues=["EMPTY_CELL"],
                contrast=0.0,
                blur_variance=0.0,
                ink_area=0
            )

        ink_area = norm_meta["ink_pixels"]
        is_small_punct = char_meta.is_small_punct

        # Minimum ink area threshold
        min_ink = 8 if is_small_punct else 30
        if ink_area < min_ink:
            issues.append("INSUFFICIENT_INK")

        # 2. Contrast evaluation
        ink_mask = norm_bin > 0
        bg_mask = norm_bin == 0
        mean_bg = float(np.mean(norm_gray[bg_mask])) if np.any(bg_mask) else 255.0
        mean_ink = float(np.mean(norm_gray[ink_mask])) if np.any(ink_mask) else 0.0
        contrast = max(0.0, mean_bg - mean_ink)

        if contrast < 30.0:
            issues.append("LOW_CONTRAST")

        # 3. Blur / Sharpness check on the glyph bounding box (not whole white canvas)
        ink_pts = np.where(norm_bin > 0)
        if len(ink_pts[0]) > 0:
            y1, y2 = int(np.min(ink_pts[0])), int(np.max(ink_pts[0]))
            x1, x2 = int(np.min(ink_pts[1])), int(np.max(ink_pts[1]))
            crop = norm_gray[max(0, y1-2):min(128, y2+3), max(0, x1-2):min(128, x2+3)]
            lap = cv2.Laplacian(crop, cv2.CV_64F)
            blur_var = float(lap.var())
        else:
            blur_var = 0.0

        if blur_var < 15.0 and not is_small_punct and ink_area > 50:
            issues.append("SEVERE_BLUR")

        # 4. Clipping check
        if glyph_result.clipped_border:
            issues.append("TOUCHES_CELL_BORDER")

        # 5. Connected Component Sanity
        comp_count = glyph_result.component_count
        if char_meta.multi_component:
            # Expected multi-component ('i', 'j', ':', '()', '{}', '[]')
            if comp_count < 1:
                issues.append("MISSING_COMPONENTS")
            elif comp_count > 6:
                issues.append("EXCESSIVE_COMPONENTS")
        else:
            # Expected single main component
            if comp_count > 4:
                issues.append("FRAGMENTED_COMPONENTS")

        # 6. Aspect Ratio Anomaly
        aspect = norm_meta["aspect_ratio"]
        if not is_small_punct:
            if aspect < 0.10 or aspect > 7.0:
                issues.append("ABNORMAL_ASPECT_RATIO")

        # Compute composite quality score (0.0 to 1.0)
        penalties = 0.0
        if "EMPTY_CELL" in issues:
            penalties += 1.0
        if "INSUFFICIENT_INK" in issues:
            penalties += 0.4
        if "LOW_CONTRAST" in issues:
            penalties += 0.25
        if "SEVERE_BLUR" in issues:
            penalties += 0.3
        if "TOUCHES_CELL_BORDER" in issues:
            penalties += 0.15
        if "MISSING_COMPONENTS" in issues:
            penalties += 0.35
        if "EXCESSIVE_COMPONENTS" in issues or "FRAGMENTED_COMPONENTS" in issues:
            penalties += 0.15
        if "ABNORMAL_ASPECT_RATIO" in issues:
            penalties += 0.25

        score = max(0.0, min(1.0, 1.0 - penalties))
        confidence = round(max(0.1, score), 3)

        # Classification
        if "EMPTY_CELL" in issues or score < 0.35:
            status = "REJECT"
        elif len(issues) > 0 or score < 0.80:
            status = "REVIEW"
        else:
            status = "GOOD"

        return QualityAssessment(
            score=round(score, 3),
            status=status,
            confidence=confidence,
            issues=issues,
            contrast=round(contrast, 2),
            blur_variance=round(blur_var, 2),
            ink_area=ink_area
        )
