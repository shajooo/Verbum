"""
Automated unit tests for Verbum Step 4: Searchable/Selectable PDF Generation Pipeline.
Validates ReportLab font embedding, multi-page layout, PyMuPDF text searchability/selection,
page preview rasterization, unsupported glyph tracking, and worker multiprocessing.
"""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import pymupdf
import pytest

from app.pdf_generator import (
    generate_handwritten_pdf,
    validate_pdf_document,
    PDFBuildResult,
)
from app.pdf_worker import start_pdf_worker


@pytest.fixture(scope="module")
def ttf_font_path() -> str:
    """Path to the generated Verbum handwriting font."""
    font = Path(__file__).resolve().parent.parent / "fonts" / "Verbum_Handwriting.ttf"
    assert font.exists(), f"Verbum_Handwriting.ttf not found at {font}"
    return str(font)


class TestPDFGenerationAndEmbedding:
    def test_single_page_pdf_generation(self, ttf_font_path):
        """Generate a single-page document and verify custom font embedding & selectable text."""
        temp_dir = tempfile.mkdtemp(prefix="verbum_test_pdf_")
        out_pdf = os.path.join(temp_dir, "test_doc.pdf")

        content = "Hello world! This is a test of the personal handwriting font.\nVerbum project 2026."
        res = generate_handwritten_pdf(
            content=content,
            title="Single Page Test",
            font_path=ttf_font_path,
            output_pdf_path=out_pdf,
            generate_preview=True,
        )

        assert res.success is True, f"PDF generation failed: {res.error_message}"
        assert res.page_count == 1
        assert Path(out_pdf).exists()
        assert Path(out_pdf).stat().st_size > 1000

        # Validate with PyMuPDF
        val_ok, val_details = validate_pdf_document(out_pdf)
        assert val_ok is True
        assert val_details.get("has_verbum_font") is True
        assert val_details.get("text_is_selectable") is True

        # Check extracted text contains key words
        doc = pymupdf.open(out_pdf)
        text = doc[0].get_text()
        assert "Hello" in text
        assert "Verbum" in text
        doc.close()

    def test_multi_page_with_page_break(self, ttf_font_path):
        """Generate a multi-page document using explicit '---' page break separator."""
        temp_dir = tempfile.mkdtemp(prefix="verbum_multipage_pdf_")
        out_pdf = os.path.join(temp_dir, "multipage_doc.pdf")

        content = (
            "Section 1: First Page Notes.\n"
            "This text belongs on the first page.\n\n"
            "---\n\n"
            "Section 2: Second Page Notes.\n"
            "This text belongs on the second page.\n"
            "Numbers: 0123456789. Symbols: . , : - ( ) [ ] { }"
        )

        res = generate_handwritten_pdf(
            content=content,
            title="Multi Page Test",
            font_path=ttf_font_path,
            output_pdf_path=out_pdf,
            generate_preview=False,
        )

        assert res.success is True
        assert res.page_count >= 2

        doc = pymupdf.open(out_pdf)
        assert len(doc) >= 2
        p1_text = doc[0].get_text()
        p2_text = doc[1].get_text()

        assert "First Page" in p1_text
        assert "Second Page" in p2_text
        doc.close()

    def test_preview_image_generation(self, ttf_font_path):
        """Verify that page preview rendering generates a valid PNG image file."""
        temp_dir = tempfile.mkdtemp(prefix="verbum_preview_pdf_")
        out_pdf = os.path.join(temp_dir, "preview_test.pdf")

        res = generate_handwritten_pdf(
            content="Testing preview rasterization with PyMuPDF.",
            title="Preview Test",
            font_path=ttf_font_path,
            output_pdf_path=out_pdf,
            generate_preview=True,
        )

        assert res.preview_image_path is not None
        prev_path = Path(res.preview_image_path)
        assert prev_path.exists()
        assert prev_path.stat().st_size > 1000

    def test_unsupported_characters_tracking(self, ttf_font_path):
        """Verify that unsupported characters are tracked gracefully without crashing."""
        temp_dir = tempfile.mkdtemp(prefix="verbum_unsupported_pdf_")
        out_pdf = os.path.join(temp_dir, "unsupported_test.pdf")

        # '@', '#', '$' are not in the handwriting glyph dataset
        content = "Supported text A B C with special @#$ symbols."
        res = generate_handwritten_pdf(
            content=content,
            title="Unsupported Test",
            font_path=ttf_font_path,
            output_pdf_path=out_pdf,
            generate_preview=False,
        )

        assert res.success is True
        assert len(res.unsupported_chars) > 0
        for ch in ["@", "#", "$"]:
            assert ch in res.unsupported_chars


class TestPDFWorker:
    def test_pdf_worker_multiprocessing(self, ttf_font_path):
        """Verify PDF worker subprocess executes and reports progress/success."""
        temp_dir = tempfile.mkdtemp(prefix="verbum_worker_pdf_")
        out_pdf = os.path.join(temp_dir, "worker_doc.pdf")

        proc, q, cancel = start_pdf_worker(
            content="Multiprocessing PDF worker verification test.",
            title="Worker Verification",
            font_path=ttf_font_path,
            output_pdf_path=out_pdf,
            page_size="letter",
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
        assert Path(data["pdf_path"]).exists()
        assert data["page_count"] >= 1
        assert data["validation_passed"] is True
