"""
Production-Quality Automatic Glyph Extraction Pipeline.
Extracts clean, labeled, normalized character images from raw handwriting sheet photos.
"""
from __future__ import annotations

import argparse
import glob
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

# Ensure project root in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import cv2
import numpy as np

from tools.pipeline.config import get_template_for_sheet, SheetTemplate, CHAR_DEFINITIONS
from tools.pipeline.image_io import ImageLoader
from tools.pipeline.page_detector import PageDetector
from tools.pipeline.grid_detector import GridDetector, ExtractedCellBox
from tools.pipeline.cell_extractor import CellExtractor, ExtractedGlyphResult
from tools.pipeline.normalizer import GlyphNormalizer
from tools.pipeline.quality_scorer import QualityScorer, QualityAssessment
from tools.pipeline.manifest import ManifestManager, ManifestEntry
from tools.build_contact_sheet import build_all_contact_sheets
from tools.inspect_grid import inspect_sheet_grid


class GlyphExtractorEngine:
    """Orchestrates the end-to-end extraction pipeline."""

    def __init__(
        self,
        output_glyphs_dir: str | Path = "dataset/glyphs",
        output_review_dir: str | Path = "dataset/review",
        metadata_dir: str | Path = "metadata",
        target_size: int = 128,
        margin: int = 16
    ):
        self.glyphs_dir = Path(output_glyphs_dir)
        self.review_dir = Path(output_review_dir)
        self.metadata_dir = Path(metadata_dir)
        
        self.normalizer = GlyphNormalizer(target_size=target_size, margin=margin)
        self.manifest = ManifestManager(metadata_dir=metadata_dir)

        # Ensure output directories exist
        self.glyphs_dir.mkdir(parents=True, exist_ok=True)
        self.review_dir.mkdir(parents=True, exist_ok=True)

    def process_sheet(
        self,
        sheet_path: str | Path,
        generate_debug_vis: bool = True
    ) -> Dict[str, Any]:
        sheet_p = Path(sheet_path)
        print(f"\n==================================================")
        print(f"[*] Processing Sheet: {sheet_p.name}")
        print(f"==================================================")

        stats = {
            "sheet_file": sheet_p.name,
            "expected_cells": 0,
            "detected_cells": 0,
            "extracted_glyphs": 0,
            "good_count": 0,
            "review_count": 0,
            "reject_count": 0,
            "errors": []
        }

        # 1. Image Loading
        try:
            raw_bgr, img_meta = ImageLoader.load_image(sheet_p)
            print(f"  [1/6] Loaded image: {img_meta['width']}x{img_meta['height']} (aspect={img_meta['aspect_ratio']})")
        except Exception as e:
            err_msg = f"PAGE_LOADING_FAILED: {e}"
            print(f"  [ERROR] {err_msg}")
            stats["errors"].append(err_msg)
            return stats

        # 2. Template Identification
        try:
            template = get_template_for_sheet(sheet_p.name)
            expected = sum(b.row_count * template.columns for b in template.blocks)
            stats["expected_cells"] = expected
            print(f"  [2/6] Template: '{template.template_id}' ({expected} expected cells)")
        except Exception as e:
            err_msg = f"TEMPLATE_LOOKUP_FAILED: {e}"
            print(f"  [ERROR] {err_msg}")
            stats["errors"].append(err_msg)
            return stats

        # 3. Page Detection & Perspective Rectification
        try:
            rect_bgr, rect_meta = PageDetector.rectify_sheet(raw_bgr, template.deskew_angle)
            print(f"  [3/6] Rectified sheet: tilt={rect_meta['tilt_angle_deg']} deg (method={rect_meta['method']})")
        except Exception as e:
            err_msg = f"PERSPECTIVE_RECTIFICATION_FAILED: {e}"
            print(f"  [ERROR] {err_msg}")
            stats["errors"].append(err_msg)
            return stats

        # 4. Grid Detection
        try:
            cells, grid_meta = GridDetector.detect_grid(rect_bgr, template)
            stats["detected_cells"] = len(cells)
            print(f"  [4/6] Detected grid: {len(cells)} cells found")
            if len(cells) != expected:
                print(f"  [WARNING] Cell count mismatch: Expected {expected}, Detected {len(cells)}")
        except Exception as e:
            err_msg = f"GRID_DETECTION_FAILED: {e}"
            print(f"  [ERROR] {err_msg}")
            stats["errors"].append(err_msg)
            return stats

        # Optional debug overlay
        if generate_debug_vis:
            inspect_sheet_grid(sheet_p)

        # 5. Cell Extraction, Line Suppression, Normalization & Quality Scoring
        print(f"  [5/6] Extracting glyphs and scoring quality...")
        sheet_id = template.template_id

        # Track sample index per character for naming A_001, A_002...
        char_sample_counts: Dict[str, int] = {}

        for cell_idx, cell in enumerate(cells):
            char_meta = cell.char_meta
            char_key = char_meta.folder_name

            current_idx = char_sample_counts.get(char_key, 0) + 1
            char_sample_counts[char_key] = current_idx
            glyph_id = f"{char_key}_{current_idx:03d}"

            # Extract cell and isolate handwriting
            glyph_res = CellExtractor.extract_glyph_from_cell(rect_bgr, cell)

            # Aspect-preserving normalization
            norm_gray, norm_bin, norm_meta = self.normalizer.normalize(glyph_res)

            # Quality Assessment
            qa = QualityScorer.assess_glyph(glyph_res, norm_gray, norm_bin, norm_meta)

            # Primary output destination is dataset/glyphs/<category>/<char>/
            primary_dir = self.glyphs_dir / char_meta.category / char_meta.folder_name
            primary_dir.mkdir(parents=True, exist_ok=True)
            out_img_path = primary_dir / f"{glyph_id}.png"

            # Save normalized anti-aliased glyph
            cv2.imwrite(str(out_img_path), norm_gray)
            stats["extracted_glyphs"] += 1

            if qa.status == "GOOD":
                stats["good_count"] += 1
            elif qa.status == "REVIEW":
                stats["review_count"] += 1
                review_flagged_dir = self.review_dir / "flagged" / char_meta.category / char_meta.folder_name
                review_flagged_dir.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(review_flagged_dir / f"{glyph_id}.png"), norm_gray)
            else:
                stats["reject_count"] += 1
                reject_dir = self.review_dir / "rejected" / char_meta.category / char_meta.folder_name
                reject_dir.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(reject_dir / f"{glyph_id}.png"), norm_gray)

            # Record manifest entry
            gx1, gy1, gx2, gy2 = glyph_res.glyph_bbox
            entry = ManifestEntry(
                glyph_id=glyph_id,
                label=char_meta.folder_name,
                char=char_meta.char,
                category=char_meta.category,
                source_image=sheet_p.name,
                sheet_id=sheet_id,
                block_idx=cell.block_idx,
                row=cell.row_idx,
                column=cell.col_idx,
                crop_x1=cell.x1 + gx1,
                crop_y1=cell.y1 + gy1,
                crop_x2=cell.x1 + gx2,
                crop_y2=cell.y1 + gy2,
                norm_size=self.normalizer.target_size,
                scale=norm_meta["scale"],
                ink_pixels=norm_meta["ink_pixels"],
                contrast=qa.contrast,
                blur_variance=qa.blur_variance,
                quality_score=qa.score,
                confidence=qa.confidence,
                review_status=qa.status,
                issues=";".join(qa.issues) if qa.issues else "NONE",
                output_path=str(out_img_path.resolve())
            )
            self.manifest.add_entry(entry)

        print(f"  [6/6] Sheet complete: {stats['extracted_glyphs']} glyphs | GOOD={stats['good_count']}, REVIEW={stats['review_count']}, REJECT={stats['reject_count']}")
        return stats

    def run_all(
        self,
        raw_dir: str | Path = "dataset/raw",
        generate_contact_sheets: bool = True
    ) -> Dict[str, Any]:
        raw_files = sorted(glob.glob(os.path.join(raw_dir, "*.jpg")) + glob.glob(os.path.join(raw_dir, "*.png")))
        print(f"Starting batch extraction on {len(raw_files)} raw sheets...")

        total_stats = {
            "total_sheets": len(raw_files),
            "expected_glyphs": 0,
            "detected_cells": 0,
            "extracted_glyphs": 0,
            "good_count": 0,
            "review_count": 0,
            "reject_count": 0,
            "sheet_results": []
        }

        t_start = time.perf_counter()

        for sheet_file in raw_files:
            try:
                res = self.process_sheet(sheet_file)
                total_stats["sheet_results"].append(res)
                total_stats["expected_glyphs"] += res["expected_cells"]
                total_stats["detected_cells"] += res["detected_cells"]
                total_stats["extracted_glyphs"] += res["extracted_glyphs"]
                total_stats["good_count"] += res["good_count"]
                total_stats["review_count"] += res["review_count"]
                total_stats["reject_count"] += res["reject_count"]
            except Exception as e:
                print(f"[FATAL SHEET ERROR] Error processing {sheet_file}: {e}")

        # Write manifest CSV and JSON
        csv_path, json_path = self.manifest.write_manifests()
        print(f"\nManifests saved:\n  - CSV: {csv_path}\n  - JSON: {json_path}")

        # Build QA Contact Sheets
        if generate_contact_sheets:
            print(f"\nGenerating Visual QA Contact Sheets...")
            cs_results = build_all_contact_sheets(csv_path, self.review_dir)
            for k, p in cs_results.items():
                print(f"  Contact Sheet [{k}]: {p}")

        elapsed = time.perf_counter() - t_start
        print(f"\n" + "=" * 50)
        print(f"BATCH EXTRACTION COMPLETE in {elapsed:.2f} seconds")
        print(f"  Total Sheets Processed: {total_stats['total_sheets']}")
        print(f"  Total Expected Glyphs:  {total_stats['expected_glyphs']}")
        print(f"  Total Cells Detected:   {total_stats['detected_cells']}")
        print(f"  Total Extracted Glyphs: {total_stats['extracted_glyphs']}")
        print(f"    - GOOD Samples:       {total_stats['good_count']}")
        print(f"    - REVIEW Samples:     {total_stats['review_count']}")
        print(f"    - REJECT Samples:     {total_stats['reject_count']}")
        print(f"=" * 50)

        return total_stats


