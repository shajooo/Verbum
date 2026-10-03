"""
recording_overlay.py — waveform visualization and background recording indicator.

RecordingVisualization  — data-driven waveform widget used by both the
                           main Capture page and the floating overlay.

RecordingOverlay        — compact non-focusable floating window that appears
                           when the main window is hidden while recording continues.
                           Uses indigo/violet accent; no red dot.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QTimer, Qt, Slot
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class RecordingVisualization(QWidget):
    """Compact data-driven microphone waveform used by the overlay and main UI."""

    _left_weights = (0.18, 0.32, 0.55, 0.82, 0.65, 0.42)
    _right_weights = (0.15, 0.37, 0.68, 0.92, 0.58, 0.34)

    def __init__(self, width: int = 252, height: int = 66, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(width, height)
        self._target = self._displayed = 0.0
        self._noise_floor = 0.0025
        self._active = False
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._advance)

    def begin(self) -> None:
        self._active = True
        self._target = self._displayed = 0.0
        self._noise_floor = 0.0025
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    def settle(self) -> None:
        self._active = False
        self._target = 0.0
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        self._active = False
        self._target = self._displayed = 0.0
        self._timer.stop()
        self.update()

    @Slot(float)
    def set_audio_level(self, rms: float) -> None:
        if not self._active:
            return
        level = max(0.0, min(float(rms), 1.0))
        # Adaptive noise floor: ambience updates quickly; speech moves it very slowly.
        if level <= self._noise_floor * 1.45:
            self._noise_floor = self._noise_floor * 0.94 + level * 0.06
        else:
            self._noise_floor = self._noise_floor * 0.998 + level * 0.002
        self._noise_floor = max(0.0008, min(self._noise_floor, 0.08))
        threshold = max(0.0045, self._noise_floor * 2.15 + 0.0015)
        excess = max(0.0, level - threshold)
        # Compress peaks so ordinary speech is clearly visible in this widget.
        self._target = min(1.0, math.log1p(excess * 95.0) / math.log1p(14.25))
        if not self._timer.isActive():
            self._timer.start()

    def _advance(self) -> None:
        factor = 0.48 if self._target > self._displayed else 0.22
        self._displayed += (self._target - self._displayed) * factor
        if self._displayed < 0.006 and self._target == 0.0:
            self._displayed = 0.0
            self._timer.stop()
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center_x, center_y = self.width() / 2, self.height() / 2
        accent, faint = QColor("#8778ff"), QColor("#3a3d60")
        baseline = 2.5
        for direction, weights in ((-1, self._left_weights), (1, self._right_weights)):
            for index, weight in enumerate(weights):
                distance = 24 + (len(weights) - index) * 8
                x = center_x + direction * distance
                half_height = baseline + self._displayed * weight * 22
                color = QColor(accent)
                color.setAlpha(105 + int(min(1.0, self._displayed * 1.4) * 135))
                pen = QPen(color, 2.0 if index > 2 else 1.5)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)
                painter.drawLine(int(x), int(center_y - half_height), int(x), int(center_y + half_height))
        painter.setPen(QPen(faint, 1.0))
        painter.drawLine(10, int(center_y), int(center_x - 76), int(center_y))
        painter.drawLine(int(center_x + 76), int(center_y), self.width() - 10, int(center_y))

        ring = QColor("#5d5aab")
        ring.setAlpha(110 + int(self._displayed * 80))
        painter.setPen(QPen(ring, 1.0))
        painter.setBrush(QColor("#17182a"))
        painter.drawEllipse(int(center_x - 20), int(center_y - 20), 40, 40)
        mic_pen = QPen(QColor("#f1f0ff"), 2.3)
        mic_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        mic_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(mic_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(center_x - 4.8, center_y - 12, 9.6, 18, 4.8, 4.8)
        path = QPainterPath()
        path.moveTo(center_x - 10, center_y + 1)
        path.cubicTo(center_x - 10, center_y + 14, center_x + 10, center_y + 14, center_x + 10, center_y + 1)
        painter.drawPath(path)
        painter.drawLine(int(center_x), int(center_y + 14), int(center_x), int(center_y + 19))
        painter.drawLine(int(center_x - 6), int(center_y + 19), int(center_x + 6), int(center_y + 19))


# ─── Compact background overlay waveform (smaller) ────────────────────────────

class CompactVisualization(QWidget):
    """
    Very compact waveform visualization for the background recording overlay.

    Bar layout:   ▂ ▄ █ ▄ ▂  🎙  ▂ ▄ █ ▄ ▂
    Accent:       indigo/violet (#7c72f8)
    No red.
    """

    _left_weights =  (0.25, 0.55, 0.88, 0.60, 0.30)
    _right_weights = (0.28, 0.58, 0.90, 0.55, 0.26)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(160, 44)
        self._target = self._displayed = 0.0
        self._noise_floor = 0.0025
        self._active = False
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._advance)

    def begin(self) -> None:
        self._active = True
        self._target = self._displayed = 0.0
        self._noise_floor = 0.0025
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    def settle(self) -> None:
        self._active = False
        self._target = 0.0
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        self._active = False
        self._target = self._displayed = 0.0
        self._timer.stop()
        self.update()

    @Slot(float)
    def set_audio_level(self, rms: float) -> None:
        if not self._active:
            return
        level = max(0.0, min(float(rms), 1.0))
        if level <= self._noise_floor * 1.45:
            self._noise_floor = self._noise_floor * 0.94 + level * 0.06
        else:
            self._noise_floor = self._noise_floor * 0.998 + level * 0.002
        self._noise_floor = max(0.0008, min(self._noise_floor, 0.08))
        threshold = max(0.0045, self._noise_floor * 2.15 + 0.0015)
        excess = max(0.0, level - threshold)
        self._target = min(1.0, math.log1p(excess * 95.0) / math.log1p(14.25))
        if not self._timer.isActive():
            self._timer.start()

    def _advance(self) -> None:
        factor = 0.48 if self._target > self._displayed else 0.22
        self._displayed += (self._target - self._displayed) * factor
        if self._displayed < 0.006 and self._target == 0.0:
            self._displayed = 0.0
            self._timer.stop()
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2

        accent = QColor("#7c72f8")
        faint_line = QColor("#2e3050")
        baseline = 1.5

        for direction, weights in ((-1, self._left_weights), (1, self._right_weights)):
            for i, weight in enumerate(weights):
                dist = 18 + (len(weights) - i) * 6
                x = cx + direction * dist
                half_h = baseline + self._displayed * weight * 14
                col = QColor(accent)
                col.setAlpha(100 + int(min(1.0, self._displayed * 1.5) * 140))
                pen = QPen(col, 2.2 if i > 2 else 1.6)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)
                painter.drawLine(int(x), int(cy - half_h), int(x), int(cy + half_h))

        # Horizontal guide lines
        painter.setPen(QPen(faint_line, 0.8))
        painter.drawLine(4, int(cy), int(cx - 30), int(cy))
        painter.drawLine(int(cx + 30), int(cy), w - 4, int(cy))

        # Mic circle
        ring = QColor("#5551a8")
        ring.setAlpha(100 + int(self._displayed * 80))
        painter.setPen(QPen(ring, 1.0))
        painter.setBrush(QColor("#14152b"))
        r = 13
        painter.drawEllipse(int(cx - r), int(cy - r), r * 2, r * 2)

        # Mic icon (small)
        mp = QPen(QColor("#eeeeff"), 1.7)
        mp.setCapStyle(Qt.PenCapStyle.RoundCap)
        mp.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(mp)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(cx - 3, cy - 8, 6, 11, 3, 3)
        path = QPainterPath()
        path.moveTo(cx - 6, cy + 1)
        path.cubicTo(cx - 6, cy + 9, cx + 6, cy + 9, cx + 6, cy + 1)
        painter.drawPath(path)
        painter.drawLine(int(cx), int(cy + 9), int(cx), int(cy + 12))
        painter.drawLine(int(cx - 3), int(cy + 12), int(cx + 3), int(cy + 12))


# ─── Background overlay window ────────────────────────────────────────────────

class RecordingOverlay(QWidget):
    """
    Small, non-focusable background recording indicator.

    Replaces the old red pulsing dot with a compact indigo/violet
    microphone + waveform indicator.  No red.  No large card.  No orb.
    """

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setObjectName("recordingOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.visualization = CompactVisualization(self)

        self.text = QLabel(self)
        self.text.setObjectName("overlayMessage")
        self.text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.text.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(2)
        layout.addWidget(self.visualization, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.text)

        self.setStyleSheet("""
            QWidget#recordingOverlay {
                background: rgba(13, 14, 26, 238);
                border: 1px solid #2e3158;
                border-radius: 14px;
            }
            QLabel#overlayMessage {
                color: #c0bcff;
                font-size: 11px;
                font-weight: 600;
                font-family: "Segoe UI";
                padding: 0 0 3px 0;
            }
        """)
        self.setFixedSize(176, 58)
        self.hide()

    def _place(self) -> None:
        screen = self.screen()
        if screen:
            area = screen.availableGeometry()
            self.move(area.center().x() - self.width() // 2, area.bottom() - self.height() - 70)

    def show_recording(self) -> None:
        self.text.hide()
        self.setFixedSize(176, 58)
        self._place()
        self.visualization.begin()
        self.show()

    @Slot(float)
    def update_audio_level(self, rms: float) -> None:
        self.visualization.set_audio_level(rms)

    def show_processing(self) -> None:
        self.visualization.settle()
        self.text.setText("Transcribing…")
        self.text.show()
        self.setFixedSize(176, 76)
        self._place()
        self.show()

    def set_message(self, message: str) -> None:
        self.visualization.settle()
        self.text.setText(message)
        self.text.show()
        self.setFixedSize(176, 76)
        self._place()
        self.show()

    def hide_overlay(self) -> None:
        self.visualization.stop()
        self.text.hide()
        self.hide()
