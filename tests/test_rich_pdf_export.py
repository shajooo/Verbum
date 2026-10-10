from pathlib import Path
import os
import pymupdf
import pytest
from app.rich_pdf_export import generate_rich_pdf
from app.pdf_worker import start_pdf_worker

@pytest.fixture
def font_path():
    path = Path(__file__).resolve().parents[1] / "fonts" / "Verbum_Handwriting.ttf"
    assert path.is_file()
    return path

def test_rich_export_keeps_text_tables_formatting_and_pages(tmp_path, font_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    output = tmp_path / "rich.pdf"
    pages = [
        '<html><body><h1>Document title</h1><p><b>Bold searchable text</b></p>'
        '<ul><li>One item</li><li>Two items</li></ul><table border="1"><tr><td>Cell A</td><td>Cell B</td></tr></table></body></html>',
        '<html><body><p>Page two content</p></body></html>',
    ]
    result = generate_rich_pdf(pages, "Rich document", font_path, output)
    assert result.success, result.error_message
    assert result.validation_passed
    assert result.page_count == 2
    assert result.validation_details["text_is_selectable"]
    assert result.validation_details["has_verbum_font"]
    with pymupdf.open(output) as pdf:
        text = "\n".join(page.get_text() for page in pdf)
        assert "Bold searchable text" in text
        assert "Cell A" in text and "Cell B" in text
        assert "Page two content" in text

def test_rich_export_can_use_standard_fonts_without_personal_font(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    output = tmp_path / "standard.pdf"
    result = generate_rich_pdf(["<html><body><p>Standard font text</p></body></html>"], "Standard", None, output)
    assert result.success, result.error_message
    with pymupdf.open(output) as pdf:
        assert "Standard font text" in pdf[0].get_text()

def test_rich_export_missing_selected_font_does_not_overwrite_existing_pdf(tmp_path):
    output = tmp_path / "existing.pdf"
    output.write_bytes(b"keep-existing")
    result = generate_rich_pdf(["<p>text</p>"], "Test", tmp_path / "missing.ttf", output)
    assert not result.success
    assert output.read_bytes() == b"keep-existing"

def test_rich_export_preserves_inserted_image(tmp_path, font_path, monkeypatch):
    from PIL import Image
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    image_path = tmp_path / "image.png"
    Image.new("RGB", (120, 80), (180, 30, 60)).save(image_path)
    output = tmp_path / "image_doc.pdf"
    html = f'<html><body><p>Before image</p><p><img src="{image_path.as_posix()}" width="120" height="80"/></p><p>After image</p></body></html>'
    result = generate_rich_pdf([html], "Image document", font_path, output)
    assert result.success, result.error_message
    with pymupdf.open(output) as pdf:
        assert "Before image" in pdf[0].get_text()
        assert "After image" in pdf[0].get_text()
        assert pdf[0].get_images()
    assert image_path.exists()

def test_rich_export_runs_in_existing_pdf_worker(tmp_path, font_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    output = tmp_path / "worker_rich.pdf"
    process, results, cancel = start_pdf_worker(
        content="ignored plain text", title="Worker rich", font_path=str(font_path),
        output_pdf_path=str(output), html_pages=["<html><body><p>Worker searchable text</p></body></html>"],
    )
    process.join(timeout=30)
    if process.is_alive():
        cancel.set()
        process.terminate()
        process.join(timeout=2)
        pytest.fail("Rich PDF worker did not finish.")
    messages = []
    while not results.empty():
        messages.append(results.get_nowait())
    success = [m for m in messages if m[0] == "success"]
    errors = [m for m in messages if m[0] == "error"]
    assert success, errors
    assert output.is_file()
    with pymupdf.open(output) as pdf:
        assert "Worker searchable text" in pdf[0].get_text()
