"""Rich HTML document export through Qt's local PDF printer."""
from __future__ import annotations
from pathlib import Path
import os
import uuid
import re
from html import unescape
from .pdf_generator import PDFBuildResult, validate_pdf_document, render_pdf_page_preview, check_unsupported_characters

def generate_rich_pdf(html_pages: list[str], title: str, font_path: str | Path | None,
                      output_pdf_path: str | Path) -> PDFBuildResult:
    """Export rich HTML pages to searchable PDF; optionally privately load a personal TTF."""
    from PySide6.QtCore import QMarginsF
    from PySide6.QtGui import (QFontDatabase, QTextDocument, QTextCursor, QTextBlockFormat,
                               QTextFormat, QTextDocumentFragment, QFont, QPageSize, QPageLayout)
    from PySide6.QtPrintSupport import QPrinter
    from PySide6.QtWidgets import QApplication
    import sys

    if not html_pages:
        return PDFBuildResult(success=False, error_message="The document has no pages.")
    font = Path(font_path).resolve() if font_path else None
    if font is not None and not font.is_file():
        return PDFBuildResult(success=False, error_message=f"Selected font is missing: {font}")
    owned_app = None
    if QApplication.instance() is None:
        owned_app = QApplication([sys.argv[0], "-platform", "offscreen"])
    font_id = -1
    families = ["Arial"]
    runtime_font = font or (Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "arial.ttf")
    if runtime_font.is_file():
        font_id = QFontDatabase.addApplicationFont(str(runtime_font))
        if font_id < 0:
            if font is not None:
                if owned_app is not None: owned_app.quit()
                return PDFBuildResult(success=False, error_message="Qt could not privately load the selected font.")
        else:
            families = QFontDatabase.applicationFontFamilies(font_id)
            if not families:
                QFontDatabase.removeApplicationFont(font_id)
                if owned_app is not None: owned_app.quit()
                return PDFBuildResult(success=False, error_message="Selected font has no usable family name.")
    elif font is not None:
        if owned_app is not None: owned_app.quit()
        return PDFBuildResult(success=False, error_message="Selected font has no usable family name.")

    document = QTextDocument()
    if len(html_pages) == 1:
        document.setHtml(html_pages[0])
    else:
        cursor = QTextCursor(document)
        for index, html in enumerate(html_pages):
            if index:
                block = QTextBlockFormat()
                block.setPageBreakPolicy(QTextFormat.PageBreakFlag.PageBreak_AlwaysBefore)
                cursor.insertBlock(block)
            fragment = QTextDocument()
            fragment.setHtml(html)
            fragment_cursor = QTextCursor(fragment)
            fragment_cursor.select(QTextCursor.SelectionType.Document)
            cursor.insertFragment(QTextDocumentFragment(fragment_cursor))
    document.setDefaultFont(QFont(families[0], 12))
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    output = Path(output_pdf_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f'.{output.stem}.{uuid.uuid4().hex}.tmp.pdf')
    printer.setOutputFileName(str(temporary))
    printer.setPageSize(QPageSize(QPageSize.PageSizeId.Letter))
    printer.setPageMargins(QMarginsF(18.0, 18.0, 18.0, 18.0), QPageLayout.Unit.Millimeter)
    document.setPageSize(printer.pageLayout().paintRect(QPageLayout.Unit.Point).size())
    try:
        document.print_(printer)
    except Exception as exc:
        if font_id >= 0: QFontDatabase.removeApplicationFont(font_id)
        if owned_app is not None: owned_app.quit()
        temporary.unlink(missing_ok=True)
        return PDFBuildResult(success=False, error_message=f"Rich PDF export failed: {exc}")
    if font_id >= 0: QFontDatabase.removeApplicationFont(font_id)
    if owned_app is not None: owned_app.quit()

    ok, details = validate_pdf_document(temporary)
    if not ok:
        temporary.unlink(missing_ok=True)
        return PDFBuildResult(success=False, validation_passed=False, validation_details=details,
                              error_message=f"PDF validation failed: {details.get('error','unknown')}")
    try:
        os.replace(temporary, output)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        return PDFBuildResult(success=False, error_message=f"Could not safely publish the PDF: {exc}")
    ok, details = validate_pdf_document(output)
    if not ok:
        return PDFBuildResult(success=False, pdf_path=str(output), validation_passed=False,
                              validation_details=details, error_message=f"PDF validation failed after publish: {details.get('error','unknown')}")
    details["export_engine"] = "Qt QTextDocument/QPrinter"
    details["rich_html_pages"] = len(html_pages)
    details["has_selected_font"] = bool(font) and any((families[0] in str(f[3]) or "Verbum" in str(f[3])) for f in details.get("fonts", []) if len(f) > 3)
    preview = render_pdf_page_preview(output, 0)
    plain_text = unescape(re.sub(r"<[^>]+>", " ", " ".join(html_pages)))
    unsupported = check_unsupported_characters(title + " " + plain_text, font) if font else []
    return PDFBuildResult(success=True, pdf_path=str(output), page_count=details.get("page_count", 1),
                          preview_image_path=preview, unsupported_chars=unsupported,
                          validation_passed=True, validation_details=details)
