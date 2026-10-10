"""
Empirical Method Evaluation Script for Step 2 Handwriting Glyph Extraction.

Compares candidate methods across all key pipeline stages:
  Stage A: Page detection / Rectification
  Stage B: Perspective correction
  Stage C: Grid detection (Morphology vs Hough vs LSD vs Projection Fitting)
  Stage D: Thresholding / Lighting normalization (Otsu vs Adaptive vs Sauvola vs IllumNorm)
  Stage E: Grid line suppression (Inward crop vs Morph subtraction vs Border component filter vs Hybrid)
  Stage F: Glyph component grouping (Largest CC vs Distance Clustering vs Label-Aware Grouping)
  Stage G: Normalization (Stretched vs Aspect-preserving center)
"""
import os
import glob
import time
import cv2
import numpy as np
from PIL import Image

RAW_DIR = "dataset/raw"
EVAL_DIR = "dataset/processed/eval_comparison"

os.makedirs(EVAL_DIR, exist_ok=True)

def evaluate_thresholding(img_path):
    print(f"\n--- Evaluating Thresholding on {os.path.basename(img_path)} ---")
    img = cv2.imread(img_path)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # 1. Global Otsu
    t0 = time.perf_counter()
    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    t_otsu = (time.perf_counter() - t0) * 1000
    
    # 2. Adaptive Gaussian
    t0 = time.perf_counter()
    adapt_gauss = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 25, 10
    )
    t_adapt = (time.perf_counter() - t0) * 1000
    
    # 3. Illumination Normalization (Background division) + Otsu
    t0 = time.perf_counter()
    # Estimate background with large morphological closing / blur
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (41, 41))
    bg = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, kernel)
    norm = cv2.divide(gray, bg, scale=255)
    # Now Otsu or soft adaptive on normalized
    _, norm_otsu = cv2.threshold(norm, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    t_norm = (time.perf_counter() - t0) * 1000

    # 4. Sauvola-style local thresholding
    t0 = time.perf_counter()
    k_sauvola = 0.2
    R = 128
    mean = cv2.boxFilter(gray.astype(np.float32), -1, (25, 25))
    sqmean = cv2.boxFilter((gray.astype(np.float32))**2, -1, (25, 25))
    var = sqmean - mean**2
    var[var < 0] = 0
    std = np.sqrt(var)
    sauvola_thresh = mean * (1 + k_sauvola * (std / R - 1))
    sauvola = np.where(gray < sauvola_thresh, 255, 0).astype(np.uint8)
    t_sauvola = (time.perf_counter() - t0) * 1000

    base = os.path.splitext(os.path.basename(img_path))[0]
    cv2.imwrite(os.path.join(EVAL_DIR, f"{base}_thresh_1_otsu.png"), otsu)
    cv2.imwrite(os.path.join(EVAL_DIR, f"{base}_thresh_2_adapt.png"), adapt_gauss)
    cv2.imwrite(os.path.join(EVAL_DIR, f"{base}_thresh_3_norm_otsu.png"), norm_otsu)
    cv2.imwrite(os.path.join(EVAL_DIR, f"{base}_thresh_4_sauvola.png"), sauvola)
    
    print(f"  Otsu: {t_otsu:.2f} ms | Foreground ratio: {np.mean(otsu)/255:.3f}")
    print(f"  Adaptive Gaussian: {t_adapt:.2f} ms | Foreground ratio: {np.mean(adapt_gauss)/255:.3f}")
    print(f"  IllumNorm + Otsu: {t_norm:.2f} ms | Foreground ratio: {np.mean(norm_otsu)/255:.3f}")
    print(f"  Sauvola: {t_sauvola:.2f} ms | Foreground ratio: {np.mean(sauvola)/255:.3f}")
    
    return {
        "otsu": otsu,
        "adaptive": adapt_gauss,
        "norm_otsu": norm_otsu,
        "sauvola": sauvola
    }

def evaluate_grid_detection(img_path):
    print(f"\n--- Evaluating Grid Detection on {os.path.basename(img_path)} ---")
    img = cv2.imread(img_path)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    base = os.path.splitext(os.path.basename(img_path))[0]
    
    # Preprocessing: background normalization to remove shadows
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (31, 31))
    bg = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, kernel)
    norm = cv2.divide(gray, bg, scale=255)
    thresh = cv2.adaptiveThreshold(
        norm, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 15, 3
    )

    # Method 1: HoughLinesP
    t0 = time.perf_counter()
    edges = cv2.Canny(norm, 50, 150)
    lines_p = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=100, minLineLength=w // 5, maxLineGap=20)
    t_hough = (time.perf_counter() - t0) * 1000
    n_hough = len(lines_p) if lines_p is not None else 0

    hough_vis = img.copy()
    if lines_p is not None:
        for line in lines_p:
            pts = line.flatten()
            if len(pts) >= 4:
                x1, y1, x2, y2 = map(int, pts[:4])
                cv2.line(hough_vis, (x1, y1), (x2, y2), (0, 0, 255), 1)
    cv2.imwrite(os.path.join(EVAL_DIR, f"{base}_grid_1_hough.png"), hough_vis)

    # Method 2: LSD (Line Segment Detector)
    t0 = time.perf_counter()
    lsd = cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD)
    lines_lsd, _, _, _ = lsd.detect(norm)
    t_lsd = (time.perf_counter() - t0) * 1000
    n_lsd = len(lines_lsd) if lines_lsd is not None else 0
    
    lsd_vis = img.copy()
    if lines_lsd is not None:
        for line in lines_lsd:
            pts = line.flatten()
            if len(pts) >= 4:
                x1, y1, x2, y2 = map(int, pts[:4])
                if np.hypot(x2 - x1, y2 - y1) > w // 6:
                    cv2.line(lsd_vis, (x1, y1), (x2, y2), (0, 255, 0), 1)
    cv2.imwrite(os.path.join(EVAL_DIR, f"{base}_grid_2_lsd.png"), lsd_vis)

    # Method 3: Morphology Line Filtering + 1D Projections
    t0 = time.perf_counter()
    # Horizontal lines kernel (must be wide)
    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(15, w // 20), 1))
    h_lines = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, h_kernel)
    
    # Vertical lines kernel (must be tall)
    v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(15, h // 25)))
    v_lines = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, v_kernel)

    # Projections
    h_proj = np.sum(h_lines, axis=1) / 255.0
    v_proj = np.sum(v_lines, axis=0) / 255.0

    # Peak detection helper
    def find_peaks_1d(arr, min_dist, rel_thresh=0.15):
        max_val = np.max(arr)
        if max_val == 0:
            return []
        thresh_val = max_val * rel_thresh
        peaks = []
        i = 1
        while i < len(arr) - 1:
            if arr[i] > thresh_val and arr[i] >= arr[i - 1] and arr[i] >= arr[i + 1]:
                # find maximum in local window
                w_end = min(len(arr), i + min_dist)
                best_idx = i + int(np.argmax(arr[i:w_end]))
                peaks.append(best_idx)
                i = best_idx + min_dist
            else:
                i += 1
        return peaks

    h_peaks = find_peaks_1d(h_proj, min_dist=max(10, h // 35), rel_thresh=0.2)
    v_peaks = find_peaks_1d(v_proj, min_dist=max(10, w // 25), rel_thresh=0.2)
    t_morph = (time.perf_counter() - t0) * 1000

    morph_vis = img.copy()
    for y in h_peaks:
        cv2.line(morph_vis, (0, y), (w, y), (255, 0, 0), 2)
    for x in v_peaks:
        cv2.line(morph_vis, (x, 0), (x, h), (0, 255, 255), 2)
    cv2.imwrite(os.path.join(EVAL_DIR, f"{base}_grid_3_morph.png"), morph_vis)

    print(f"  HoughLinesP: {t_hough:.2f} ms | Segments: {n_hough}")
    print(f"  LSD: {t_lsd:.2f} ms | Segments: {n_lsd}")
    print(f"  Morph + Projection: {t_morph:.2f} ms | H-peaks: {len(h_peaks)}, V-peaks: {len(v_peaks)}")

    return {
        "hough_n": n_hough,
        "lsd_n": n_lsd,
        "h_peaks": h_peaks,
        "v_peaks": v_peaks
    }

def evaluate_line_suppression(sample_cell_bgr):
    """
    Evaluates different strategies for removing grid lines from a cell:
      Method E1: Plain Inward Crop (8% inset)
      Method E2: Morphological Line Subtraction
      Method E3: Border Component Scrubbing
      Method E4: Hybrid (Adaptive Inset + Perimeter Component Pruning)
    """
    gray = cv2.cvtColor(sample_cell_bgr, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    
    # Binarize with local adaptive
    thresh = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 15, 4
    )
    
    # E1: Simple Inset Crop (8% on each side)
    inset_y = max(2, int(h * 0.08))
    inset_x = max(2, int(w * 0.08))
    e1_crop = thresh[inset_y:h-inset_y, inset_x:w-inset_x]
    
    # E2: Global Morphological Line Subtraction
    h_kern = cv2.getStructuringElement(cv2.MORPH_RECT, (int(w * 0.6), 1))
    v_kern = cv2.getStructuringElement(cv2.MORPH_RECT, (1, int(h * 0.6)))
    h_lines = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, h_kern)
    v_lines = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, v_kern)
    line_mask = cv2.bitwise_or(h_lines, v_lines)
    # Dilate line mask slightly to cover line thickness
    line_mask = cv2.dilate(line_mask, cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2)))
    e2_subtracted = cv2.bitwise_and(thresh, cv2.bitwise_not(line_mask))
    
    # E3: Border Component Filtering on exact cell
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(thresh, connectivity=8)
    e3_cleaned = np.zeros_like(thresh)
    for lbl in range(1, num_labels):
        x, y, cw, ch, area = stats[lbl]
        # check if component touches the cell border
        touches_border = (x <= 1 or y <= 1 or (x + cw) >= w - 1 or (y + ch) >= h - 1)
        aspect = max(cw / (ch + 1e-5), ch / (cw + 1e-5))
        # If it touches border and is elongated or spans a significant fraction of border, it's a grid line
        is_grid_artifact = touches_border and (aspect > 3.0 or (cw > w * 0.6 and ch < h * 0.2) or (ch > h * 0.6 and cw < w * 0.2))
        if not is_grid_artifact:
            e3_cleaned[labels == lbl] = 255
            
    # E4: Hybrid: Safe Inset (4 pixels) + Perimeter Component Pruning
    safe_m = 4
    if h > 2 * safe_m and w > 2 * safe_m:
        sub = thresh[safe_m:h-safe_m, safe_m:w-safe_m]
        sub_h, sub_w = sub.shape
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(sub, connectivity=8)
        e4_hybrid = np.zeros_like(sub)
        for lbl in range(1, num_labels):
            x, y, cw, ch, area = stats[lbl]
            touches_border = (x <= 1 or y <= 1 or (x + cw) >= sub_w - 1 or (y + ch) >= sub_h - 1)
            aspect = max(cw / (ch + 1e-5), ch / (cw + 1e-5))
            is_grid = touches_border and (aspect > 2.5 or cw > sub_w * 0.5 or ch > sub_h * 0.5)
            if not is_grid:
                e4_hybrid[labels == lbl] = 255
    else:
        e4_hybrid = thresh.copy()
        
    return {
        "e1_inset": e1_crop,
        "e2_sub": e2_subtracted,
        "e3_border": e3_cleaned,
        "e4_hybrid": e4_hybrid
    }

if __name__ == "__main__":
    files = sorted(glob.glob(os.path.join(RAW_DIR, "*.jpg")))
    for f in files:
        evaluate_thresholding(f)
        evaluate_grid_detection(f)
