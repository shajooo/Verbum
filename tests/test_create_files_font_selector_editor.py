"""Regression tests for Create Files font database selection and direct PDF-to-editor handoff."""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pymupdf
from PySide6.QtWidgets import QApplication, QMessageBox

from app.config import Config, DEFAULTS
from app.font_projects import FontProjectStore
from app.ui.main_window import CreateFilesPage


def _app():
    return QApplication.instance() or QApplication([])


def _validated_font(store: FontProjectStore, project_id: str, source_font: Path, version: int = 1) -> Path:
    output, allocated = store.generation_directory(project_id)
    assert allocated == version
    target = output / "TestGenerated.ttf"
    target.write_bytes(source_font.read_bytes())
    store.record_generation(project_id, {
        "project_id": project_id,
        "version": version,
        "ttf_path": str(target),
        "otf_path": None,
        "specimen_path": None,
        "glyph_count": 12,
        "validation_passed": True,
    })
    return target


def _page():
    _app()
    return CreateFilesPage()


def test_font_database_selector_keeps_project_ids_and_versions_isolated(tmp_path: Path, monkeypatch):
    page = _page()
    store = FontProjectStore(tmp_path / "font_projects")
    project_a = store.create("Duplicate Display Name")
    project_b = store.create("Duplicate Display Name")
    system_font = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "arial.ttf"
    if not system_font.is_file():
        page.close()
        return
    font_a = _validated_font(store, project_a["project_id"], system_font)
    font_b = _validated_font(store, project_b["project_id"], system_font)

    page._font_project_store = store
    page._font_projects = [project_a, project_b]
    page.font_database_combo.addItem(project_a["project_name"], project_a["project_id"])
    page.font_database_combo.addItem(project_b["project_name"], project_b["project_id"])
    page.font_database_combo.setCurrentIndex(1)
    page._populate_font_versions(project_b["project_id"])
    selected = page.font_version_combo.currentData()
    assert selected["project_id"] == project_b["project_id"]
    assert Path(selected["path"]).resolve() == font_b.resolve()
    assert Path(selected["path"]).resolve() != font_a.resolve() or project_a["project_id"] != project_b["project_id"]

    page._populate_font_versions(project_a["project_id"])
    selected_a = page.font_version_combo.currentData()
    assert selected_a["project_id"] == project_a["project_id"]
    assert Path(selected_a["path"]).resolve() == font_a.resolve()
    page.close()


def test_empty_font_database_has_clear_empty_state(tmp_path: Path):
    page = _page()
    store = FontProjectStore(tmp_path / "font_projects")
    project = store.create("No Fonts Yet")
    page._font_project_store = store
    page._font_projects = [project]
    page._populate_font_versions(project["project_id"])
    assert page.font_version_combo.count() == 1
    assert not page.font_version_combo.isEnabled()
    assert "no valid generated fonts" in page.font_preview_label.text().lower()
    page.close()


def test_open_in_editor_imports_exact_current_pdf_without_file_picker(tmp_path: Path, monkeypatch):
    page = _page()
    pdf_path = tmp_path / "current-session.pdf"
    with pymupdf.open() as pdf:
        page_pdf = pdf.new_page(width=500, height=700)
        page_pdf.insert_text((40, 60), "Exact current session")
        pdf.save(pdf_path)

    page.title_input.setText("Current session")
    page.content_input.setPlainText("Generated source content")
    page._pdf_path = str(pdf_path)
    page._pdf_session_id = page._document_session_id
    page._pdf_fingerprint = page._document_fingerprint()
    page._pdf_font_ref = {}
    errors = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: errors.append(args[-1]))
    monkeypatch.setattr(page, "_confirm_discard", lambda: True)

    page.open_current_pdf_in_editor()
    assert not errors, errors
    assert page._document.source_pdf == str(pdf_path.resolve())
    assert page._page_editors[0].toPlainText().strip() == "Exact current session"
    assert page._document.source_pdf == str(pdf_path.resolve())
    page.close()


def test_open_in_editor_does_not_import_stale_pdf_and_requests_regeneration(tmp_path: Path):
    page = _page()
    stale_pdf = tmp_path / "stale.pdf"
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((30, 40), "Old document")
        pdf.save(stale_pdf)

    page.content_input.setPlainText("New document content")
    page._pdf_path = str(stale_pdf)
    page._pdf_session_id = "older-session"
    page._pdf_fingerprint = "older-fingerprint"
    emitted = []
    page.generate_pdf_requested.connect(lambda *args: emitted.append(args))

    page.open_current_pdf_in_editor()
    assert len(emitted) == 1
    assert page._pending_open_in_editor
    assert page._pending_open_session_id == page._document_session_id
    assert page._document.source_pdf is None
    page.close()


def test_cancelled_unsaved_editor_transition_preserves_current_document(tmp_path: Path, monkeypatch):
    page = _page()
    existing_text = "Do not replace unsaved work"
    page.content_input.setPlainText(existing_text)
    pdf_path = tmp_path / "candidate.pdf"
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((30, 40), "Candidate PDF")
        pdf.save(pdf_path)
    page._pdf_path = str(pdf_path)
    page._pdf_session_id = page._document_session_id
    page._pdf_fingerprint = page._document_fingerprint()
    monkeypatch.setattr(page, "_confirm_discard", lambda: False)

    page.open_current_pdf_in_editor()
    assert page.content_input.toPlainText() == existing_text
    assert page._document.source_pdf is None
    assert not page._pending_open_in_editor
    page.close()
