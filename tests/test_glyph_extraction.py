"""
Automated unit tests for the Verbum Step 2 Glyph Extraction Pipeline.
Validates template schemas, image normalization, quality scoring, and extraction components.
"""

from pathlib import Path
import numpy as np
import pytest

from tools.pipeline.config import (
    SHEET_TEMPLATES,
    TOTAL_EXPECTED_GLYPHS,
    CHAR_DEFINITIONS,
    CharacterMeta,
    get_category_for_char,
    safe_char_filename,
)
from tools.pipeline.grid_detector import ExtractedCellBox
from tools.pipeline.cell_extractor import ExtractedGlyphResult
from tools.pipeline.normalizer import GlyphNormalizer
from tools.pipeline.quality_scorer import QualityScorer
from tools.pipeline.manifest import ManifestManager, ManifestEntry


class TestGlyphPipelineConfig:
    def test_total_glyph_count_equals_966(self):
        """Verify the exact count of expected glyphs across all 6 sheet templates."""
        total = sum(t.total_cells for t in SHEET_TEMPLATES.values())
        assert total == 966, f"Expected 966 total glyphs across templates, got {total}"
        assert total == TOTAL_EXPECTED_GLYPHS

    def test_category_mappings(self):
        """Ensure all character categories match the project specification."""
        assert get_category_for_char("A") == "uppercase"
        assert get_category_for_char("Z") == "uppercase"
        assert get_category_for_char("a") == "lowercase"
        assert get_category_for_char("z") == "lowercase"
        assert get_category_for_char("0") == "numbers"
        assert get_category_for_char("9") == "numbers"
        assert get_category_for_char(".") == "punctuation"
        assert get_category_for_char(":") == "punctuation"
        assert get_category_for_char("()") == "punctuation"
        assert get_category_for_char("{}") == "punctuation"
        assert get_category_for_char("[]") == "punctuation"

    def test_safe_filenames(self):
        """Ensure filenames do not contain reserved characters for Windows filesystems."""
        assert safe_char_filename("A") == "A"
        assert safe_char_filename(".") == "period"
        assert safe_char_filename(":") == "colon"
        assert safe_char_filename("()") == "parentheses"
        assert safe_char_filename("{}") == "braces"
        assert safe_char_filename("[]") == "brackets"
        assert safe_char_filename("-") == "hyphen"


class TestGlyphNormalizer:
    def test_normalization_dimensions_and_background(self):
        """Ensure normalized glyph outputs are exactly 128x128 with pure white background."""
        normalizer = GlyphNormalizer(target_size=128, margin=16)

        # Create synthetic ExtractedGlyphResult
        cell_box = ExtractedCellBox(
            block_idx=0,
            row_idx=0,
            col_idx=0,
            x1=10,
            y1=10,
            x2=70,
            y2=70,
            char_meta=CHAR_DEFINITIONS["a"]
        )
        norm_gray = np.full((60, 60), 240, dtype=np.uint8)
        norm_gray[15:45, 15:35] = 30
        isolated_mask = np.zeros((60, 60), dtype=np.uint8)
        isolated_mask[15:45, 15:35] = 255

        glyph_result = ExtractedGlyphResult(
            cell_box=cell_box,
            raw_cell_crop=np.stack([norm_gray]*3, axis=-1),
            norm_gray_cell=norm_gray,
            isolated_binary_mask=isolated_mask,
            glyph_bbox=(15, 15, 35, 45),
            component_count=1,
            is_empty=False
        )

        norm_gray_out, norm_bin_out, meta = normalizer.normalize(glyph_result)

        assert norm_gray_out.shape == (128, 128)
        assert norm_gray_out.dtype == np.uint8
        # Outer margins must be pure 255
        assert norm_gray_out[0, 0] == 255
        assert norm_gray_out[0, 127] == 255
        assert norm_gray_out[127, 0] == 255
        assert norm_gray_out[127, 127] == 255
        assert meta["ink_pixels"] > 0
        assert meta["scale"] > 0

    def test_empty_glyph_normalization(self):
        """Empty glyphs should produce blank 128x128 canvases."""
        normalizer = GlyphNormalizer(target_size=128, margin=16)
        cell_box = ExtractedCellBox(0, 0, 0, 0, 0, 50, 50, CHAR_DEFINITIONS["a"])
        glyph_result = ExtractedGlyphResult(
            cell_box=cell_box,
            raw_cell_crop=np.full((50, 50, 3), 255, dtype=np.uint8),
            norm_gray_cell=np.full((50, 50), 255, dtype=np.uint8),
            isolated_binary_mask=np.zeros((50, 50), dtype=np.uint8),
            glyph_bbox=(0, 0, 0, 0),
            component_count=0,
            is_empty=True
        )
        norm_gray, norm_bin, meta = normalizer.normalize(glyph_result)
        assert norm_gray.shape == (128, 128)
        assert np.all(norm_gray == 255)
        assert meta["ink_pixels"] == 0


