"""
Visual QA Contact Sheet Builder.
Generates structured visual contact sheets for all extracted character categories.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


def create_category_contact_sheet(
    category_name: str,
    manifest_entries: List[Dict[str, str]],
    output_path: Path,
    thumb_size: int = 64,
    pad: int = 4
) -> Optional[Path]:
    """
    Creates a contact sheet where each row corresponds to one character,
    and columns correspond to the 14 handwritten variations.
    """
    # Filter entries for category
    cat_entries = [e for e in manifest_entries if e["category"] == category_name]
    if not cat_entries:
        return None

    # Group entries by label maintaining row order
    by_label: Dict[str, List[Dict[str, str]]] = {}
    for e in cat_entries:
        lbl = e["label"]
        if lbl not in by_label:
            by_label[lbl] = []
        by_label[lbl].append(e)

    # Sort labels canonically
    if category_name == "uppercase":
        canonical = [chr(c) for c in range(ord('A'), ord('Z') + 1)]
        labels_order = [lbl for lbl in canonical if lbl in by_label]
    elif category_name == "lowercase":
        canonical = [chr(c) for c in range(ord('a'), ord('z') + 1)]
        labels_order = [lbl for lbl in canonical if lbl in by_label]
    elif category_name == "numbers":
        canonical = [str(d) for d in range(10)]
        labels_order = [lbl for lbl in canonical if lbl in by_label]
    elif category_name == "punctuation":
        canonical = ["period", "comma", "colon", "parentheses", "braces", "brackets", "hyphen"]
        labels_order = [lbl for lbl in canonical if lbl in by_label]
    else:
        labels_order = list(by_label.keys())

    num_rows = len(labels_order)
    max_cols = max((len(samples) for samples in by_label.values()), default=14)

    label_badge_w = 70
    row_h = thumb_size + 2 * pad
    sheet_w = label_badge_w + max_cols * (thumb_size + pad) + pad
    sheet_h = 40 + num_rows * row_h + pad

    canvas = np.full((sheet_h, sheet_w, 3), 245, dtype=np.uint8)

    # Header banner
    cv2.rectangle(canvas, (0, 0), (sheet_w, 36), (45, 45, 50), -1)
    title_text = f"VERBUM QA CONTACT SHEET - CATEGORY: {category_name.upper()} ({num_rows} characters x {max_cols} variations)"
    cv2.putText(canvas, title_text, (15, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)

    for r_idx, lbl in enumerate(labels_order):
        y_top = 40 + r_idx * row_h
        y_bot = y_top + thumb_size + pad

        # Alternating row background
        bg_col = (255, 255, 255) if r_idx % 2 == 0 else (238, 240, 243)
        cv2.rectangle(canvas, (0, y_top), (sheet_w, y_bot), bg_col, -1)

        # Label badge
        cv2.rectangle(canvas, (pad, y_top + pad), (label_badge_w - pad, y_bot - pad), (220, 225, 230), -1)
        cv2.rectangle(canvas, (pad, y_top + pad), (label_badge_w - pad, y_bot - pad), (180, 185, 190), 1)
        
        display_char = by_label[lbl][0].get("char", lbl)
        cv2.putText(
            canvas,
            display_char,
            (pad + 12, y_top + thumb_size // 2 + 8),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (20, 20, 20),
            2,
            cv2.LINE_AA
        )

        # Samples
        samples = by_label[lbl]
        for c_idx, sample in enumerate(samples):
            x_left = label_badge_w + c_idx * (thumb_size + pad)
            img_path = sample.get("output_path", "")

            # Default cell placeholder
            cv2.rectangle(canvas, (x_left, y_top + pad), (x_left + thumb_size, y_top + pad + thumb_size), (210, 210, 210), 1)

            if os.path.exists(img_path):
                glyph_img = cv2.imread(img_path)
                if glyph_img is not None:
                    thumb = cv2.resize(glyph_img, (thumb_size, thumb_size), interpolation=cv2.INTER_AREA)
                    canvas[y_top + pad:y_top + pad + thumb_size, x_left:x_left + thumb_size] = thumb

                    # Border color based on review status
                    status = sample.get("review_status", "GOOD")
                    if status == "GOOD":
                        b_col = (0, 180, 0)
                    elif status == "REVIEW":
                        b_col = (0, 140, 255)  # Orange
                    else:
                        b_col = (0, 0, 255)    # Red

                    cv2.rectangle(canvas, (x_left, y_top + pad), (x_left + thumb_size, y_top + pad + thumb_size), b_col, 1)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output_path), canvas)
    print(f"[build_contact_sheet] Generated category sheet: {output_path}")
    return output_path


def create_flagged_review_sheet(
    manifest_entries: List[Dict[str, str]],
    output_path: Path,
    thumb_size: int = 96,
    pad: int = 8
) -> Optional[Path]:
    """Generates visual QA sheet for samples marked as REVIEW or REJECT."""
    flagged = [e for e in manifest_entries if e.get("review_status") in ("REVIEW", "REJECT")]
    if not flagged:
        print("[build_contact_sheet] No samples flagged for REVIEW or REJECT.")
        return None

    cols = 8
    rows = int(np.ceil(len(flagged) / float(cols)))

    cell_w = thumb_size + 2 * pad
    cell_h = thumb_size + 38 + 2 * pad

    sheet_w = cols * cell_w + pad
    sheet_h = 50 + rows * cell_h + pad

    canvas = np.full((sheet_h, sheet_w, 3), 240, dtype=np.uint8)

    # Header
    cv2.rectangle(canvas, (0, 0), (sheet_w, 40), (40, 40, 45), -1)
    cv2.putText(canvas, f"FLAGGED GLYPH AUDIT SHEET - {len(flagged)} SAMPLES NEEDING REVIEW / REJECTED", (15, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 255), 1, cv2.LINE_AA)

    for idx, item in enumerate(flagged):
        r = idx // cols
        c = idx % cols
        x0 = pad + c * cell_w
        y0 = 50 + r * cell_h

        # Card bg
        status = item.get("review_status", "REVIEW")
        card_col = (255, 255, 255)
        cv2.rectangle(canvas, (x0, y0), (x0 + cell_w - pad, y0 + cell_h - pad), card_col, -1)
        border_col = (0, 0, 220) if status == "REJECT" else (0, 140, 255)
        cv2.rectangle(canvas, (x0, y0), (x0 + cell_w - pad, y0 + cell_h - pad), border_col, 2)

        # Image
        img_p = item.get("output_path", "")
        if os.path.exists(img_p):
            im = cv2.imread(img_p)
            if im is not None:
                t = cv2.resize(im, (thumb_size, thumb_size), interpolation=cv2.INTER_AREA)
                canvas[y0 + pad:y0 + pad + thumb_size, x0 + pad:x0 + pad + thumb_size] = t

        # Text metadata
        lbl_str = f"{item['char']} ({status})"
        cv2.putText(canvas, lbl_str, (x0 + pad, y0 + thumb_size + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.42, border_col, 1, cv2.LINE_AA)
        
        issue_str = item.get("issues", "")[:18]
        cv2.putText(canvas, issue_str, (x0 + pad, y0 + thumb_size + 32), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (80, 80, 80), 1, cv2.LINE_AA)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output_path), canvas)
    print(f"[build_contact_sheet] Generated flagged review sheet: {output_path}")
    return output_path


def build_all_contact_sheets(
    manifest_csv_path: str | Path = "metadata/glyph_manifest.csv",
    output_dir: str | Path = "dataset/review"
) -> Dict[str, Path]:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    entries = []
    with open(manifest_csv_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            entries.append(row)

    results = {}
    categories = ["uppercase", "lowercase", "numbers", "punctuation"]
    for cat in categories:
        cat_file = out_dir / f"contact_sheet_{cat}.png"
        p = create_category_contact_sheet(cat, entries, cat_file)
        if p:
            results[cat] = p

    flagged_file = out_dir / "contact_sheet_flagged_review.png"
    p_fl = create_flagged_review_sheet(entries, flagged_file)
    if p_fl:
        results["flagged"] = p_fl

    return results


def main():
    parser = argparse.ArgumentParser(description="Build visual contact sheets from glyph manifest.")
    parser.add_argument("--manifest", type=str, default="metadata/glyph_manifest.csv", help="Path to manifest CSV")
    parser.add_argument("--output-dir", type=str, default="dataset/review", help="Output directory for contact sheets")

    args = parser.parse_args()
    build_all_contact_sheets(args.manifest, args.output_dir)


if __name__ == "__main__":
    main()
