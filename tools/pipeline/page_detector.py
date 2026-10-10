"""
Page and Sheet Detection & Perspective Rectification.
"""
from __future__ import annotations

import math
from typing import Dict, Optional, Tuple, Any

import cv2
import numpy as np


class PageDetector:
    """Detects sheet boundary, estimates tilt/perspective, and rectifies image."""

    @staticmethod
    def estimate_tilt_angle(gray_img: np.ndarray) -> float:
        """
        Estimates global tilt angle in degrees using dominant Hough line orientations.
        Returns angle in degrees (clockwise positive).
        """
        h, w = gray_img.shape
        edges = cv2.Canny(gray_img, 50, 150)
        lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=80, minLineLength=w // 6, maxLineGap=20)
        
        if lines is None or len(lines) == 0:
            return 0.0

        angles = []
        for line in lines:
            pts = line.flatten()
            if len(pts) >= 4:
                x1, y1, x2, y2 = map(int, pts[:4])
                dx = x2 - x1
                dy = y2 - y1
                if abs(dx) > abs(dy) * 2:  # near-horizontal line
                    angle = math.degrees(math.atan2(dy, dx))
                    if abs(angle) < 15.0:
                        angles.append(angle)

        if not angles:
            return 0.0

        median_angle = float(np.median(angles))
        return median_angle

    @staticmethod
    def rectify_sheet(
        bgr_img: np.ndarray,
        forced_deskew_angle: Optional[float] = None
    ) -> Tuple[np.ndarray, Dict[str, Any]]:
        """
        Rectifies sheet perspective and rotational tilt.
        """
        h, w = bgr_img.shape[:2]
        gray = cv2.cvtColor(bgr_img, cv2.COLOR_BGR2GRAY)

        if forced_deskew_angle is not None:
            angle = forced_deskew_angle
        else:
            angle = PageDetector.estimate_tilt_angle(gray)

        rect_meta = {
            "tilt_angle_deg": round(angle, 2),
            "method": "rotational_affine" if abs(angle) > 0.3 else "identity"
        }

        # If tilt is significant (> 0.3 degrees), deskew
        if abs(angle) > 0.3:
            center = (w / 2.0, h / 2.0)
            M = cv2.getRotationMatrix2D(center, angle, 1.0)
            rectified = cv2.warpAffine(
                bgr_img, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
            )
            return rectified, rect_meta
        else:
            return bgr_img.copy(), rect_meta