class TestQualityScorer:
    def test_clean_glyph_scoring(self):
        """Synthetic high-contrast glyph should score as GOOD."""
        cell_box = ExtractedCellBox(0, 0, 0, 0, 0, 60, 60, CHAR_DEFINITIONS["O"])
        norm_gray = np.full((60, 60), 245, dtype=np.uint8)
        for y in range(15, 45):
            for x in range(15, 45):
                if 25 <= (y - 30)**2 + (x - 30)**2 <= 140:
                    norm_gray[y, x] = 20

        mask = np.where(norm_gray < 180, 255, 0).astype(np.uint8)
        glyph_result = ExtractedGlyphResult(
            cell_box=cell_box,
            raw_cell_crop=np.stack([norm_gray]*3, axis=-1),
            norm_gray_cell=norm_gray,
            isolated_binary_mask=mask,
            glyph_bbox=(15, 15, 45, 45),
            component_count=1,
            is_empty=False,
            clipped_border=False
        )

        normalizer = GlyphNormalizer(128, 16)
        c_gray, c_bin, meta = normalizer.normalize(glyph_result)

        assessment = QualityScorer.assess_glyph(glyph_result, c_gray, c_bin, meta)
        assert assessment.status == "GOOD"
        assert len(assessment.issues) == 0
        assert assessment.score >= 0.9

    def test_empty_cell_scoring(self):
        """Empty cells should be classified as REJECT."""
        cell_box = ExtractedCellBox(0, 0, 0, 0, 0, 60, 60, CHAR_DEFINITIONS["A"])
        glyph_result = ExtractedGlyphResult(
            cell_box=cell_box,
            raw_cell_crop=np.full((60, 60, 3), 255, dtype=np.uint8),
            norm_gray_cell=np.full((60, 60), 255, dtype=np.uint8),
            isolated_binary_mask=np.zeros((60, 60), dtype=np.uint8),
            glyph_bbox=(0, 0, 0, 0),
            component_count=0,
            is_empty=True
        )
        normalizer = GlyphNormalizer(128, 16)
        c_gray, c_bin, meta = normalizer.normalize(glyph_result)
        assessment = QualityScorer.assess_glyph(glyph_result, c_gray, c_bin, meta)
        assert assessment.status == "REJECT"
        assert "EMPTY_CELL" in assessment.issues


class TestManifestManager:
    def test_manifest_recording(self, tmp_path):
        """Verify CSV and JSON manifest serialization and parsing."""
        manager = ManifestManager(metadata_dir=tmp_path)
        entry = ManifestEntry(
            glyph_id="test_A_001",
            label="A",
            char="A",
            category="uppercase",
            source_image="test.jpg",
            sheet_id="test_sheet",
            block_idx=0,
            row=0,
            column=0,
            crop_x1=10,
            crop_y1=10,
            crop_x2=50,
            crop_y2=50,
            norm_size=128,
            scale=2.0,
            ink_pixels=450,
            contrast=85.0,
            blur_variance=45.0,
            quality_score=1.0,
            confidence=1.0,
            review_status="GOOD",
            issues="NONE",
            output_path=str(tmp_path / "A_001.png")
        )
        manager.add_entry(entry)
        csv_file, json_file = manager.write_manifests()

        assert csv_file.exists()
        assert json_file.exists()
        assert csv_file.stat().st_size > 0
        assert json_file.stat().st_size > 0
