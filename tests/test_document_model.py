from pathlib import Path
import pytest
from app.document_model import EditableDocument, DocumentPage, save_document, load_document

def test_document_round_trip_preserves_pages_rich_html_and_font_reference(tmp_path):
    path = tmp_path / "notes.vdoc"
    document = EditableDocument(
        title="Notes",
        pages=[DocumentPage("<html><body><p><b>Hello</b></p></body></html>"),
               DocumentPage("<html><body><p>Page two</p></body></html>")],
        font_ref={"project_id": "casual_12345678", "version": 2, "family": "Casual"},
        source_pdf="source.pdf",
    )
    save_document(path, document)
    restored = load_document(path)
    assert restored.title == "Notes"
    assert len(restored.pages) == 2
    assert "<b>Hello</b>" in restored.pages[0].html
    assert "Page two" in restored.pages[1].html
    assert restored.font_ref["project_id"] == "casual_12345678"
    assert restored.font_ref["version"] == 2
    assert restored.source_pdf == "source.pdf"

def test_save_atomically_replaces_previous_valid_document(tmp_path):
    path = tmp_path / "notes.vdoc"
    save_document(path, EditableDocument(title="Old"))
    save_document(path, EditableDocument(title="New"))
    assert load_document(path).title == "New"
    assert not list(tmp_path.glob(".notes.vdoc.*.tmp"))

def test_load_rejects_unknown_schema(tmp_path):
    path = tmp_path / "bad.vdoc"
    path.write_text('{"schema_version":99,"pages":[]}', encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported"):
        load_document(path)

def test_load_rejects_malformed_json(tmp_path):
    path = tmp_path / "bad.vdoc"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(Exception):
        load_document(path)