def main():
    parser = argparse.ArgumentParser(description="Verbum Step 2 Automatic Glyph Extraction Pipeline.")
    parser.add_argument("--sheet", type=str, help="Process single raw sheet image")
    parser.add_argument("--all", action="store_true", help="Process all images in dataset/raw")
    parser.add_argument("--raw-dir", type=str, default="dataset/raw", help="Path to raw dataset directory")
    parser.add_argument("--glyphs-dir", type=str, default="dataset/glyphs", help="Output directory for clean glyphs")
    parser.add_argument("--review-dir", type=str, default="dataset/review", help="Output directory for reviews/contact sheets")
    parser.add_argument("--metadata-dir", type=str, default="metadata", help="Output directory for manifest files")
    parser.add_argument("--no-contact-sheets", action="store_true", help="Skip contact sheet generation")

    args = parser.parse_args()

    engine = GlyphExtractorEngine(
        output_glyphs_dir=args.glyphs_dir,
        output_review_dir=args.review_dir,
        metadata_dir=args.metadata_dir
    )

    if args.sheet:
        engine.process_sheet(args.sheet)
        engine.manifest.write_manifests()
        if not args.no_contact_sheets:
            build_all_contact_sheets(args.metadata_dir + "/glyph_manifest.csv", args.review_dir)
    else:
        engine.run_all(raw_dir=args.raw_dir, generate_contact_sheets=not args.no_contact_sheets)


if __name__ == "__main__":
    main()
