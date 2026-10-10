"""
Automated unit tests for Verbum Step 3: Handwriting Font Generation Pipeline.
Validates glyph extraction from dataset, vectorization, TrueType table structure,
OpenType tables, cmap coverage, specimen card rendering, and worker processes.
"""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import pytest
from fontTools.ttLib import TTFont

from app.font_generator import (
    validate_dataset,
    select_best_glyphs,
    create_handwriting_font,
    render_font_preview_specimen,
    FontBuildResult,
)
from app.font_worker import start_font_worker


@pytest.fixture(scope="module")
def manifest_path() -> Path:
    base = Path(__file__).resolve().parent.parent
    p = base / "metadata" / "glyph_manifest.json"
    assert p.exists(), f"Manifest file missing at {p}"
    return p


@pytest.fixture(scope="module")
def glyphs_dir() -> Path:
    base = Path(__file__).resolve().parent.parent
    p = base / "dataset" / "glyphs"
    return p


@pytest.fixture(scope="module")
def generated_font_dir(manifest_path) -> str:
    """Generate a test font once in a temporary directory for tests in this module."""
    temp_dir = tempfile.mkdtemp(prefix="verbum_test_font_")
    res = create_handwriting_font(
        manifest_path=str(manifest_path),
        glyphs_dir=str(manifest_path.parent.parent / "dataset" / "glyphs"),
        output_dir=temp_dir,
        font_name="Verbum Handwriting Test",
        build_otf=True,
    )
    assert res.success is True, f"Font generation failed: {res.error_message}"
    return temp_dir


class TestDatasetValidationAndSelection:
    def test_dataset_coverage_and_quality(self, manifest_path, glyphs_dir):
        """Verify the dataset has 100% coverage and zero rejected glyphs."""
        stats = validate_dataset(manifest_path, glyphs_dir)
        assert stats.is_valid is True
        assert stats.total_samples == 966
        assert stats.good_samples == 913
        assert stats.review_samples == 53
        assert stats.reject_samples == 0
        assert stats.uppercase_count == 26
        assert stats.lowercase_count == 26
        assert stats.numbers_count == 10
        assert stats.punctuation_count == 7

    def test_glyph_selection_picks_optimal_samples(self, manifest_path, glyphs_dir):
        """Verify glyph selection picks 1 sample per character class."""
        selected = select_best_glyphs(manifest_path, glyphs_dir)
        assert len(selected) >= 69
        # Check that essential categories are present
        for ch in ["A", "Z", "a", "z", "0", "9", ".", ",", ":", "-", "(", ")", "[", "]", "{", "}"]:
            assert ch in selected
            assert selected[ch].review_status in ("GOOD", "REVIEW")


class TestFontStructureAndMetrics:
    def test_font_files_exist(self, generated_font_dir):
        """Ensure both TTF and OTF files are generated and non-empty."""
        ttf = Path(generated_font_dir) / "Verbum_Handwriting_Test.ttf"
        otf = Path(generated_font_dir) / "Verbum_Handwriting_Test.otf"
        assert ttf.exists()
        assert ttf.stat().st_size > 5000
        assert otf.exists()
        assert otf.stat().st_size > 3000

    def test_truetype_tables_and_units_per_em(self, generated_font_dir):
        """Verify TrueType required tables and typographical units per EM = 1000."""
        ttf_path = Path(generated_font_dir) / "Verbum_Handwriting_Test.ttf"
        tt = TTFont(str(ttf_path))

        required_tables = {"head", "hhea", "maxp", "OS/2", "name", "cmap", "glyf", "hmtx", "post"}
        present_tables = set(tt.keys())
        assert required_tables.issubset(present_tables), f"Missing tables: {required_tables - present_tables}"

        head = tt["head"]
        assert head.unitsPerEm == 1000

        os2 = tt["OS/2"]
        assert os2.sCapHeight == 700
        assert os2.sxHeight == 490

    def test_opentype_cff_table(self, generated_font_dir):
        """Verify OTF file contains CFF table and standard OpenType structures."""
        otf_path = Path(generated_font_dir) / "Verbum_Handwriting_Test.otf"
        tt = TTFont(str(otf_path))

        required_tables = {"head", "hhea", "maxp", "OS/2", "name", "cmap", "CFF ", "hmtx", "post"}
        present_tables = set(tt.keys())
        assert required_tables.issubset(present_tables), f"Missing tables: {required_tables - present_tables}"

    def test_character_mapping_coverage(self, generated_font_dir):
        """Verify cmap table contains all required ASCII uppercase, lowercase, numbers, and split punctuation."""
        ttf_path = Path(generated_font_dir) / "Verbum_Handwriting_Test.ttf"
        tt = TTFont(str(ttf_path))
        cmap = tt.getBestCmap()

        # Check A-Z
        for code in range(ord("A"), ord("Z") + 1):
            assert code in cmap, f"Missing char {chr(code)} in cmap"

        # Check a-z
        for code in range(ord("a"), ord("z") + 1):
            assert code in cmap, f"Missing char {chr(code)} in cmap"

        # Check 0-9
        for code in range(ord("0"), ord("9") + 1):
            assert code in cmap, f"Missing char {chr(code)} in cmap"

        # Check individual punctuation including split pairs
        for sym in [".", ",", ":", "-", "(", ")", "[", "]", "{", "}", " "]:
            assert ord(sym) in cmap, f"Missing symbol '{sym}' (codepoint {ord(sym)}) in cmap"


class TestSpecimenAndWorker:
    def test_specimen_rendering(self, generated_font_dir):
        """Ensure font specimen card renders to PNG successfully."""
        ttf_path = Path(generated_font_dir) / "Verbum_Handwriting_Test.ttf"
        spec_png = Path(generated_font_dir) / "specimen_test.png"
        render_font_preview_specimen(str(ttf_path), str(spec_png))
        assert spec_png.exists()
        assert spec_png.stat().st_size > 1000

    def test_font_worker_multiprocessing(self, manifest_path):
        """Verify font worker subprocess executes and reports progress/results."""
        temp_dir = tempfile.mkdtemp(prefix="verbum_worker_font_")
        proc, q, cancel = start_font_worker(
            manifest_path=str(manifest_path),
            glyphs_dir=str(manifest_path.parent.parent / "dataset" / "glyphs"),
            output_dir=temp_dir,
            font_name="Worker Font",
            build_otf=False,
        )

        messages = []
        proc.join(timeout=30)
        assert not proc.is_alive()

        while not q.empty():
            messages.append(q.get_nowait())

        kinds = [m[0] for m in messages]
        assert "progress" in kinds
        assert "success" in kinds

        success_msg = next(m for m in messages if m[0] == "success")
        data = success_msg[1]
        assert Path(data["ttf_path"]).exists()
        assert data["glyph_count"] >= 70
