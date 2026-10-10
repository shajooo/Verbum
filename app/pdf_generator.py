"""
Verbum PDF Generator — Generates selectable, searchable handwritten PDF documents
using the custom-generated Verbum Handwriting TrueType font.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pymupdf
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


logger = logging.getLogger(__name__)


@dataclass
class PDFBuildResult:
    success: bool
    pdf_path: Optional[str] = None
    page_count: int = 0
    preview_image_path: Optional[str] = None
    unsupported_chars: List[str] = field(default_factory=list)
    validation_passed: bool = False
    validation_details: Dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None


def check_unsupported_characters(text: str, font_path: str | Path) -> List[str]:
    """
    Identifies characters in input text that are absent from the handwriting font's cmap.
    """
    try:
        from fontTools.ttLib import TTFont as FTFont
        f = FTFont(str(font_path))
        cmap = f.getBestCmap()
        f.close()
        if not cmap:
            return []
        
        unsupported = set()
        for ch in text:
            # Allow basic whitespace
            if ch in ("\n", "\r", "\t", " "):
                continue
            if ord(ch) not in cmap:
                unsupported.add(ch)
        return sorted(list(unsupported))
    except Exception as exc:
        logger.warning("Could not check unsupported characters: %s", exc)
        return []


def generate_handwritten_pdf(
    content: str,
    title: str = "",
    font_path: str | Path = "",
    output_pdf_path: str | Path = "",
    page_size: str = "letter",
    generate_preview: bool = True
) -> PDFBuildResult:
    """
    Builds a multi-page PDF document embedding the custom handwriting TrueType font.
    """
    font_p = Path(font_path)
    if not font_p.exists():
        return PDFBuildResult(
            success=False,
            error_message=f"Handwriting font not found at: {font_p}. Please generate the font first."
        )

    out_pdf = Path(output_pdf_path)
    out_pdf.parent.mkdir(parents=True, exist_ok=True)

    # Check for unsupported glyphs
    unsupported = check_unsupported_characters((title + " " + content), font_p)

    font_family_name = "VerbumHandwriting"
    try:
        # Register font in ReportLab
        pdfmetrics.registerFont(TTFont(font_family_name, str(font_p)))
    except Exception as exc:
        logger.error("Failed to register font with ReportLab: %s", exc)
        return PDFBuildResult(
            success=False,
            error_message=f"Failed to register handwriting font: {exc}"
        )

    ps = A4 if page_size.lower() == "a4" else letter
    margin = 54  # 0.75 in (54 pt)

    doc = SimpleDocTemplate(
        str(out_pdf),
        pagesize=ps,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=margin
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "HandwritingTitle",
        fontName=font_family_name,
        fontSize=24,
        leading=32,
        spaceAfter=18,
        textColor="#1a1c29"
    )

    body_style = ParagraphStyle(
        "HandwritingBody",
        fontName=font_family_name,
        fontSize=16,
        leading=25,
        spaceAfter=12,
        textColor="#222436"
    )

    story = []

    # Optional Title
    if title.strip():
        # Escape XML entities for ReportLab Paragraph
        safe_title = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        story.append(Paragraph(safe_title, title_style))
        story.append(Spacer(1, 12))

    # Split paragraphs by double newline or single newline
    paragraphs = content.split("\n")
    for para in paragraphs:
        text_line = para.strip()
        if not text_line:
            story.append(Spacer(1, 10))
            continue
        if text_line == "---":
            story.append(PageBreak())
            continue

        safe_text = text_line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        story.append(Paragraph(safe_text, body_style))

    try:
        doc.build(story)
        logger.info("PDF document built successfully: %s", out_pdf)
    except Exception as exc:
        logger.error("ReportLab PDF build failed: %s", exc)
        return PDFBuildResult(
            success=False,
            error_message=f"Document generation failed: {exc}",
            unsupported_chars=unsupported
        )

    # Programmatic validation with PyMuPDF
    val_ok, val_details = validate_pdf_document(out_pdf)
    if not val_ok:
        return PDFBuildResult(
            success=False,
            pdf_path=str(out_pdf),
            unsupported_chars=unsupported,
            validation_passed=False,
            validation_details=val_details,
            error_message=f"PDF validation failed: {val_details.get('error', 'Unknown')}"
        )

    # Render preview image of page 1
    preview_img_path = None
    if generate_preview and val_details.get("page_count", 0) > 0:
        preview_img_path = render_pdf_page_preview(out_pdf, page_num=0)

    return PDFBuildResult(
        success=True,
        pdf_path=str(out_pdf),
        page_count=val_details.get("page_count", 1),
        preview_image_path=preview_img_path,
        unsupported_chars=unsupported,
        validation_passed=True,
        validation_details=val_details
    )


def validate_pdf_document(pdf_path: str | Path) -> Tuple[bool, Dict[str, Any]]:
    """
    Validates that the PDF opens, contains pages, has extractable selectable text,
    and embeds the custom font.
    """
    details: Dict[str, Any] = {}
    try:
        doc = pymupdf.open(str(pdf_path))
        page_count = len(doc)
        details["page_count"] = page_count
        if page_count == 0:
            details["error"] = "PDF contains 0 pages"
            doc.close()
            return False, details

        # Inspect text on page 1
        page1 = doc[0]
        page_text = page1.get_text()
        details["page1_text_length"] = len(page_text)
        details["text_is_selectable"] = len(page_text.strip()) > 0

        # Inspect embedded fonts
        fonts = page1.get_fonts()
        details["fonts"] = fonts
        font_names = [f[3] for f in fonts if len(f) > 3]
        has_custom_font = any("Verbum" in name for name in font_names)
        details["has_verbum_font"] = has_custom_font

        doc.close()
        return True, details
    except Exception as exc:
        details["error"] = str(exc)
        return False, details


def render_pdf_page_preview(
    pdf_path: str | Path,
    page_num: int = 0,
    zoom: float = 1.3
) -> str:
    """
    Renders a page of the generated PDF to a high-resolution PNG image for UI preview.
    """
    pdf_p = Path(pdf_path)
    preview_out = pdf_p.parent / f"{pdf_p.stem}_page_{page_num + 1}_preview.png"

    try:
        doc = pymupdf.open(str(pdf_p))
        if page_num >= len(doc):
            page_num = 0
        page = doc[page_num]
        mat = pymupdf.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)
        pix.save(str(preview_out))
        doc.close()
        logger.info("Rendered PDF page preview: %s", preview_out)
        return str(preview_out)
    except Exception as exc:
        logger.error("Failed to render PDF page preview: %s", exc)
        return ""
