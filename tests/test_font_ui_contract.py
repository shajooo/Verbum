"""Regression coverage for the controller/Create Font presentation contract."""
from __future__ import annotations

import copy
import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.config import Config, DEFAULTS
from app.font_projects import FontProjectStore
from app.main import VoiceInputApp
from app.ui.main_window import MainWindow


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_refresh_font_projects_has_matching_main_window_generation_api(tmp_path: Path) -> None:
    """Startup refresh must publish project generation metadata without AttributeError."""
    _application()
    config = Config(**copy.deepcopy(DEFAULTS))
    store = FontProjectStore(tmp_path / "font_projects")
    project = store.create("Startup Contract")
    config.active_font_project_id = project["project_id"]

    output_dir, version = store.generation_directory(project["project_id"])
    ttf = output_dir / "Startup_Contract.ttf"
    ttf.write_bytes(b"font-test-artifact")
    store.record_generation(project["project_id"], {
        "project_id": project["project_id"],
        "version": version,
        "ttf_path": str(ttf),
        "otf_path": None,
        "specimen_path": None,
        "glyph_count": 0,
        "validation_passed": True,
    })

    window = MainWindow(config)
    controller = SimpleNamespace(font_projects=store, config=config, main_window=window)
    VoiceInputApp._refresh_font_projects(controller)

    assert hasattr(window, "set_font_project_generation")
    assert window.font_page._ttf_path == str(ttf)
    assert window.font_page.dataset_summary.text().startswith("Dataset: 0 glyph samples")
    assert window.font_page.font_ready_badge.text() == "v001 Ready"
    window._switch_page(window._PAGE_FONT)
    assert window._stack.currentWidget() is window.font_page
    window.close()


def test_font_intake_progress_indicator_is_visible_only_while_running() -> None:
    _application()
    config = Config(**copy.deepcopy(DEFAULTS))
    window = MainWindow(config)
    page = window.font_page

    page.show_intake_progress("Analyzing sample…")
    assert not page.intake_progress.isHidden()

    page.show_intake_result({
        "sample_id": "sample-1",
        "file_name": "test1.jpeg",
        "sample_type": "HANDWRITTEN_NOTE",
        "confidence": 0.76,
        "message": "Handwritten note detected.",
        "candidates": [],
    })
    assert page.intake_progress.isHidden()
    assert "no usable glyphs were extracted" in page.intake_status.text()
    window.close()


def test_font_intake_progress_indicator_hides_on_error() -> None:
    _application()
    config = Config(**copy.deepcopy(DEFAULTS))
    window = MainWindow(config)
    page = window.font_page

    page.show_intake_progress("Analyzing sample…")
    assert not page.intake_progress.isHidden()
    page.show_intake_error("Sample analysis failed.")
    assert page.intake_progress.isHidden()
    assert "Sample analysis failed." in page.intake_status.text()
    window.close()
