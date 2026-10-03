from __future__ import annotations

import logging
import multiprocessing as mp
import os
import queue
import sys
import time
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal, Qt, Slot
from PySide6.QtWidgets import QApplication

from .clipboard import copy_text, paste_text
from .config import Config
from .hotkey import PushToTalkHotkey
from .recorder import Recorder
from .extraction_worker import start_extraction_worker
from .worker import start_worker
from .ui.main_window import MainWindow
from .ui.recording_overlay import RecordingOverlay
from .ui.settings_window import SettingsWindow
from .ui.tray import Tray


class HotkeyBridge(QObject):
    pressed = Signal()
    released = Signal()


class AudioLevelBridge(QObject):
    """Marshal recorder-thread RMS values onto Qt's GUI thread."""
    level = Signal(float)


class VoiceInputApp(QObject):
    worker_start_timeout = 120
    transcription_timeout = 120

    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self.app, self.config = app, Config.load()

        # ── Independent feature states ────────────────────────────────────────
        self.voice_state = "IDLE"
        self.extraction_state = "IDLE"
        # font_state / files_state are placeholders for future backends
        self.font_state = "IDLE"
        self.files_state = "IDLE"

        self.recorder = Recorder(self.config.microphone)
        self.worker = self.command_queue = self.result_queue = None
        self.worker_state = "OFFLINE"
        self.worker_started_at = self.transcription_started_at = 0.0
        self.next_request_id = 0
        self.pending_request_id = None
        self.settings_window = None
        self.extraction_process = self.extraction_result_queue = self.extraction_cancel_event = None
        self.extraction_source_path = ""

        self.tray = Tray()
        self.tray.show_main.connect(self.show_main)
        self.tray.show_settings.connect(self.show_settings)
        self.tray.quit_requested.connect(self.shutdown)

        self.overlay = RecordingOverlay()
        self.main_window = MainWindow(self.config)

        # Wire main_window signals
        self.main_window.open_settings.connect(self.show_settings)
        self.main_window.hidden_to_tray.connect(self.notify_background)
        self.main_window.cancel_requested.connect(self.cancel_active)
        self.main_window.copy_requested.connect(self.copy_history_item)
        self.main_window.extraction_requested.connect(self.start_extraction)
        self.main_window.extraction_cancel_requested.connect(self.cancel_extraction)
        self.main_window.extraction_toggled.connect(self.handle_extraction_toggled)
        self.main_window.font_toggled.connect(self.handle_font_toggled)
        self.main_window.files_toggled.connect(self.handle_files_toggled)

        # Audio level bridge — feeds both the overlay and the Capture page waveform
        self.audio_level_bridge = AudioLevelBridge(self)
        self.audio_level_bridge.level.connect(
            self.overlay.update_audio_level, Qt.ConnectionType.QueuedConnection)
        self.audio_level_bridge.level.connect(
            self.main_window.update_audio_level, Qt.ConnectionType.QueuedConnection)
        self.recorder.set_level_callback(self.audio_level_bridge.level.emit)

        self.main_window.show()

        # Hotkey
        self.hotkey_bridge = HotkeyBridge(self)
        self.hotkey_bridge.pressed.connect(self.start_recording, Qt.ConnectionType.QueuedConnection)
        self.hotkey_bridge.released.connect(self.stop_recording, Qt.ConnectionType.QueuedConnection)
        self.hotkey = PushToTalkHotkey(self.hotkey_bridge.pressed.emit, self.hotkey_bridge.released.emit)
        self.hotkey.start()
        if self.hotkey.startup_error:
            self.voice_status("ERROR", f"Global Ctrl + Space is unavailable: {self.hotkey.startup_error}")
        else:
            self.voice_status("IDLE")
            logging.info("Voice Input ready: tap Ctrl+Space to toggle or hold to record")

        self.ensure_worker()

        # Single polling timer — polls both voice worker and extraction worker
        self.timer = QTimer()
        self.timer.timeout.connect(self.poll_worker)
        self.timer.timeout.connect(self.poll_extraction)
        self.timer.start(100)

    # ── Voice state ───────────────────────────────────────────────────────────

    def voice_status(self, state: str, message: str = "") -> None:
        self.voice_state = state
        self.tray.set_status(state.title(), message)
        self.main_window.update_status(state, message)

    # ── Extraction state ──────────────────────────────────────────────────────

    def extraction_status(self, state: str, message: str = "") -> None:
        self.extraction_state = state
        self.main_window.update_extraction_status(state, message)

    # ── Whisper worker management ─────────────────────────────────────────────

    def ensure_worker(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        self.finish_worker()
        settings = {key: getattr(self.config, key) for key in ("model", "language", "device", "compute_type")}
        self.worker, self.command_queue, self.result_queue = start_worker(settings)
        self.worker_state = "STARTING"
        self.worker_started_at = time.monotonic()
        logging.info("Starting background Whisper worker with model=%s", settings["model"])

    @Slot()
    def start_recording(self) -> None:
        if self.voice_state != "IDLE":
            return
        try:
            self.ensure_worker()
            self.recorder.start()
            self.overlay.show_recording()
            self.voice_status("RECORDING", "Recording… release Ctrl + Space to transcribe.")
            logging.info("Recording started")
        except Exception as exc:
            logging.exception("Microphone unavailable")
            self.voice_status("ERROR", f"Microphone error: {exc}")
            QTimer.singleShot(2500, self.return_idle)

    @Slot()
    def stop_recording(self) -> None:
        if self.voice_state != "RECORDING":
            return
        try:
            audio = self.recorder.stop()
            logging.info("Captured %d audio samples", len(audio))
            if len(audio) < self.recorder.sample_rate // 4:
                self.overlay.hide_overlay()
                self.voice_status("IDLE", "No usable audio captured.")
                return
            self.ensure_worker()
            if not self.command_queue:
                raise RuntimeError("Whisper worker could not be started")
            self.next_request_id += 1
            self.pending_request_id = self.next_request_id
            self.transcription_started_at = time.monotonic()
            self.command_queue.put((self.pending_request_id, audio))
            self.voice_status("TRANSCRIBING", "Transcribing locally…")
            self.overlay.show_processing()
        except Exception as exc:
            logging.exception("Recording stop failed")
            self.overlay.hide_overlay()
            self.voice_status("ERROR", f"Recording error: {exc}")
            QTimer.singleShot(2500, self.return_idle)

    def poll_worker(self) -> None:
        if not self.worker or not self.result_queue:
            return
        try:
            message = self.result_queue.get_nowait()
        except queue.Empty:
            now = time.monotonic()
            if not self.worker.is_alive():
                if self.pending_request_id or self.worker_state == "READY":
                    self.handle_worker_failure("Whisper stopped before returning a result.")
            elif self.worker_state == "STARTING" and now - self.worker_started_at > self.worker_start_timeout:
                self.handle_worker_failure("Whisper took too long to start.")
            elif self.pending_request_id and now - self.transcription_started_at > self.transcription_timeout:
                self.handle_worker_failure("Transcription timed out. Please try again.")
            return
        self.handle_worker_message(message)

    # ── Extraction worker management ──────────────────────────────────────────

    @Slot(str)
    def start_extraction(self, path: str) -> None:
        if not self.config.enable_extraction:
            self.extraction_status("ERROR", "Enable Printed Text Extraction to extract text.")
            return
        if self.extraction_state != "IDLE":
            return
        if self.extraction_process:
            return
        try:
            self.extraction_process, self.extraction_result_queue, self.extraction_cancel_event = \
                start_extraction_worker(path)
            self.extraction_source_path = path
            self.extraction_status("EXTRACTING", "Detecting the file and extracting text locally...")
        except Exception as exc:
            logging.exception("Could not start extraction worker")
            self.extraction_status("ERROR", f"Could not start extraction: {exc}")

    def poll_extraction(self) -> None:
        process, results = self.extraction_process, self.extraction_result_queue
        if not process or not results:
            return
        try:
            message = results.get_nowait()
        except queue.Empty:
            if not process.is_alive():
                self.finish_extraction_worker()
                self.extraction_status("ERROR", "The extraction worker stopped before returning a result.")
                QTimer.singleShot(4000, self._reset_extraction_state)
            return

        kind = message[0]

        # Status updates: progress messages — do NOT call finish_extraction_worker
        if kind == "status":
            _status_type = message[1] if len(message) > 1 else ""
            detail = message[2] if len(message) > 2 else "Processing…"
            if _status_type == "loading_model":
                self.extraction_status("EXTRACTING", f"⏳ {detail}")
            else:
                self.extraction_status("EXTRACTING", detail)
            return  # keep polling

        # Final result message
        self.finish_extraction_worker()
        if message[1] != "ok":
            detail = message[2] if len(message) > 2 else "Extraction failed."
            if "No printed or selectable text" in detail:
                self.extraction_status("IDLE", "No printed text was detected in this file.")
            elif "cancelled" in detail.lower():
                self.extraction_status("IDLE", "Extraction cancelled.")
            else:
                self.extraction_status("ERROR", detail)
                QTimer.singleShot(4000, self._reset_extraction_state)
            return

        _kind, _outcome, text, output_path, input_kind = message
        try:
            output_action = self.publish_voice_output(text) if False else self.publish_extraction_output(
                text, input_kind, output_path)
            filename = Path(output_path).name
            detail = f"Saved {filename}. {output_action}."
            self.extraction_status("SUCCESS", detail)
            logging.info("Extracted %s to %s", input_kind, output_path)
            QTimer.singleShot(5000, self._reset_extraction_state)
        except Exception as exc:
            logging.exception("Could not share extracted output")
            self.extraction_status("ERROR", f"Text was created, but clipboard output failed: {exc}")
            QTimer.singleShot(4000, self._reset_extraction_state)

    def publish_extraction_output(self, text: str, input_kind: str, output_path: str) -> str:
        """Add to extraction history, then copy/paste."""
        label_map = {
            "raster": "Image extraction",
            "pdf": "PDF extraction",
            "docx": "DOCX extraction",
            "svg": "SVG extraction",
        }
        label = label_map.get(input_kind, "Extraction")
        self.config.add_extraction_history(text, label)
        # Refresh extract page history if visible
        self.main_window.extract_page.populate_history(
            self.config.extraction_history, self.main_window.copy_requested.emit)
        if self.config.auto_paste:
            paste_text(text)
            return "Pasted"
        if self.config.auto_copy:
            copy_text(text)
            return "Copied to clipboard"
        return "Complete"

    @Slot()
    def _reset_extraction_state(self) -> None:
        """Return extraction pipeline to IDLE so the Extract Text button re-enables."""
        if self.extraction_state not in ("EXTRACTING",):
            self.extraction_state = "IDLE"
            self.main_window.update_extraction_status("IDLE")

    @Slot()
    def cancel_extraction(self) -> None:
        if not self.extraction_process:
            return
        if self.extraction_cancel_event:
            self.extraction_cancel_event.set()
        self.finish_extraction_worker(terminate=True)
        self.extraction_source_path = ""
        self.extraction_status("IDLE", "Extraction cancelled.")

    @Slot(bool)
    def handle_extraction_toggled(self, enabled: bool) -> None:
        if not enabled and self.extraction_process:
            self.cancel_extraction()

    @Slot(bool)
    def handle_font_toggled(self, enabled: bool) -> None:
        """Future: initialize/teardown font generation backend."""
        self.config.enable_font = enabled
        self.config.save()
        logging.info("Create Font feature toggled: %s", enabled)

    @Slot(bool)
    def handle_files_toggled(self, enabled: bool) -> None:
        """Future: initialize/teardown file generation backend."""
        self.config.enable_files = enabled
        self.config.save()
        logging.info("Create Files feature toggled: %s", enabled)

    def finish_extraction_worker(self, terminate: bool = False) -> None:
        process = self.extraction_process
        if process:
            if terminate and process.is_alive():
                process.terminate()
            process.join(timeout=1)
            if process.is_alive():
                process.terminate()
                process.join(timeout=1)
        self.extraction_process = self.extraction_result_queue = self.extraction_cancel_event = None
        self.extraction_source_path = ""

    # ── Whisper result handling ───────────────────────────────────────────────

    def handle_worker_message(self, message: tuple) -> None:
        kind = message[0]
        if kind == "ready":
            self.worker_state = "READY"
            logging.info("Background Whisper worker is ready")
            return
        if kind == "startup_error":
            logging.error("Whisper startup failed: %s", message[1])
            self.handle_worker_failure("Whisper could not start. See the log for details.")
            return
        if kind != "result":
            logging.error("Unknown worker message: %r", message)
            return

        request_id, outcome, value = message[1:]
        if request_id != self.pending_request_id:
            return
        self.pending_request_id = None
        if outcome == "error":
            logging.error("Transcription failed: %s", value)
            self.finish_worker()
            self.overlay.hide_overlay()
            self.voice_status("ERROR", "Transcription failed. See the log for details.")
            QTimer.singleShot(2500, self.return_idle)
            return
        if value:
            try:
                action = self.publish_voice_output(value)
                self.overlay.set_message(action)
            except Exception as exc:
                self.voice_status("ERROR", f"Clipboard error: {exc}")
                self.overlay.set_message("Clipboard error")
            QTimer.singleShot(2500, self.return_idle)
        else:
            self.voice_status("IDLE", "No speech detected. Hold Ctrl + Space while speaking.")
            self.overlay.set_message("No speech detected")
            QTimer.singleShot(1500, self.return_idle)

    def publish_voice_output(self, text: str) -> str:
        """Add to voice history, then copy/paste. Returns action description."""
        self.config.add_voice_history(text)
        # Refresh Capture page history live
        self.main_window.capture_page.populate_history(
            self.config.voice_history, self.main_window.copy_requested.emit)
        self.main_window.refresh_config()
        if self.config.auto_paste:
            paste_text(text)
            return "Pasted"
        if self.config.auto_copy:
            copy_text(text)
            return "Copied to clipboard"
        return "Complete"

    # Legacy compat used by old call sites
    def publish_output(self, text: str, label: str = "") -> str:
        return self.publish_voice_output(text)

    @Slot()
    def cancel_active(self) -> None:
        """Stop recording or discard an in-flight transcription from the UI."""
        if self.voice_state == "RECORDING":
            self.stop_recording()
            return
        if self.voice_state == "TRANSCRIBING":
            self.pending_request_id = None
            self.finish_worker()
            self.overlay.hide_overlay()
            self.voice_status("IDLE", "Transcription stopped.")
            return

    @Slot(str)
    def copy_history_item(self, text: str) -> None:
        try:
            copy_text(text)
        except Exception:
            logging.exception("History copy failed")

    def handle_worker_failure(self, message: str) -> None:
        self.pending_request_id = None
        self.finish_worker()
        if self.recorder.recording:
            self.recorder.stop()
        self.overlay.hide_overlay()
        self.voice_status("ERROR", message)
        QTimer.singleShot(3500, self.return_idle)

    @Slot()
    def return_idle(self) -> None:
        self.overlay.hide_overlay()
        self.voice_status("IDLE")

    def finish_worker(self) -> None:
        worker, commands = self.worker, self.command_queue
        if worker:
            if commands and worker.is_alive():
                try:
                    commands.put(None)
                except (OSError, ValueError):
                    pass
            worker.join(timeout=0.5)
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=1)
        self.worker = self.command_queue = self.result_queue = None
        self.worker_state = "OFFLINE"

    # ── Settings / main window ────────────────────────────────────────────────

    def show_settings(self) -> None:
        if self.settings_window and self.settings_window.isVisible():
            self.settings_window.raise_()
            self.settings_window.activateWindow()
            return
        self.settings_window = SettingsWindow(self.config, self.voice_state.title())
        self.settings_window.saved.connect(self.settings_saved)
        self.settings_window.show()
        self.settings_window.raise_()

    def settings_saved(self) -> None:
        self.main_window.refresh_config()
        if self.voice_state == "IDLE":
            self.finish_worker()

    def show_main(self) -> None:
        self.main_window.refresh_config()
        self.main_window.show_and_raise()

    def notify_background(self) -> None:
        self.tray.showMessage("Voice Input",
                              "Voice Input is still running in the background. Use the tray icon to reopen it.")

    def shutdown(self) -> None:
        self.hotkey.stop()
        if self.recorder.recording:
            self.recorder.stop()
        self.overlay.hide_overlay()
        self.finish_extraction_worker(terminate=True)
        self.finish_worker()
        self.app.quit()


def run() -> None:
    mp.freeze_support()

    import ctypes
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "VoiceInput_SingleInstance_Mutex")
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        return

    root = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "VoiceInput" \
        if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
    (root / "logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=root / "logs" / "voice-input.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.info("Voice Input starting (pid=%s, frozen=%s)", os.getpid(), getattr(sys, "frozen", False))
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    controller = VoiceInputApp(app)
    app.voice_input_controller = controller
    sys.exit(app.exec())
