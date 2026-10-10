"""Regression tests for generated-font testing and compact workspace pages."""
from __future__ import annotations

import copy
import os
import shutil
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QScrollArea, QWidget

from app.config import Config, DEFAULTS
from app.font_projects import FontProjectStore
from app.main import VoiceInputApp
from app.ui.main_window import CreateFontPage, MainWindow


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def _font_data(version: int = 1) -> dict:
    root = Path(__file__).resolve().parent.parent
    return {
        "version": version,
        "ttf_path": str(root / "fonts" / "Verbum_Handwriting.ttf"),
        "otf_path": None,
        "specimen_path": None,
        "validation_passed": True,
    }


def _window() -> MainWindow:
    config = Config(**copy.deepcopy(DEFAULTS))
    # MainWindow initialization emits preference signals; tests must not mutate
    # the developer configuration file as a side effect.
    config.save = lambda: None
    return MainWindow(config)


def test_test_handwriting_uses_a_separate_registered_generated_font() -> None:
    app = _application()
    page = CreateFontPage()
    data = _font_data()
    page.set_project_generation(data, [data])
    page.test_input.setText("jo")
    app.processEvents()

    assert page.test_input.text() == "jo"
    assert page.test_preview.text() == "jo"
    assert not page.test_preview.isHidden()
    assert page._test_font_id >= 0
    assert page.test_input.font().family() == "Segoe UI"
    assert page.test_preview.font().family() != page.test_input.font().family()

    registered_id = page._test_font_id
    page.test_input.setText("jo jo")
    app.processEvents()
    assert page._test_font_id == registered_id
    assert page.test_preview.text() == "jo jo"
    page._clear_test_font()
    assert page._test_font_id == -1


def test_invalid_generated_font_is_visible_error_not_ui_font_fallback(tmp_path: Path) -> None:
    _application()
    page = CreateFontPage()
    page.set_project_generation({
        "version": 1, "ttf_path": str(tmp_path / "missing.ttf"),
        "validation_passed": True,
    }, [])

    assert page._test_font_id == -1
    assert page.test_preview.isHidden()
    assert "unavailable or invalid" in page.test_preview_status.text()


def test_changing_the_selected_generated_version_requests_a_preview_refresh() -> None:
    _application()
    page = CreateFontPage()
    version_one, version_two = _font_data(1), _font_data(2)
    selected: list[int] = []
    page.generation_selected.connect(selected.append)
    page.set_project_generation(version_two, [version_two, version_one])

    assert not page.generation_combo.isHidden()
    page.generation_combo.setCurrentIndex(page.generation_combo.findData(1))
    assert selected == [1]


def test_controller_selects_only_the_active_projects_requested_version(tmp_path: Path) -> None:
    app = _application()
    store = FontProjectStore(tmp_path / "font_projects")
    project = store.create("Version Selection")
    records = []
    for version in (1, 2):
        output, allocated = store.generation_directory(project["project_id"])
        ttf = output / f"version_{version}.ttf"
        shutil.copy2(_font_data()["ttf_path"], ttf)
        record = {"project_id": project["project_id"], "version": allocated,
                  "ttf_path": str(ttf), "otf_path": None, "specimen_path": None,
                  "glyph_count": 70, "validation_passed": True}
        store.record_generation(project["project_id"], record)
        records.append(record)

    config = Config(**copy.deepcopy(DEFAULTS))
    config.active_font_project_id = project["project_id"]
    config.save = lambda: None
    window = MainWindow(config)
    controller = type("Controller", (), {
        "font_projects": store, "config": config, "main_window": window,
    })()
    VoiceInputApp._refresh_font_projects(controller)
    VoiceInputApp.select_font_generation(controller, 1)
    app.processEvents()

    assert window.font_page._ttf_path == records[0]["ttf_path"]
    assert window.font_page.test_preview.font().family() != window.font_page.test_input.font().family()
    window.close()


def test_workspace_uses_current_page_height_not_tallest_hidden_page() -> None:
    app = _application()
    window = _window()
    window.resize(1120, 800)
    window.show()
    app.processEvents()

    scroll = window.findChild(QScrollArea, "workspaceScroll")
    assert scroll is not None
    assert window.capture_page.height() < 500
    assert scroll.verticalScrollBar().maximum() == 0
    footer = window.findChild(QWidget, "configFooter")
    assert footer is not None
    assert footer.y() <= window._stack.height() + 2

    for page_index, page in (
        (window._PAGE_EXTRACT, window.extract_page),
        (window._PAGE_HISTORY, window.history_page),
        (window._PAGE_TRANSLATE, window.translate_page),
    ):
        window._switch_page(page_index)
        app.processEvents()
        assert window._stack.height() < 800
        assert page.height() < 800
        assert scroll.verticalScrollBar().maximum() == 0
        assert footer.y() <= window._stack.height() + 2

    window._switch_page(window._PAGE_FILES)
    app.processEvents()
    assert scroll.height() <= scroll.viewport().height() + scroll.verticalScrollBar().sizeHint().height() + 8
    assert scroll.verticalScrollBar().maximum() > 0
    window.close()
