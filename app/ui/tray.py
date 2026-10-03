from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QStyle, QSystemTrayIcon


class Tray(QObject):
    show_main = Signal()
    show_settings = Signal()
    quit_requested = Signal()
    def __init__(self) -> None:
        super().__init__()
        icon = QStyle.StandardPixmap.SP_MediaPlay
        self.tray = QSystemTrayIcon(self.style_icon(icon))
        self.menu = QMenu()
        self.status_action = QAction("Status: Ready"); self.status_action.setEnabled(False); self.menu.addAction(self.status_action)
        self.menu.addSeparator()
        open_main = self.menu.addAction("Open Voice Input"); open_main.triggered.connect(self.show_main)
        settings = self.menu.addAction("Settings"); settings.triggered.connect(self.show_settings)
        self.menu.addAction("About", lambda: self.tray.showMessage("Voice Input", "Local push-to-talk transcription.\nHold Ctrl + Space to record."))
        self.menu.addSeparator(); exit_action = self.menu.addAction("Exit"); exit_action.triggered.connect(self.quit_requested)
        self.tray.activated.connect(self.on_activated)
        self.tray.setContextMenu(self.menu)
        self.tray.setToolTip("Voice Input - Ready")
        self.tray.show()

    def on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_main.emit()
        self.tray.setContextMenu(self.menu); self.tray.setToolTip("Voice Input — Ready"); self.tray.show()

    def style_icon(self, icon: QStyle.StandardPixmap) -> QIcon:
        from PySide6.QtWidgets import QApplication
        return QApplication.style().standardIcon(icon)

    def set_status(self, status: str, detail: str = "") -> None:
        self.status_action.setText(f"Status: {status}"); self.tray.setToolTip(f"Voice Input — {status}")
        if detail: self.tray.showMessage("Voice Input", detail, QSystemTrayIcon.MessageIcon.Information, 2500)

    def showMessage(self, title: str, message: str, icon: QSystemTrayIcon.MessageIcon = QSystemTrayIcon.MessageIcon.Information, msecs: int = 2500) -> None:
        self.tray.showMessage(title, message, icon, msecs)
