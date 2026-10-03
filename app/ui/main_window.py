"""
main_window.py — Voice Input main window.

Pages (via sidebar):
  Capture       — voice transcription only
  Extract text  — OCR / document extraction only
  History       — unified history view
  Create Font   — UI skeleton for future handwriting/font generation
  Create Files  — UI skeleton for future file generation
  Settings      — opens the settings window (signal)
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup, QFileDialog, QFrame, QHBoxLayout, QLabel, QMainWindow,
    QPushButton, QScrollArea, QSizePolicy, QStackedWidget, QToolButton,
    QVBoxLayout, QWidget,
)

from ..config import Config
from .icons import icon
from .recording_overlay import RecordingVisualization

# ─── Sidebar widths ──────────────────────────────────────────────────────────
SIDEBAR_EXPANDED = 192
SIDEBAR_COLLAPSED = 54


# ─── Helper: drop-zone ───────────────────────────────────────────────────────

class ImageDropZone(QLabel):
    image_selected = Signal(str)
    _accepted_exts = {".png", ".jpg", ".jpeg", ".webp", ".bmp",
                      ".svg", ".tif", ".tiff", ".gif", ".pdf", ".docx",
                      ".ico", ".avif"}

    def __init__(self) -> None:
        super().__init__("Drop an image, PDF, SVG, or DOCX here\nor choose one from your device")
        self.setObjectName("imageDropZone")
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(164)
        self.setWordWrap(True)

    def show_file(self, path: str) -> None:
        raster = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif", ".ico", ".avif"}
        if path and Path(path).suffix.lower() in raster:
            px = QPixmap(path)
            if not px.isNull():
                self.setPixmap(px.scaled(330, 164, Qt.AspectRatioMode.KeepAspectRatio,
                                         Qt.TransformationMode.SmoothTransformation))
                self.setToolTip(path)
                return
        self.setPixmap(QPixmap())
        if path:
            self.setText(f"Selected: {Path(path).name}\nReady for local text extraction")
            self.setToolTip(path)
        else:
            self.setText("Drop an image, PDF, SVG, or DOCX here\nor choose one from your device")
            self.setToolTip("")

    def dragEnterEvent(self, event) -> None:
        urls = event.mimeData().urls()
        if len(urls) == 1 and Path(urls[0].toLocalFile()).suffix.lower() in self._accepted_exts:
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        self.image_selected.emit(event.mimeData().urls()[0].toLocalFile())
        event.acceptProposedAction()


# ─── History row helper ───────────────────────────────────────────────────────

class HistoryRow(QFrame):
    copy_clicked = Signal(str)

    def __init__(self, text: str, meta: str, icon_name: str = "mic") -> None:
        super().__init__()
        self.setObjectName("historyRow")
        self._text = text
        layout = QHBoxLayout(self)
        layout.setContentsMargins(13, 10, 12, 10)
        layout.setSpacing(12)

        img = QLabel()
        img.setPixmap(icon(icon_name, "#9b8fff", 20).pixmap(20, 20))
        layout.addWidget(img)

        details = QVBoxLayout()
        details.setSpacing(2)
        output = QLabel(text.replace("\n", " "))
        output.setObjectName("historyText")
        output.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        output.setWordWrap(True)
        meta_lbl = QLabel(meta)
        meta_lbl.setObjectName("historyMeta")
        details.addWidget(output)
        details.addWidget(meta_lbl)
        layout.addLayout(details, 1)

        self._copy_btn = QPushButton("Copy")
        self._copy_btn.setObjectName("copyButton")
        self._copy_btn.setIcon(icon("copy", "#b9b4e8", 15))
        self._copy_btn.setFixedWidth(68)
        self._copy_btn.clicked.connect(self._on_copy)
        layout.addWidget(self._copy_btn)

    def _on_copy(self) -> None:
        self.copy_clicked.emit(self._text)
        # Animate: show checkmark briefly
        self._copy_btn.setText("Copied")
        self._copy_btn.setIcon(icon("check", "#60ddb0", 15))
        self._copy_btn.setObjectName("copyButtonDone")
        self._copy_btn.setStyle(self._copy_btn.style())  # force style refresh
        QTimer.singleShot(1400, self._reset_copy_btn)

    def _reset_copy_btn(self) -> None:
        self._copy_btn.setText("Copy")
        self._copy_btn.setIcon(icon("copy", "#b9b4e8", 15))
        self._copy_btn.setObjectName("copyButton")
        self._copy_btn.setStyle(self._copy_btn.style())


# ─── Toggle widget ────────────────────────────────────────────────────────────

class FeatureToggle(QFrame):
    """Compact ON/OFF toggle for a named feature."""
    toggled = Signal(bool)

    def __init__(self, label: str, enabled: bool = True) -> None:
        super().__init__()
        self.setObjectName("featureToggleBar")
        self._enabled = enabled
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self._lbl = QLabel(label)
        self._lbl.setObjectName("sectionSubtitle")
        self._status = QLabel("ON" if enabled else "OFF")
        self._status.setObjectName("hotkeyBadge")
        self._btn = QPushButton("Disable" if enabled else "Enable")
        self._btn.setObjectName("quietButton")
        self._btn.clicked.connect(self._toggle)
        layout.addWidget(self._lbl)
        layout.addWidget(self._status)
        layout.addWidget(self._btn)
        layout.addStretch()
        self._refresh()

    def _toggle(self) -> None:
        self._enabled = not self._enabled
        self._refresh()
        self.toggled.emit(self._enabled)

    def _refresh(self) -> None:
        self._status.setText("ON" if self._enabled else "OFF")
        if self._enabled:
            self._status.setStyleSheet("color: #60ddb0; border-color: #60ddb0;")
        else:
            self._status.setStyleSheet("color: #989bb0; border-color: #292d40;")
        self._btn.setText("Disable" if self._enabled else "Enable")

    def set_enabled(self, val: bool) -> None:
        self._enabled = val
        self._refresh()

    @property
    def is_enabled(self) -> bool:
        return self._enabled


# ─── Page: Capture ───────────────────────────────────────────────────────────

class CapturePage(QWidget):
    cancel_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("pageWidget")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        # ── Voice card ───────────────────────────────────────────────────────
        card = QFrame()
        card.setObjectName("surfaceCard")
        card.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(24, 21, 24, 22)
        card_layout.setSpacing(18)

        heading = self._make_heading()
        card_layout.addLayout(heading)

        content = QHBoxLayout()
        content.setSpacing(22)

        # Visual column
        visual_col = QVBoxLayout()
        visual_col.setSpacing(5)
        self.voice_visual = RecordingVisualization(338, 108)
        self.voice_visual.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        visual_col.addWidget(self.voice_visual, 0, Qt.AlignmentFlag.AlignHCenter)
        self.status_title = QLabel("Ready")
        self.status_title.setObjectName("captureState")
        self.status_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_detail = QLabel("Press Ctrl + Space and start speaking.")
        self.status_detail.setObjectName("captureDetail")
        self.status_detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_detail.setWordWrap(True)
        visual_col.addWidget(self.status_title)
        visual_col.addWidget(self.status_detail)
        content.addLayout(visual_col, 1)

        # Session panel
        session = QFrame()
        session.setObjectName("sessionPanel")
        session.setMinimumWidth(260)
        session_layout = QVBoxLayout(session)
        session_layout.setContentsMargins(18, 17, 18, 17)
        session_layout.setSpacing(9)
        session_label = QLabel("Session")
        session_label.setObjectName("sessionLabel")
        self.session_state = QLabel("Listening is ready")
        self.session_state.setObjectName("sessionState")
        self.session_state.setWordWrap(True)
        session_hint = QLabel("Voice Input transcribes locally, then follows your copy or paste setting.")
        session_hint.setObjectName("sessionHint")
        session_hint.setWordWrap(True)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setObjectName("stopButton")
        self.stop_button.setIcon(icon("stop", "#f3f1ff", 16))
        self.stop_button.setVisible(False)
        self.stop_button.clicked.connect(self.cancel_requested)
        session_layout.addWidget(session_label)
        session_layout.addWidget(self.session_state)
        session_layout.addWidget(session_hint)
        session_layout.addStretch()
        session_layout.addWidget(self.stop_button, 0, Qt.AlignmentFlag.AlignLeft)
        content.addWidget(session)
        card_layout.addLayout(content)
        layout.addWidget(card)

        # ── Voice history card ───────────────────────────────────────────────
        self.history_card = QFrame()
        self.history_card.setObjectName("surfaceCard")
        self.history_card.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        hist_layout = QVBoxLayout(self.history_card)
        hist_layout.setContentsMargins(24, 21, 24, 20)
        hist_layout.setSpacing(14)

        hist_head = QHBoxLayout()
        hist_icon = QLabel()
        hist_icon.setPixmap(icon("history", "#9084ff", 23).pixmap(23, 23))
        hist_text = QVBoxLayout()
        hist_text.setSpacing(2)
        ht = QLabel("Voice history")
        ht.setObjectName("sectionTitle")
        hs = QLabel("Your five most recent local transcriptions")
        hs.setObjectName("sectionSubtitle")
        hist_text.addWidget(ht)
        hist_text.addWidget(hs)
        hist_head.addWidget(hist_icon, 0, Qt.AlignmentFlag.AlignTop)
        hist_head.addLayout(hist_text)
        hist_head.addStretch()
        self.clear_history_btn = QPushButton("Clear history")
        self.clear_history_btn.setObjectName("quietButton")
        hist_head.addWidget(self.clear_history_btn)
        hist_layout.addLayout(hist_head)
        self.history_rows = QVBoxLayout()
        self.history_rows.setSpacing(8)
        hist_layout.addLayout(self.history_rows)
        layout.addWidget(self.history_card)

        layout.addStretch()

    def _make_heading(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        img = QLabel()
        img.setPixmap(icon("mic", "#9084ff", 23).pixmap(23, 23))
        text = QVBoxLayout()
        text.setSpacing(2)
        h = QLabel("Voice transcription")
        h.setObjectName("sectionTitle")
        s = QLabel("Press Ctrl + Space to start or stop recording")
        s.setObjectName("sectionSubtitle")
        text.addWidget(h)
        text.addWidget(s)
        layout.addWidget(img, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(text)
        layout.addStretch()
        hotkey = QLabel("  Ctrl + Space  ")
        hotkey.setObjectName("hotkeyBadge")
        layout.addWidget(hotkey)
        return layout

    def update_status(self, state: str, detail: str = "") -> None:
        labels = {
            "IDLE":        ("Ready",       "Listening is ready",                      "#d8d6ff"),
            "RECORDING":   ("Listening",   "Recording from your selected microphone", "#9d91ff"),
            "TRANSCRIBING":("Transcribing","Processing the recording locally",        "#c8bfff"),
            "SUCCESS":     ("Complete",    "Your output is ready",                    "#60ddb0"),
            "ERROR":       ("Attention",   "Voice Input needs your attention",        "#f1a6b5"),
        }
        title, session, color = labels.get(state, (state.title(), state.title(), "#e9e8f4"))
        self.status_title.setText(title)
        self.status_title.setStyleSheet(f"color: {color};")
        self.status_detail.setText(detail or "Press Ctrl + Space and start speaking.")
        self.session_state.setText(session)
        self.stop_button.setVisible(state in {"RECORDING", "TRANSCRIBING"})
        if state == "RECORDING":
            self.voice_visual.begin()
        elif state == "TRANSCRIBING":
            self.voice_visual.settle()
        else:
            self.voice_visual.stop()

    def update_audio_level(self, rms: float) -> None:
        self.voice_visual.set_audio_level(rms)

    def populate_history(self, entries: list[str], copy_cb) -> None:
        while self.history_rows.count():
            item = self.history_rows.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not entries:
            empty = QLabel("No completed transcriptions yet. Your latest output will appear here.")
            empty.setObjectName("emptyHistory")
            self.history_rows.addWidget(empty)
            return
        for text in entries:
            row = HistoryRow(text, "Voice transcription", "mic")
            row.copy_clicked.connect(copy_cb)
            self.history_rows.addWidget(row)


# ─── Page: Extract text ───────────────────────────────────────────────────────

class ExtractPage(QWidget):
    extraction_requested = Signal(str)
    extraction_cancel_requested = Signal()
    extraction_toggled = Signal(bool)
    file_path_changed = Signal(str)  # emitted when file selection changes (for config persistence)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("pageWidget")
        self._current_path = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        # ── Extraction card ──────────────────────────────────────────────────
        card = QFrame()
        card.setObjectName("surfaceCard")
        card.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(24, 21, 24, 20)
        card_layout.setSpacing(16)

        # Heading
        head = QHBoxLayout()
        himg = QLabel()
        himg.setPixmap(icon("image", "#9084ff", 23).pixmap(23, 23))
        htxt = QVBoxLayout()
        htxt.setSpacing(2)
        ht = QLabel("Text extraction")
        ht.setObjectName("sectionTitle")
        hs = QLabel("Extract printed text locally from images, PDFs, SVGs, and Word documents")
        hs.setObjectName("sectionSubtitle")
        htxt.addWidget(ht)
        htxt.addWidget(hs)
        head.addWidget(himg, 0, Qt.AlignmentFlag.AlignTop)
        head.addLayout(htxt)
        head.addStretch()
        fmt = QLabel("PNG · JPG · PDF · DOCX · SVG · TIFF")
        fmt.setObjectName("formatBadge")
        head.addWidget(fmt)
        card_layout.addLayout(head)

        # Toggle
        self.toggle = FeatureToggle("Printed Text Extraction:", enabled=True)
        self.toggle.toggled.connect(self.extraction_toggled)
        card_layout.addWidget(self.toggle)

        # Drop zone + actions split
        split = QHBoxLayout()
        split.setSpacing(16)
        self.drop_zone = ImageDropZone()
        self.drop_zone.image_selected.connect(self._on_file_selected)
        split.addWidget(self.drop_zone, 1)

        actions_frame = QFrame()
        actions_frame.setObjectName("imageActions")
        actions_frame.setMinimumWidth(190)
        actions_layout = QVBoxLayout(actions_frame)
        actions_layout.setContentsMargins(16, 15, 16, 15)
        actions_layout.setSpacing(8)
        self.file_name = QLabel("No file selected")
        self.file_name.setObjectName("imageName")
        self.file_name.setWordWrap(True)
        self.file_meta = QLabel("Select a file, then extract text locally.")
        self.file_meta.setObjectName("imageMeta")
        self.file_meta.setWordWrap(True)
        self.extract_status = QLabel("Ready for a local extraction job.")
        self.extract_status.setObjectName("imageMeta")
        self.extract_status.setWordWrap(True)
        browse_btn = QPushButton("Browse files")
        browse_btn.setObjectName("quietButton")
        browse_btn.clicked.connect(self.browse_file)
        self.extract_btn = QPushButton("Extract text")
        self.extract_btn.setObjectName("primaryButton")
        self.extract_btn.setEnabled(False)
        self.extract_btn.clicked.connect(self._on_extract)
        self.stop_btn = QPushButton("Stop extraction")
        self.stop_btn.setObjectName("quietButton")
        self.stop_btn.clicked.connect(self.extraction_cancel_requested)
        self.stop_btn.hide()
        clear_btn = QPushButton("Clear selection")
        clear_btn.setObjectName("quietButton")
        clear_btn.clicked.connect(self.clear_file)
        actions_layout.addWidget(self.file_name)
        actions_layout.addWidget(self.file_meta)
        actions_layout.addWidget(self.extract_status)
        actions_layout.addStretch()
        actions_layout.addWidget(browse_btn)
        actions_layout.addWidget(self.extract_btn)
        actions_layout.addWidget(self.stop_btn)
        actions_layout.addWidget(clear_btn)
        split.addWidget(actions_frame)
        card_layout.addLayout(split)
        layout.addWidget(card)

        # ── Extraction history card ──────────────────────────────────────────
        self.history_card = QFrame()
        self.history_card.setObjectName("surfaceCard")
        self.history_card.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        hist_layout = QVBoxLayout(self.history_card)
        hist_layout.setContentsMargins(24, 21, 24, 20)
        hist_layout.setSpacing(14)

        hist_head = QHBoxLayout()
        hi_img = QLabel()
        hi_img.setPixmap(icon("history", "#9084ff", 23).pixmap(23, 23))
        hi_txt = QVBoxLayout()
        hi_txt.setSpacing(2)
        hi_t = QLabel("Extraction history")
        hi_t.setObjectName("sectionTitle")
        hi_s = QLabel("Your five most recent extraction results")
        hi_s.setObjectName("sectionSubtitle")
        hi_txt.addWidget(hi_t)
        hi_txt.addWidget(hi_s)
        hist_head.addWidget(hi_img, 0, Qt.AlignmentFlag.AlignTop)
        hist_head.addLayout(hi_txt)
        hist_head.addStretch()
        self.clear_history_btn = QPushButton("Clear history")
        self.clear_history_btn.setObjectName("quietButton")
        hist_head.addWidget(self.clear_history_btn)
        hist_layout.addLayout(hist_head)
        self.history_rows = QVBoxLayout()
        self.history_rows.setSpacing(8)
        hist_layout.addLayout(self.history_rows)
        layout.addWidget(self.history_card)

        layout.addStretch()

    def _on_file_selected(self, path: str) -> None:
        self._current_path = path
        self._refresh_file_ui()
        self.file_path_changed.emit(path)

    def _on_extract(self) -> None:
        if self._current_path:
            self.extraction_requested.emit(self._current_path)

    def browse_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose a file to extract", self._current_path,
            "Supported files (*.png *.jpg *.jpeg *.webp *.bmp *.svg *.tif *.tiff "
            "*.gif *.ico *.avif *.pdf *.docx);;All files (*.*)",
        )
        if path:
            self._on_file_selected(path)

    def clear_file(self) -> None:
        self._current_path = ""
        self._refresh_file_ui()
        self.file_path_changed.emit("")

    def set_path(self, path: str) -> None:
        self._current_path = path
        self._refresh_file_ui()

    def _refresh_file_ui(self) -> None:
        path = self._current_path
        self.drop_zone.show_file(path)
        enabled = self.toggle.is_enabled
        if not enabled:
            self.file_name.setText("Text extraction is disabled.")
            self.file_meta.setText("Enable Printed Text Extraction to extract text.")
        elif path:
            p = Path(path)
            self.file_name.setText(p.name)
            try:
                size_mb = p.stat().st_size / (1024 * 1024)
                meta_parts = [f"{p.suffix.upper().lstrip('.')} • {size_mb:.1f} MB"]
                if p.suffix.lower() == ".pdf":
                    try:
                        import pymupdf
                        with pymupdf.open(str(p)) as doc:
                            meta_parts.append(f"{len(doc)} pages")
                    except Exception:
                        pass
                self.file_meta.setText(" • ".join(meta_parts))
            except Exception:
                self.file_meta.setText("File details unavailable")
        else:
            self.file_name.setText("No file selected")
            self.file_meta.setText("Select a file, then extract text locally.")
        self.extract_btn.setEnabled(enabled and bool(path))

    def update_toggle(self, enabled: bool) -> None:
        self.toggle.set_enabled(enabled)
        self._refresh_file_ui()

    def update_extraction_status(self, state: str, detail: str = "") -> None:
        extracting = state == "EXTRACTING"
        can_extract = not extracting and self.toggle.is_enabled and bool(self._current_path)
        self.extract_btn.setEnabled(can_extract)
        self.stop_btn.setVisible(extracting)
        if detail:
            self.extract_status.setText(detail)
        elif extracting:
            self.extract_status.setText("Extracting locally…")
        elif state == "SUCCESS":
            self.extract_status.setText("Extraction complete. Text copied/saved.")
        elif state == "ERROR":
            self.extract_status.setText("Extraction failed. See the message above.")
        elif state in ("CANCELLED", "IDLE"):
            self.extract_status.setText("Ready for a local extraction job.")
        else:
            self.extract_status.setText("Ready for a local extraction job.")

    def populate_history(self, entries: list[str], copy_cb) -> None:
        while self.history_rows.count():
            item = self.history_rows.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not entries:
            empty = QLabel("No extractions yet. Your latest result will appear here.")
            empty.setObjectName("emptyHistory")
            self.history_rows.addWidget(empty)
            return
        for entry in entries:
            # Strip "label: " prefix for display
            display, raw = entry, entry
            if ": " in entry:
                parts = entry.split(": ", 1)
                label_part = parts[0]
                display = parts[1]
                raw = display
                icon_name = "image"
            else:
                label_part = "Extracted"
                icon_name = "image"
            row = HistoryRow(display, label_part, icon_name)
            row.copy_clicked.connect(copy_cb)
            self.history_rows.addWidget(row)


# ─── Page: History (unified) ──────────────────────────────────────────────────

class HistoryPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("pageWidget")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        card = QFrame()
        card.setObjectName("surfaceCard")
        card.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(24, 21, 24, 20)
        card_layout.setSpacing(14)

        head = QHBoxLayout()
        hi = QLabel()
        hi.setPixmap(icon("history", "#9084ff", 23).pixmap(23, 23))
        ht_col = QVBoxLayout()
        ht_col.setSpacing(2)
        ht = QLabel("All history")
        ht.setObjectName("sectionTitle")
        hs = QLabel("Unified view of voice, extraction, font and file history")
        hs.setObjectName("sectionSubtitle")
        ht_col.addWidget(ht)
        ht_col.addWidget(hs)
        head.addWidget(hi, 0, Qt.AlignmentFlag.AlignTop)
        head.addLayout(ht_col)
        head.addStretch()
        self.clear_all_btn = QPushButton("Clear all")
        self.clear_all_btn.setObjectName("quietButton")
        head.addWidget(self.clear_all_btn)
        card_layout.addLayout(head)

        self.rows_layout = QVBoxLayout()
        self.rows_layout.setSpacing(8)
        card_layout.addLayout(self.rows_layout)
        layout.addWidget(card)
        layout.addStretch()

    def populate(self, voice: list[str], extraction: list[str],
                 font: list[str], files: list[str], copy_cb) -> None:
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        all_entries: list[tuple[str, str, str]] = []
        for t in voice:
            all_entries.append((t, "Voice transcription", "mic"))
        for e in extraction:
            label, text = ("Extraction", e)
            if ": " in e:
                parts = e.split(": ", 1)
                label, text = parts[0], parts[1]
            all_entries.append((text, label, "image"))
        for f in font:
            all_entries.append((f, "Create Font", "font"))
        for fl in files:
            all_entries.append((fl, "Create Files", "files"))

        if not all_entries:
            empty = QLabel("No history yet. Your completed outputs will appear here.")
            empty.setObjectName("emptyHistory")
            self.rows_layout.addWidget(empty)
            return
        for text, meta, icon_name in all_entries:
            row = HistoryRow(text, meta, icon_name)
            row.copy_clicked.connect(copy_cb)
            self.rows_layout.addWidget(row)


# ─── Page: Create Font ────────────────────────────────────────────────────────

class CreateFontPage(QWidget):
    toggled = Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("pageWidget")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        # Main card
        card = QFrame()
        card.setObjectName("surfaceCard")
        card.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(24, 21, 24, 22)
        cl.setSpacing(18)

        # Heading
        head = QHBoxLayout()
        hi = QLabel()
        hi.setPixmap(icon("font", "#9084ff", 23).pixmap(23, 23))
        ht_col = QVBoxLayout()
        ht_col.setSpacing(2)
        ht = QLabel("Create Font")
        ht.setObjectName("sectionTitle")
        hs = QLabel("Create a personalized font from your handwriting samples")
        hs.setObjectName("sectionSubtitle")
        ht_col.addWidget(ht)
        ht_col.addWidget(hs)
        head.addWidget(hi, 0, Qt.AlignmentFlag.AlignTop)
        head.addLayout(ht_col)
        head.addStretch()
        cl.addLayout(head)

        # Toggle
        self.feature_toggle = FeatureToggle("Create Font:", enabled=False)
        self.feature_toggle.toggled.connect(self.toggled)
        cl.addWidget(self.feature_toggle)

        # Disabled overlay notice
        self.disabled_notice = QLabel(
            "Enable Create Font to upload handwriting samples and generate a personalized font.\n"
            "When enabled, the font generation engine will be available but not yet active."
        )
        self.disabled_notice.setObjectName("disabledNotice")
        self.disabled_notice.setWordWrap(True)
        cl.addWidget(self.disabled_notice)

        # Upload area
        upload_area = QFrame()
        upload_area.setObjectName("skeletonPanel")
        ul = QVBoxLayout(upload_area)
        ul.setContentsMargins(18, 16, 18, 16)
        ul.setSpacing(10)
        ul_title = QLabel("Upload handwriting samples")
        ul_title.setObjectName("panelLabel")
        ul_sub = QLabel("Supported samples: uppercase letters, lowercase letters, numbers, punctuation, short sentences")
        ul_sub.setObjectName("sectionSubtitle")
        ul_sub.setWordWrap(True)
        self.upload_btn = QPushButton("Choose files")
        self.upload_btn.setObjectName("quietButton")
        self.upload_btn.setIcon(icon("upload", "#b9b4e8", 16))
        self.upload_btn.setEnabled(False)
        ul.addWidget(ul_title)
        ul.addWidget(ul_sub)
        ul.addWidget(self.upload_btn, 0, Qt.AlignmentFlag.AlignLeft)
        cl.addWidget(upload_area)

        # Preview area
        preview_area = QFrame()
        preview_area.setObjectName("skeletonPanel")
        pl = QVBoxLayout(preview_area)
        pl.setContentsMargins(18, 16, 18, 16)
        pl.setSpacing(8)
        pl_title = QLabel("Font preview")
        pl_title.setObjectName("panelLabel")
        self.preview_label = QLabel("Your generated font will appear here.")
        self.preview_label.setObjectName("skeletonPlaceholder")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumHeight(64)
        pl.addWidget(pl_title)
        pl.addWidget(self.preview_label)
        cl.addWidget(preview_area)

        # Download
        self.download_btn = QPushButton("Download font")
        self.download_btn.setObjectName("primaryButton")
        self.download_btn.setIcon(icon("download", "#f3f1ff", 16))
        self.download_btn.setEnabled(False)
        self.download_btn.setToolTip("Font generation backend is not yet implemented.")
        cl.addWidget(self.download_btn, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(card)

        # History card
        self.history_card = QFrame()
        self.history_card.setObjectName("surfaceCard")
        self.history_card.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        hl = QVBoxLayout(self.history_card)
        hl.setContentsMargins(24, 21, 24, 20)
        hl.setSpacing(14)
        h_head = QHBoxLayout()
        h_hi = QLabel()
        h_hi.setPixmap(icon("history", "#9084ff", 23).pixmap(23, 23))
        h_txt = QVBoxLayout()
        h_txt.setSpacing(2)
        h_t = QLabel("Font history")
        h_t.setObjectName("sectionTitle")
        h_s = QLabel("Your generated fonts will appear here")
        h_s.setObjectName("sectionSubtitle")
        h_txt.addWidget(h_t)
        h_txt.addWidget(h_s)
        h_head.addWidget(h_hi, 0, Qt.AlignmentFlag.AlignTop)
        h_head.addLayout(h_txt)
        h_head.addStretch()
        self.clear_history_btn = QPushButton("Clear history")
        self.clear_history_btn.setObjectName("quietButton")
        h_head.addWidget(self.clear_history_btn)
        hl.addLayout(h_head)
        self.history_rows = QVBoxLayout()
        self.history_rows.setSpacing(8)
        hl.addLayout(self.history_rows)
        layout.addWidget(self.history_card)

        layout.addStretch()
        self._refresh_enabled(False)

    def _refresh_enabled(self, enabled: bool) -> None:
        self.disabled_notice.setVisible(not enabled)
        self.upload_btn.setEnabled(enabled)

    def update_toggle(self, enabled: bool) -> None:
        self.feature_toggle.set_enabled(enabled)
        self._refresh_enabled(enabled)

    def populate_history(self, entries: list[str], copy_cb) -> None:
        while self.history_rows.count():
            item = self.history_rows.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not entries:
            empty = QLabel("No font generations yet. This is a future feature.")
            empty.setObjectName("emptyHistory")
            self.history_rows.addWidget(empty)
            return
        for text in entries:
            row = HistoryRow(text, "Create Font", "font")
            row.copy_clicked.connect(copy_cb)
            self.history_rows.addWidget(row)


# ─── Page: Create Files ───────────────────────────────────────────────────────

class CreateFilesPage(QWidget):
    toggled = Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("pageWidget")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        card = QFrame()
        card.setObjectName("surfaceCard")
        card.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(24, 21, 24, 22)
        cl.setSpacing(18)

        # Heading
        head = QHBoxLayout()
        hi = QLabel()
        hi.setPixmap(icon("files", "#9084ff", 23).pixmap(23, 23))
        ht_col = QVBoxLayout()
        ht_col.setSpacing(2)
        ht = QLabel("Create Files")
        ht.setObjectName("sectionTitle")
        hs = QLabel("Create files from extracted or generated content")
        hs.setObjectName("sectionSubtitle")
        ht_col.addWidget(ht)
        ht_col.addWidget(hs)
        head.addWidget(hi, 0, Qt.AlignmentFlag.AlignTop)
        head.addLayout(ht_col)
        head.addStretch()
        cl.addLayout(head)

        # Toggle
        self.feature_toggle = FeatureToggle("Create Files:", enabled=False)
        self.feature_toggle.toggled.connect(self.toggled)
        cl.addWidget(self.feature_toggle)

        # Disabled notice
        self.disabled_notice = QLabel(
            "Enable Create Files to generate output files from your transcribed or extracted content.\n"
            "The file generation backend will be implemented in a future release."
        )
        self.disabled_notice.setObjectName("disabledNotice")
        self.disabled_notice.setWordWrap(True)
        cl.addWidget(self.disabled_notice)

        # Source panel
        source_panel = QFrame()
        source_panel.setObjectName("skeletonPanel")
        sl = QVBoxLayout(source_panel)
        sl.setContentsMargins(18, 16, 18, 16)
        sl.setSpacing(8)
        sp_title = QLabel("Choose source")
        sp_title.setObjectName("panelLabel")
        self.source_label = QLabel("Content will appear here once available.")
        self.source_label.setObjectName("skeletonPlaceholder")
        self.source_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.source_label.setMinimumHeight(52)
        sl.addWidget(sp_title)
        sl.addWidget(self.source_label)
        cl.addWidget(source_panel)

        # File type row
        ft_row = QHBoxLayout()
        ft_lbl = QLabel("File type:")
        ft_lbl.setObjectName("sectionSubtitle")
        self.file_type_label = QLabel("TXT")
        self.file_type_label.setObjectName("hotkeyBadge")
        ft_row.addWidget(ft_lbl)
        ft_row.addWidget(self.file_type_label)
        ft_row.addStretch()
        cl.addLayout(ft_row)

        # Preview panel
        prev_panel = QFrame()
        prev_panel.setObjectName("skeletonPanel")
        pvl = QVBoxLayout(prev_panel)
        pvl.setContentsMargins(18, 16, 18, 16)
        pvl.setSpacing(8)
        pv_title = QLabel("Output preview")
        pv_title.setObjectName("panelLabel")
        self.preview_label = QLabel("Generated file preview will appear here.")
        self.preview_label.setObjectName("skeletonPlaceholder")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumHeight(64)
        pvl.addWidget(pv_title)
        pvl.addWidget(self.preview_label)
        cl.addWidget(prev_panel)

        # Download
        self.download_btn = QPushButton("Download file")
        self.download_btn.setObjectName("primaryButton")
        self.download_btn.setIcon(icon("download", "#f3f1ff", 16))
        self.download_btn.setEnabled(False)
        self.download_btn.setToolTip("File generation backend is not yet implemented.")
        cl.addWidget(self.download_btn, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(card)

        # History card
        self.history_card = QFrame()
        self.history_card.setObjectName("surfaceCard")
        self.history_card.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        hl = QVBoxLayout(self.history_card)
        hl.setContentsMargins(24, 21, 24, 20)
        hl.setSpacing(14)
        h_head = QHBoxLayout()
        h_hi = QLabel()
        h_hi.setPixmap(icon("history", "#9084ff", 23).pixmap(23, 23))
        h_txt = QVBoxLayout()
        h_txt.setSpacing(2)
        h_t = QLabel("Files history")
        h_t.setObjectName("sectionTitle")
        h_s = QLabel("Your generated files will appear here")
        h_s.setObjectName("sectionSubtitle")
        h_txt.addWidget(h_t)
        h_txt.addWidget(h_s)
        h_head.addWidget(h_hi, 0, Qt.AlignmentFlag.AlignTop)
        h_head.addLayout(h_txt)
        h_head.addStretch()
        self.clear_history_btn = QPushButton("Clear history")
        self.clear_history_btn.setObjectName("quietButton")
        h_head.addWidget(self.clear_history_btn)
        hl.addLayout(h_head)
        self.history_rows = QVBoxLayout()
        self.history_rows.setSpacing(8)
        hl.addLayout(self.history_rows)
        layout.addWidget(self.history_card)

        layout.addStretch()
        self._refresh_enabled(False)

    def _refresh_enabled(self, enabled: bool) -> None:
        self.disabled_notice.setVisible(not enabled)

    def update_toggle(self, enabled: bool) -> None:
        self.feature_toggle.set_enabled(enabled)
        self._refresh_enabled(enabled)

    def populate_history(self, entries: list[str], copy_cb) -> None:
        while self.history_rows.count():
            item = self.history_rows.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not entries:
            empty = QLabel("No file generations yet. This is a future feature.")
            empty.setObjectName("emptyHistory")
            self.history_rows.addWidget(empty)
            return
        for text in entries:
            row = HistoryRow(text, "Create Files", "files")
            row.copy_clicked.connect(copy_cb)
            self.history_rows.addWidget(row)


# ─── Main Window ──────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    """Visible control centre; closing it leaves the tray service running."""

    open_settings = Signal()
    hidden_to_tray = Signal()
    cancel_requested = Signal()
    copy_requested = Signal(str)
    extraction_requested = Signal(str)
    extraction_cancel_requested = Signal()
    extraction_toggled = Signal(bool)
    font_toggled = Signal(bool)
    files_toggled = Signal(bool)
    voice_history_cleared = Signal()
    extraction_history_cleared = Signal()
    font_history_cleared = Signal()
    files_history_cleared = Signal()
    all_history_cleared = Signal()

    _PAGE_CAPTURE = 0
    _PAGE_EXTRACT = 1
    _PAGE_HISTORY = 2
    _PAGE_FONT = 3
    _PAGE_FILES = 4

    def __init__(self, config: Config) -> None:
        super().__init__()
        self.config = config
        self._sidebar: QFrame | None = None
        self._collapse_btn: QToolButton | None = None
        self._nav_group: QButtonGroup | None = None
        self._nav_buttons: list[QToolButton] = []
        self._privacy_widget: QWidget | None = None
        self.setWindowTitle("Voice Input")
        self.setMinimumSize(920, 690)
        self.resize(1120, 800)

        root = QWidget()
        root.setObjectName("appRoot")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(18, 16, 18, 18)
        root_layout.setSpacing(14)
        root_layout.addLayout(self._make_header())

        body = QHBoxLayout()
        body.setSpacing(0)

        # Sidebar
        self._sidebar = self._make_sidebar()
        body.addWidget(self._sidebar)
        self._apply_sidebar_state(self.config.sidebar_collapsed)

        # Page stack
        self._stack = QStackedWidget()
        self._stack.setObjectName("pageStack")

        # Create pages
        self.capture_page = CapturePage()
        self.extract_page = ExtractPage()
        self.history_page = HistoryPage()
        self.font_page = CreateFontPage()
        self.files_page = CreateFilesPage()

        self._stack.addWidget(self.capture_page)   # 0
        self._stack.addWidget(self.extract_page)   # 1
        self._stack.addWidget(self.history_page)   # 2
        self._stack.addWidget(self.font_page)      # 3
        self._stack.addWidget(self.files_page)     # 4

        # Wrap stack in scroll
        scroll = QScrollArea()
        scroll.setObjectName("workspaceScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll_inner = QWidget()
        scroll_inner.setObjectName("workspace")
        scroll_inner.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        si_layout = QVBoxLayout(scroll_inner)
        si_layout.setContentsMargins(16, 0, 2, 0)
        si_layout.setSpacing(0)
        si_layout.addWidget(self._stack)
        si_layout.addWidget(self._make_footer())
        si_layout.addStretch()
        scroll.setWidget(scroll_inner)
        body.addWidget(scroll, 1)
        root_layout.addLayout(body, 1)
        self.setCentralWidget(root)

        # Wire signals
        self.capture_page.cancel_requested.connect(self.cancel_requested)
        self.capture_page.clear_history_btn.clicked.connect(self._clear_voice_history)
        self.extract_page.extraction_requested.connect(self.extraction_requested)
        self.extract_page.extraction_cancel_requested.connect(self.extraction_cancel_requested)
        self.extract_page.extraction_toggled.connect(self._on_extraction_toggled)
        self.extract_page.file_path_changed.connect(self._on_extract_path_changed)
        self.extract_page.clear_history_btn.clicked.connect(self._clear_extraction_history)
        self.font_page.toggled.connect(self._on_font_toggled)
        self.font_page.clear_history_btn.clicked.connect(self._clear_font_history)
        self.files_page.toggled.connect(self._on_files_toggled)
        self.files_page.clear_history_btn.clicked.connect(self._clear_files_history)
        self.history_page.clear_all_btn.clicked.connect(self._clear_all_history)

        self._apply_theme()
        self.refresh_config()
        self._switch_page(self._PAGE_CAPTURE)

    # ── Header ────────────────────────────────────────────────────────────────

    def _make_header(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setContentsMargins(4, 0, 4, 0)
        brand_icon = QLabel()
        brand_icon.setPixmap(icon("mic", "#9589ff", 26).pixmap(26, 26))
        brand = QLabel("Voice Input")
        brand.setObjectName("brand")
        version = QLabel("Local voice workspace")
        version.setObjectName("version")
        brand_stack = QVBoxLayout()
        brand_stack.setSpacing(0)
        brand_stack.addWidget(brand)
        brand_stack.addWidget(version)
        layout.addWidget(brand_icon)
        layout.addLayout(brand_stack)
        layout.addStretch()
        self.offline_badge = QLabel("  Local · Offline  ")
        self.offline_badge.setObjectName("offlineBadge")
        layout.addWidget(self.offline_badge)
        return layout

    # ── Sidebar ───────────────────────────────────────────────────────────────

    def _make_sidebar(self) -> QFrame:
        self._sidebar = QFrame()
        self._sidebar.setObjectName("sidebar")
        collapsed = getattr(self.config, "sidebar_collapsed", False)
        self._sidebar.setFixedWidth(SIDEBAR_COLLAPSED if collapsed else SIDEBAR_EXPANDED)

        layout = QVBoxLayout(self._sidebar)
        layout.setContentsMargins(6, 10, 6, 12)
        layout.setSpacing(4)

        # Toggle button (collapse/expand)
        self._collapse_btn = QToolButton()
        self._collapse_btn.setObjectName("collapseButton")
        self._collapse_btn.setIcon(icon("chevron_left" if not collapsed else "chevron_right", "#9b9eb3", 18))
        self._collapse_btn.setIconSize(QSize(18, 18))
        self._collapse_btn.setFixedSize(30, 30)
        self._collapse_btn.setToolTip("Collapse sidebar" if not collapsed else "Expand sidebar")
        self._collapse_btn.clicked.connect(self._toggle_sidebar)
        col_row = QHBoxLayout()
        col_row.setContentsMargins(0, 0, 0, 6)
        col_row.addStretch()
        col_row.addWidget(self._collapse_btn)
        layout.addLayout(col_row)

        # Nav buttons
        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)

        self.nav_capture = self._nav_button("Capture", "capture")
        self.nav_extract = self._nav_button("Extract text", "image")
        self.nav_history = self._nav_button("History", "history")
        self.nav_font = self._nav_button("Create Font", "font")
        self.nav_files = self._nav_button("Create Files", "files")
        self.nav_settings = self._nav_button("Settings", "settings")

        self._nav_buttons = [
            self.nav_capture, self.nav_extract, self.nav_history,
            self.nav_font, self.nav_files,
        ]
        self.nav_capture.setChecked(True)

        for btn in self._nav_buttons:
            layout.addWidget(btn)

        # Settings at bottom
        layout.addStretch()

        # Privacy notice (only shown when expanded)
        self._privacy_widget = QWidget()
        priv_layout = QHBoxLayout(self._privacy_widget)
        priv_layout.setContentsMargins(4, 0, 4, 0)
        priv_layout.setSpacing(7)
        privacy_icon = QLabel()
        privacy_icon.setPixmap(icon("shield", "#52dca5", 18).pixmap(18, 18))
        privacy_title = QLabel("Local processing")
        privacy_title.setObjectName("privacyTitle")
        privacy_copy = QLabel("No data leaves your device.")
        privacy_copy.setObjectName("privacyCopy")
        privacy_copy.setWordWrap(True)
        privacy_text = QVBoxLayout()
        privacy_text.setSpacing(1)
        privacy_text.addWidget(privacy_title)
        privacy_text.addWidget(privacy_copy)
        priv_layout.addWidget(privacy_icon, 0, Qt.AlignmentFlag.AlignTop)
        priv_layout.addLayout(privacy_text, 1)
        layout.addWidget(self._privacy_widget)

        # Settings button last
        layout.addWidget(self.nav_settings)

        self.nav_capture.clicked.connect(lambda: self._switch_page(self._PAGE_CAPTURE))
        self.nav_extract.clicked.connect(lambda: self._switch_page(self._PAGE_EXTRACT))
        self.nav_history.clicked.connect(lambda: self._switch_page(self._PAGE_HISTORY))
        self.nav_font.clicked.connect(lambda: self._switch_page(self._PAGE_FONT))
        self.nav_files.clicked.connect(lambda: self._switch_page(self._PAGE_FILES))
        self.nav_settings.clicked.connect(self._on_settings_clicked)

        return self._sidebar

    def _nav_button(self, label: str, icon_name: str) -> QToolButton:
        button = QToolButton()
        button.setObjectName("navButton")
        button.setText(label)
        button.setIcon(icon(icon_name))
        button.setIconSize(QSize(20, 20))
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        button.setCheckable(True)
        button.setAutoExclusive(True)
        button.setMinimumHeight(40)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._nav_group.addButton(button)
        return button

    def _toggle_sidebar(self) -> None:
        if getattr(self, "_sidebar", None) is None:
            return
        collapsed = self._sidebar.width() > SIDEBAR_COLLAPSED
        self.config.sidebar_collapsed = collapsed
        self.config.save()
        self._apply_sidebar_state(collapsed)

    def _set_sidebar_collapsed(self) -> None:
        if getattr(self, "_sidebar", None) is None:
            return
        self.config.sidebar_collapsed = True
        self.config.save()
        self._apply_sidebar_state(True)

    def _set_sidebar_expanded(self) -> None:
        if getattr(self, "_sidebar", None) is None:
            return
        self.config.sidebar_collapsed = False
        self.config.save()
        self._apply_sidebar_state(False)

    def _apply_sidebar_state(self, collapsed: bool) -> None:
        if getattr(self, "_sidebar", None) is None or getattr(self, "_collapse_btn", None) is None:
            return
        if collapsed:
            self._sidebar.setFixedWidth(SIDEBAR_COLLAPSED)
            self._collapse_btn.setIcon(icon("chevron_right", "#9b9eb3", 18))
            self._collapse_btn.setToolTip("Expand sidebar")
            for btn in self._nav_buttons + [self.nav_settings]:
                btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
                btn.setToolTip(btn.text())
            if getattr(self, "_privacy_widget", None) is not None:
                self._privacy_widget.hide()
        else:
            self._sidebar.setFixedWidth(SIDEBAR_EXPANDED)
            self._collapse_btn.setIcon(icon("chevron_left", "#9b9eb3", 18))
            self._collapse_btn.setToolTip("Collapse sidebar")
            for btn in self._nav_buttons + [self.nav_settings]:
                btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
                btn.setToolTip("")
            if getattr(self, "_privacy_widget", None) is not None:
                self._privacy_widget.show()

    def _switch_page(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        if index == self._PAGE_HISTORY:
            self._populate_history_page()
        elif index == self._PAGE_CAPTURE:
            self.capture_page.populate_history(
                self.config.voice_history, self.copy_requested.emit)
        elif index == self._PAGE_EXTRACT:
            self.extract_page.populate_history(
                self.config.extraction_history, self.copy_requested.emit)
        elif index == self._PAGE_FONT:
            self.font_page.populate_history(
                self.config.font_history, self.copy_requested.emit)
        elif index == self._PAGE_FILES:
            self.files_page.populate_history(
                self.config.files_history, self.copy_requested.emit)

    def _on_settings_clicked(self) -> None:
        # Uncheck nav buttons; settings is separate window
        for btn in self._nav_buttons:
            if btn.isChecked():
                btn.setChecked(False)
        self.open_settings.emit()

    # ── Footer ────────────────────────────────────────────────────────────────

    def _make_footer(self) -> QFrame:
        footer = QFrame()
        footer.setObjectName("configFooter")
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(16, 10, 16, 10)
        label = QLabel("Local configuration")
        label.setObjectName("footerLabel")
        self.config_summary = QLabel()
        self.config_summary.setObjectName("configSummary")
        layout.addWidget(label)
        layout.addStretch()
        layout.addWidget(self.config_summary)
        return footer

    # ── History management ────────────────────────────────────────────────────

    def _clear_voice_history(self) -> None:
        self.config.voice_history = []
        self.config.recent_transcriptions = []
        self.config.save()
        self.capture_page.populate_history([], self.copy_requested.emit)
        self.voice_history_cleared.emit()

    def _clear_extraction_history(self) -> None:
        self.config.extraction_history = []
        self.config.save()
        self.extract_page.populate_history([], self.copy_requested.emit)
        self.extraction_history_cleared.emit()

    def _clear_font_history(self) -> None:
        self.config.font_history = []
        self.config.save()
        self.font_page.populate_history([], self.copy_requested.emit)
        self.font_history_cleared.emit()

    def _clear_files_history(self) -> None:
        self.config.files_history = []
        self.config.save()
        self.files_page.populate_history([], self.copy_requested.emit)
        self.files_history_cleared.emit()

    def _clear_all_history(self) -> None:
        self.config.voice_history = []
        self.config.recent_transcriptions = []
        self.config.extraction_history = []
        self.config.font_history = []
        self.config.files_history = []
        self.config.save()
        self._populate_history_page()
        self.all_history_cleared.emit()

    def _populate_history_page(self) -> None:
        self.history_page.populate(
            self.config.voice_history,
            self.config.extraction_history,
            self.config.font_history,
            self.config.files_history,
            self.copy_requested.emit,
        )

    # ── Toggle handlers ───────────────────────────────────────────────────────

    def _on_extraction_toggled(self, enabled: bool) -> None:
        self.config.enable_extraction = enabled
        self.config.save()
        self.extraction_toggled.emit(enabled)
        self.extract_page._refresh_file_ui()

    def _on_font_toggled(self, enabled: bool) -> None:
        self.config.enable_font = enabled
        self.config.save()
        self.font_page._refresh_enabled(enabled)
        self.font_toggled.emit(enabled)

    def _on_files_toggled(self, enabled: bool) -> None:
        self.config.enable_files = enabled
        self.config.save()
        self.files_page._refresh_enabled(enabled)
        self.files_toggled.emit(enabled)

    def _on_extract_path_changed(self, path: str) -> None:
        self.config.image_path = path
        self.config.save()

    # ── Public update API ─────────────────────────────────────────────────────

    def update_status(self, state: str, detail: str = "") -> None:
        self.capture_page.update_status(state, detail)

    def update_audio_level(self, rms: float) -> None:
        self.capture_page.update_audio_level(rms)

    def update_extraction_status(self, state: str, detail: str = "") -> None:
        self.extract_page.update_extraction_status(state, detail)

    def refresh_config(self) -> None:
        self.config_summary.setText(
            f"Model: {self.config.model}   ·   Device: {self.config.device}   ·   Language: {self.config.language}"
        )
        # Update per-page toggles from config
        self.extract_page.update_toggle(self.config.enable_extraction)
        self.font_page.update_toggle(self.config.enable_font)
        self.files_page.update_toggle(self.config.enable_files)
        # Restore extract path
        if self.config.image_path:
            self.extract_page.set_path(self.config.image_path)
        # Refresh current page data
        idx = self._stack.currentIndex()
        self._switch_page(idx)

    # ── Forwarded compat signals for app/main.py ──────────────────────────────

    def set_image(self, path: str) -> None:
        """Called externally to update the active extraction file."""
        self.config.image_path = path
        self.config.save()
        self.extract_page.set_path(path)

    def clear_image(self) -> None:
        self.config.image_path = ""
        self.config.save()
        self.extract_page.clear_file()

    # ── Window lifecycle ──────────────────────────────────────────────────────

    def show_and_raise(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def hide_to_tray(self) -> None:
        self.hide()
        self.hidden_to_tray.emit()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.hide_to_tray()
        event.ignore()

    # ── Theme ─────────────────────────────────────────────────────────────────

    def _apply_theme(self) -> None:
        self.setStyleSheet("""
            QWidget#appRoot { background: #0b0d14; color: #f2f1f8; font-family: "Segoe UI"; }
            QLabel#brand { font-size: 19px; font-weight: 700; color: #faf9ff; }
            QLabel#version, QLabel#sectionSubtitle, QLabel#captureDetail,
            QLabel#sessionHint, QLabel#imageMeta, QLabel#historyMeta,
            QLabel#privacyCopy, QLabel#configSummary { color: #989bb0; font-size: 12px; }
            QLabel#offlineBadge, QLabel#hotkeyBadge, QLabel#formatBadge {
                background: #151824; border: 1px solid #292d40; border-radius: 12px;
                color: #c9c7da; font-size: 12px; padding: 6px 9px; }
            QFrame#sidebar {
                background: #10121b; border: 1px solid #202332; border-radius: 14px;
                margin-right: 14px; }
            QToolButton#navButton {
                background: transparent; border: 1px solid transparent;
                border-radius: 9px; color: #bbbdd0; font-size: 13px;
                font-weight: 600; padding: 8px 9px; text-align: left; }
            QToolButton#navButton:hover { background: #171a28; color: #f0effa; }
            QToolButton#navButton:checked { background: #211f3f; border-color: #393568; color: #c7c0ff; }
            QToolButton#collapseButton {
                background: transparent; border: 1px solid #232737;
                border-radius: 7px; color: #888aaa; }
            QToolButton#collapseButton:hover { background: #171a28; border-color: #393568; }
            QLabel#privacyTitle { color: #d8f7e9; font-size: 12px; font-weight: 700; }
            QScrollArea#workspaceScroll { background: transparent; }
            QScrollBar:vertical { background: transparent; width: 8px; margin: 4px; }
            QScrollBar::handle:vertical { background: #303347; min-height: 30px; border-radius: 4px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QFrame#surfaceCard {
                background: #11141d; border: 1px solid #232737; border-radius: 14px; }
            QLabel#sectionTitle { color: #f3f2f8; font-size: 17px; font-weight: 700; }
            QLabel#captureState { color: #d8d6ff; font-size: 17px; font-weight: 700; }
            QFrame#sessionPanel, QFrame#imageActions {
                background: #0d0f17; border: 1px solid #242838; border-radius: 11px; }
            QLabel#sessionLabel { color: #aaa6d8; font-size: 12px; font-weight: 700; }
            QLabel#sessionState { color: #f2f0fb; font-size: 14px; font-weight: 700; }
            QLabel#imageName { color: #f1eff9; font-size: 13px; font-weight: 700; }
            QLabel#imageDropZone {
                background: #0d0f17; border: 1px dashed #464962;
                border-radius: 11px; color: #9b9eb3; font-size: 13px; }
            QLabel#imageDropZone:hover { border-color: #8276f5; color: #cdc9ff; }
            QPushButton {
                background: #222637; border: 1px solid #32364a; border-radius: 8px;
                color: #e8e7f1; font-size: 12px; font-weight: 600; padding: 8px 12px; }
            QPushButton:hover { background: #2a2e43; border-color: #4c5070; }
            QPushButton:focus, QToolButton:focus { border: 1px solid #887cff; }
            QPushButton#primaryButton { background: #5d52ca; border-color: #7669ec; color: white; }
            QPushButton#primaryButton:hover { background: #6c60df; }
            QPushButton#primaryButton:disabled { background: #2a2840; border-color: #3a3660; color: #7a78a0; }
            QPushButton#quietButton { background: transparent; color: #b9b6cf; }
            QPushButton#quietButton:hover { background: #1c1f2d; color: #efedfa; }
            QPushButton#stopButton { background: #2d2945; border-color: #544d7d; color: #f3f1ff; }
            QFrame#historyRow { background: #0e1018; border: 1px solid #222638; border-radius: 10px; }
            QLabel#historyText { color: #e7e6ef; font-size: 13px; font-weight: 600; }
            QLabel#emptyHistory { color: #8d90a6; font-size: 13px; padding: 8px 0; }
            QPushButton#copyButton {
                background: transparent; border-color: #292d3d;
                color: #c0bdd5; padding: 6px 9px; }
            QPushButton#copyButton:hover { background: #1c1f2d; color: #efedfa; }
            QPushButton#copyButtonDone {
                background: transparent; border-color: #2a4a3a;
                color: #60ddb0; padding: 6px 9px; }
            QFrame#configFooter {
                background: #0f1119; border: 1px solid #202434; border-radius: 10px;
                margin-top: 10px; }
            QLabel#footerLabel { color: #c9c7d9; font-size: 12px; font-weight: 700; }
            QFrame#skeletonPanel {
                background: #0d0f17; border: 1px solid #242838; border-radius: 11px; }
            QLabel#panelLabel { color: #aaa6d8; font-size: 12px; font-weight: 700; }
            QLabel#skeletonPlaceholder { color: #5a5d78; font-size: 13px; font-style: italic; }
            QLabel#disabledNotice {
                color: #7a7d98; font-size: 12px; background: #111420;
                border: 1px solid #252940; border-radius: 8px; padding: 10px 14px; }
        """)
