from __future__ import annotations

import sounddevice as sd
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout,
    QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from ..autostart import set_enabled as set_autostart_enabled
from ..config import Config


class SettingsWindow(QWidget):
    saved = Signal()

    def __init__(self, config: Config, status: str) -> None:
        super().__init__()
        self.config = config
        self.setObjectName("settingsRoot")
        self.setWindowTitle("Voice Input Settings")
        self.setMinimumWidth(520)
        self.resize(570, 640)

        self.model = QComboBox()
        self.model.addItems(["tiny", "base", "small", "medium"])
        self.model.setCurrentText(config.model)

        self.device = QComboBox()
        self.device.addItems(["auto", "cpu", "cuda"])
        self.device.setCurrentText(config.device)

        self.language = QComboBox()
        self.language.addItems(["auto", "en"])
        self.language.setCurrentText(config.language)

        self.microphone = QComboBox()
        self.microphone.addItem("default")
        try:
            for device in sd.query_devices():
                if device["max_input_channels"] > 0:
                    self.microphone.addItem(device["name"])
        except Exception:
            pass
        self.microphone.setCurrentText(config.microphone)

        self.copy = QCheckBox("Copy each completed transcript to the clipboard")
        self.copy.setChecked(config.auto_copy)
        self.paste = QCheckBox("Paste the transcript into the active app")
        self.paste.setChecked(getattr(config, "auto_paste", False))
        self.start_with_windows = QCheckBox("Start Voice Input when I sign in")
        self.start_with_windows.setChecked(config.start_with_windows)

        # Feature toggles
        self.enable_extraction = QCheckBox("Enable Printed Text Extraction (OCR)")
        self.enable_extraction.setChecked(config.enable_extraction)
        self.enable_font = QCheckBox("Enable Create Font feature")
        self.enable_font.setChecked(getattr(config, "enable_font", False))
        self.enable_files = QCheckBox("Enable Create Files feature")
        self.enable_files.setChecked(getattr(config, "enable_files", False))
        self.sidebar_collapsed = QCheckBox("Start with sidebar collapsed")
        self.sidebar_collapsed.setChecked(getattr(config, "sidebar_collapsed", False))

        # Legacy image path kept for compatibility
        self.image_path = config.image_path
        self.image_label = QLabel(self._image_label_text())
        self.image_label.setObjectName("settingsPath")
        self.image_label.setWordWrap(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 23, 24, 22)
        root.setSpacing(16)
        heading = QLabel("Settings")
        heading.setObjectName("settingsTitle")
        subheading = QLabel("Configure local capture and output behavior.")
        subheading.setObjectName("settingsSubtitle")
        root.addWidget(heading)
        root.addWidget(subheading)

        card = QFrame()
        card.setObjectName("settingsCard")
        form = QFormLayout(card)
        form.setContentsMargins(20, 18, 20, 18)
        form.setSpacing(13)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.addRow("Hotkey", QLabel("Ctrl + Space (fixed)"))
        form.addRow("Microphone", self.microphone)
        form.addRow("Whisper model", self.model)
        form.addRow("Device", self.device)
        form.addRow("Language", self.language)
        form.addRow("Output", self.copy)
        form.addRow("", self.paste)
        form.addRow("Startup", self.start_with_windows)
        choose_image = QPushButton("Choose image")
        choose_image.setObjectName("settingsButton")
        choose_image.clicked.connect(self._choose_image)
        image_row = QHBoxLayout()
        image_row.addWidget(choose_image)
        image_row.addWidget(self.image_label, 1)
        form.addRow("Reference image", image_row)
        form.addRow("Extraction", self.enable_extraction)
        form.addRow("Create Font", self.enable_font)
        form.addRow("Create Files", self.enable_files)
        form.addRow("Sidebar", self.sidebar_collapsed)
        form.addRow("Current status", QLabel(status))
        root.addWidget(card)
        root.addStretch()

        actions = QHBoxLayout()
        actions.addStretch()
        cancel = QPushButton("Cancel")
        cancel.setObjectName("settingsButton")
        cancel.clicked.connect(self.close)
        save = QPushButton("Save changes")
        save.setObjectName("settingsSave")
        save.clicked.connect(self.save)
        actions.addWidget(cancel)
        actions.addWidget(save)
        root.addLayout(actions)

        self.setStyleSheet("""
            QWidget#settingsRoot { background: #0d0f17; color: #efedf8; font-family: "Segoe UI"; }
            QLabel#settingsTitle { font-size: 21px; font-weight: 700; color: #fbfaff; }
            QLabel#settingsSubtitle, QLabel#settingsPath { color: #9a9caf; font-size: 12px; }
            QFrame#settingsCard { background: #12151f; border: 1px solid #262a3a; border-radius: 13px; }
            QFrame#settingsCard QLabel { color: #d5d3df; font-size: 12px; }
            QComboBox { background: #0d0f17; border: 1px solid #34384b; border-radius: 7px;
                        color: #edeaf8; min-height: 26px; padding: 2px 8px; }
            QComboBox:hover { border-color: #7469df; }
            QCheckBox { color: #ceccda; font-size: 12px; spacing: 8px; }
            QCheckBox::indicator { width: 15px; height: 15px; border: 1px solid #555970;
                                   border-radius: 4px; background: #0d0f17; }
            QCheckBox::indicator:checked { background: #6559d8; border-color: #8b80f4; }
            QPushButton { border-radius: 8px; padding: 8px 12px; font-size: 12px; font-weight: 600; }
            QPushButton#settingsButton { background: #202433; border: 1px solid #33384b; color: #e3e1ee; }
            QPushButton#settingsButton:hover { background: #292d40; }
            QPushButton#settingsSave { background: #5d52ca; border: 1px solid #776aec; color: white; }
            QPushButton#settingsSave:hover { background: #6b60df; }
        """)

    def _image_label_text(self) -> str:
        return self.image_path if self.image_path else "No image selected"

    def _choose_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose an image", self.image_path,
            "Image files (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;All files (*.*)")
        if path:
            self.image_path = path
            self.image_label.setText(self._image_label_text())

    def save(self) -> None:
        try:
            set_autostart_enabled(self.start_with_windows.isChecked())
        except OSError as exc:
            QMessageBox.critical(self, "Voice Input", f"Could not update Windows startup: {exc}")
            return
        self.config.model = self.model.currentText()
        self.config.device = self.device.currentText()
        self.config.language = self.language.currentText()
        self.config.microphone = self.microphone.currentText()
        self.config.auto_copy = self.copy.isChecked()
        self.config.auto_paste = self.paste.isChecked()
        self.config.start_with_windows = self.start_with_windows.isChecked()
        self.config.image_path = self.image_path
        self.config.enable_extraction = self.enable_extraction.isChecked()
        self.config.enable_font = self.enable_font.isChecked()
        self.config.enable_files = self.enable_files.isChecked()
        self.config.sidebar_collapsed = self.sidebar_collapsed.isChecked()
        self.config.save()
        self.saved.emit()
        self.close()
