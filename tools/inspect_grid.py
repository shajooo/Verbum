"""
Grid and Cell Boundary Inspector Tool.
Overlays detected grid lines, cell boundaries, and expected labels onto sheets.
"""
from __future__ import annotations

import argparse
import glob
import os
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import cv2
import numpy as np

from tools.pipeline.config import get_template_for_sheet
from tools.pipeline.image_io import ImageLoader
from tools.pipeline.page_detector import PageDetector
from tools.pipeline.grid_detector import GridDetector


def inspect_sheet_grid(
    image_path: str | Path,
    output_dir: str | Path = "dataset/processed/debug_inspect"
) -> Path:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    img_bgr, meta = ImageLoader.load_image(image_path)
    template = get_template_for_sheet(Path(image_path).name)

    # Rectify sheet
    rect_img, rect_meta = PageDetector.rectify_sheet(img_bgr, template.deskew_angle)

    # Detect grid
    cells, grid_meta = GridDetector.detect_grid(rect_img, template)

    # Draw visualization
    vis = rect_img.copy()

    # Draw cell boundaries and labels
    for cell in cells:
        # Green cell border
        cv2.rectangle(vis, (cell.x1, cell.y1), (cell.x2, cell.y2), (0, 220, 0), 1)

        # Label badge in corner
        label_text = cell.char_meta.char
        # Put small text in top-left
        cv2.putText(
            vis,
            label_text,
            (cell.x1 + 3, cell.y1 + 14),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.4,
            (0, 0, 255),
            1,
            cv2.LINE_AA
        )

    out_file = out_dir / f"grid_inspect_{Path(image_path).stem}.png"
    cv2.imwrite(str(out_file), vis)
    print(f"[inspect_grid] Saved visualization: {out_file} ({len(cells)} cells)")
    return out_file


def main():
    parser = argparse.ArgumentParser(description="Inspect sheet grid and cell boundaries.")
    parser.add_argument("--image", type=str, help="Path to single raw sheet image")
    parser.add_argument("--all", action="store_true", help="Inspect all raw images in dataset/raw")
    parser.add_argument("--output-dir", type=str, default="dataset/processed/debug_inspect", help="Output directory")

    args = parser.parse_args()

    if args.all or not args.image:
        raw_files = sorted(glob.glob("dataset/raw/*.jpg"))
        for f in raw_files:
            inspect_sheet_grid(f, args.output_dir)
    else:
        inspect_sheet_grid(args.image, args.output_dir)


if __name__ == "__main__":
    main()
