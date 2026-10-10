from __future__ import annotations

import logging
import multiprocessing as mp
import os
import queue
import shutil
import sys
import time
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal, Qt, Slot, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QFileDialog

from .clipboard import copy_text, paste_text
from .config import Config
from .hotkey import PushToTalkHotkey
from .recorder import Recorder
from .resources import application_output_root, font_dataset_paths
from .extraction_worker import start_extraction_worker
from .translation_worker import start_translation_worker
from .font_worker import start_font_worker
from .font_intake_worker import start_font_intake_worker
from .font_projects import FontProjectStore
from .pdf_worker import start_pdf_worker
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
        self.translation_state = "IDLE"
        self.font_state = "IDLE"
        self.files_state = "IDLE"
        self.font_process = self.font_result_queue = self.font_cancel_event = None
        self.font_intake_process = self.font_intake_queue = self.font_intake_cancel = None
        self.font_intake_project_id = ""
        self.font_generation_project_id = ""
        self.font_generation_version = 0
        self.font_projects = FontProjectStore()
        self.pdf_process = self.pdf_result_queue = self.pdf_cancel_event = None
        self.last_generated_pdf_path = ""

        self.recorder = Recorder(self.config.microphone)
        self.worker = self.command_queue = self.result_queue = None
        self.worker_state = "OFFLINE"
        self.worker_started_at = self.transcription_started_at = 0.0
        self.next_request_id = 0
        self.pending_request_id = None
        self.settings_window = None
        self.extraction_process = self.extraction_result_queue = self.extraction_cancel_event = None
        self.extraction_source_path = ""
        self.translation_process = None
        self.translation_commands = None
        self.translation_results = None
        self.translation_cancel_event = None
        self.pending_translation_request_id = None
        self._pending_translation_text = ""   # original text saved while worker runs
        self._translation_job_kind = ""

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
        self.main_window.font_generation_requested.connect(self.start_font_generation)
        self.main_window.font_cancel_requested.connect(self.cancel_font_generation)
        self.main_window.font_download_ttf_requested.connect(self.download_ttf)
        self.main_window.font_download_otf_requested.connect(self.download_otf)
        self.main_window.font_project_create_requested.connect(self.create_font_project)
        self.main_window.font_project_selected.connect(self.select_font_project)
        self.main_window.font_generation_selected.connect(self.select_font_generation)
        self.main_window.font_sample_selected.connect(self.start_font_intake)
        self.main_window.font_sample_accept_requested.connect(self.accept_font_sample)
        self.main_window.font_candidate_accept_requested.connect(self.accept_font_candidate)
        self.main_window.font_sample_review_requested.connect(self.review_font_sample)
        self.main_window.font_sample_remove_requested.connect(self.remove_font_sample)
        self.main_window.font_samples_merge_requested.connect(self.merge_font_samples)

        self._refresh_font_projects()
        self.main_window.files_toggled.connect(self.handle_files_toggled)
        self.main_window.pdf_generation_requested.connect(self.start_pdf_generation)
        self.main_window.pdf_cancel_requested.connect(self.cancel_pdf_generation)
        self.main_window.pdf_download_requested.connect(self.download_pdf)
        self.main_window.pdf_open_requested.connect(self.open_pdf)
        self.main_window.translation_requested.connect(self.start_translation)
        self.main_window.translation_cancelled.connect(self.cancel_translation)
        self.main_window.translation_toggled.connect(self.handle_translation_toggled)
        self.main_window.translation_setup_requested.connect(self.install_translation_model)

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

        # Single polling timer — polls voice worker, extraction worker, translation, font, and pdf workers
        self.timer = QTimer()
        self.timer.timeout.connect(self.poll_worker)
        self.timer.timeout.connect(self.poll_extraction)
        self.timer.timeout.connect(self.poll_translation)
        self.timer.timeout.connect(self.poll_font)
        self.timer.timeout.connect(self.poll_font_intake)
        self.timer.timeout.connect(self.poll_pdf)
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

    # ── Translation worker management ────────────────────────────────────────────

    def ensure_translation_worker(self) -> None:
        """Start long-running translation worker if not already running."""
        if self.translation_process is not None and self.translation_process.is_alive():
            return
        self.finish_translation_worker(terminate=True)
        try:
            self.translation_process, self.translation_commands, self.translation_results, self.translation_cancel_event = \
                start_translation_worker()
            logging.info("Persistent translation worker process started (pid=%s)", self.translation_process.pid)
        except Exception as exc:
            logging.exception("Failed to start translation worker process")
            self.main_window.show_translation_error(f"Could not initialize translation service: {exc}")

    @Slot(str, str)
    def start_translation(self, text: str, source_lang: str) -> None:
        """Submit a translation job to the persistent worker process."""
        if not self.config.enable_translation:
            self.main_window.show_translation_error("Enable Translation to use this feature.")
            return
        if self.translation_state != "IDLE":
            return
        text = text.strip()
        if not text:
            self.main_window.show_translation_error("Input text cannot be empty.")
            return

        self.ensure_translation_worker()
        if not self.translation_process or not self.translation_commands:
            self.main_window.show_translation_error("Translation service is currently unavailable.")
            return

        import uuid
        req_id = str(uuid.uuid4())
        self.pending_translation_request_id = req_id
        self._pending_translation_text = text
        self._translation_job_kind = "translation"
        if self.translation_cancel_event:
            self.translation_cancel_event.clear()

        self.translation_state = "RUNNING"
        if source_lang == "auto":
            self.main_window.update_translation_status("detecting", "Preparing language detection…")
        else:
            self.main_window.update_translation_status("loading", "Preparing translation…")
        self.translation_commands.put(("translate", req_id, text, source_lang))
        logging.info("Submitted translation job (req_id=%s, lang=%s, length=%d)", req_id, source_lang, len(text))

    @Slot()
    def install_translation_model(self) -> None:
        """Run an explicit, user-initiated one-time local model setup."""
        if not self.config.enable_translation or self.translation_state != "IDLE":
            return
        self.ensure_translation_worker()
        if not self.translation_process or not self.translation_commands:
            self.main_window.show_translation_error("Translation service is currently unavailable.")
            return
        import uuid
        req_id = str(uuid.uuid4())
        self.pending_translation_request_id = req_id
        self._translation_job_kind = "install"
        self.translation_state = "RUNNING"
        self.translation_commands.put(("install", req_id))
        logging.info("Submitted explicit translation model setup (req_id=%s)", req_id)

    def poll_translation(self) -> None:
        """Poll translation result queue (runs every 100 ms on main timer)."""
        process, results = self.translation_process, self.translation_results
        if not process or not results:
            return
        try:
            message = results.get_nowait()
        except queue.Empty:
            if self.translation_state == "RUNNING" and not process.is_alive():
                self.finish_translation_worker()
                self.translation_state = "IDLE"
                self.pending_translation_request_id = None
                self.main_window.show_translation_error("The translation worker stopped unexpectedly.")
            return

        kind = message[0]
        req_id = message[1] if len(message) > 1 else ""

        # Ignore results from cancelled / stale requests
        if req_id != self.pending_translation_request_id:
            return

        if kind == "status":
            status_kind = message[2] if len(message) > 2 else ""
            detail = message[3] if len(message) > 3 else ""
            self.main_window.update_translation_status(status_kind, detail)
            return

        # Final result received
        self.translation_state = "IDLE"
        self.pending_translation_request_id = None

        if kind == "result":
            outcome = message[2] if len(message) > 2 else ""
            if outcome == "ok":
                translated = message[3]
                source_lang = message[4]
                source_name = message[5]
                original = self._pending_translation_text
                self._pending_translation_text = ""
                # Persist to history
                self.config.add_translation_history(
                    original=original,
                    translated=translated,
                    source_lang=source_lang,
                    source_name=source_name,
                )
                # Persist source language preference if in manual mode
                if self.config.translation_detect_mode == "manual":
                    self.config.translation_source_lang = source_lang
                    self.config.save()
                # Update UI
                self.main_window.show_translation_result(original, translated, source_lang, source_name)
                self.main_window.translate_page.populate_history(
                    self.config.translation_history,
                    self.main_window.copy_requested.emit,
                )
                self._translation_job_kind = ""
                logging.info("Translation complete: %s → English (%d chars)", source_name, len(translated))
            elif outcome == "installed":
                self._translation_job_kind = ""
                self.main_window.translate_page.show_model_installed()
                logging.info("Translation model setup complete")
            elif outcome == "model_missing":
                self._translation_job_kind = ""
                self._pending_translation_text = ""
                err = message[3] if len(message) > 3 else "Translation model is not installed."
                self.main_window.translate_page.show_model_missing(err)
            elif outcome == "cancelled":
                self._pending_translation_text = ""
                self._translation_job_kind = ""
                self.main_window.show_translation_cancelled()
            else:
                err = message[3] if len(message) > 3 else "Translation failed."
                if len(message) > 5:
                    logging.error(
                        "Translation setup failure [%s]:\n%s",
                        message[4], message[5],
                    )
                self._pending_translation_text = ""
                self._translation_job_kind = ""
                self.main_window.show_translation_error(err)
                logging.error("Translation error: %s", err)

    @Slot()
    def cancel_translation(self) -> None:
        """Cancel an in-flight job and retire its isolated worker safely.

        Retiring the process avoids a shared cancellation-event race where a
        newly submitted job could clear the event before the old inference has
        observed it. The next translation lazily starts one fresh worker.
        """
        if self.translation_cancel_event:
            self.translation_cancel_event.set()
        self.finish_translation_worker(terminate=True)
        self._pending_translation_text = ""
        self.translation_state = "IDLE"
        self.main_window.show_translation_cancelled()

    def finish_translation_worker(self, terminate: bool = False) -> None:
        process = self.translation_process
        if process:
            if not terminate and self.translation_commands:
                try:
                    self.translation_commands.put(("shutdown",))
                except Exception:
                    pass
            if terminate and process.is_alive():
                process.terminate()
            process.join(timeout=1)
            if process.is_alive():
                process.terminate()
                process.join(timeout=1)
        self.translation_process = None
        self.translation_commands = None
        self.translation_results = None
        self.translation_cancel_event = None
        self.pending_translation_request_id = None
        self._translation_job_kind = ""

    @Slot(bool)
    def handle_translation_toggled(self, enabled: bool) -> None:
        """Handle Translation feature toggle."""
        self.config.enable_translation = enabled
        self.config.save()
        logging.info("Translation feature toggled: %s", enabled)
        if not enabled:
            if self.translation_state == "RUNNING":
                self.cancel_translation()
            self.finish_translation_worker(terminate=True)

    # Phase 1 font-project intake
    def _refresh_font_projects(self) -> None:
        # Keep the bundled verified starter project self-healing across PyInstaller
        # rebuilds, because its read-only resources live under the current bundle's
        # _internal directory.
        self.font_projects.ensure_legacy_project()
        projects = self.font_projects.list_projects()
        active = self.config.active_font_project_id
        if not any(item["project_id"] == active for item in projects):
            active = projects[0]["project_id"]
            self.config.active_font_project_id = active
            self.config.save()
        self.main_window.set_font_projects(projects, active)
        entries = self.font_projects.entries(active)
        summary = {state: sum(1 for entry in entries if entry.get("review_status") == state)
                   for state in ("GOOD", "REVIEW", "REJECT")}
        chars = {str(entry.get("char", "")) for entry in entries if entry.get("char")}
        coverage = {
            "upper": sum(1 for char in chars if len(char) == 1 and char.isascii() and char.isupper()),
            "lower": sum(1 for char in chars if len(char) == 1 and char.isascii() and char.islower()),
            "numbers": sum(1 for char in chars if len(char) == 1 and char.isdigit()),
            "punctuation": sum(1 for char in chars if len(char) == 1 and not char.isalnum() and not char.isspace()),
        }
        self.main_window.set_font_project_statistics(len(entries), summary, coverage)
        self.main_window.set_font_project_samples(
            self.font_projects.get(active), self.font_projects.staged_samples(active),
        )
        history = self.font_projects.generation_history(active)
        self.main_window.set_font_project_generation(
            self.font_projects.latest_generation(active), history)
        self.main_window.font_page.populate_history(
            [f"v{item['version']:03d} — {item.get('glyph_count', 0)} glyphs" for item in history],
            self.main_window.copy_requested.emit,
        )

    @Slot(str)
    def create_font_project(self, name: str) -> None:
        try:
            created = self.font_projects.create(name)
            self.config.active_font_project_id = created["project_id"]
            self.config.save()
            self._refresh_font_projects()
        except Exception as exc:
            self.main_window.show_font_intake_error(str(exc))

    @Slot(str)
    def select_font_project(self, project_id: str) -> None:
        try:
            self.font_projects.project_root(project_id)
            self.config.active_font_project_id = project_id
            self.config.save()
            self._refresh_font_projects()
        except Exception as exc:
            self.main_window.show_font_intake_error(str(exc))

    @Slot(int)
    def select_font_generation(self, version: int) -> None:
        """Select an immutable generated version from the active project only."""
        project_id = self.config.active_font_project_id
        try:
            record = self.font_projects.validated_generation(project_id, version)
            if record is None:
                raise ValueError("The selected generated font version is unavailable.")
            self.main_window.set_font_project_generation(
                record, self.font_projects.generation_history(project_id))
        except Exception as exc:
            self.main_window.show_font_error(str(exc))

    @Slot(str)
    def start_font_intake(self, path: str) -> None:
        project_id = self.config.active_font_project_id
        if not project_id:
            self.main_window.show_font_intake_error("Create a font project before adding handwriting samples.")
            return
        if self.font_intake_process and self.font_intake_process.is_alive():
            self.main_window.show_font_intake_error("A handwriting sample is already being analyzed.")
            return
        try:
            self.main_window.show_font_intake_progress("Copying sample into the active project…")
            self.font_intake_process, self.font_intake_queue, self.font_intake_cancel = start_font_intake_worker(project_id, path)
            self.font_intake_project_id = project_id
        except Exception as exc:
            self.main_window.show_font_intake_error(f"Could not start sample analysis: {exc}")

    def poll_font_intake(self) -> None:
        if not self.font_intake_queue:
            return
        try:
            kind, payload = self.font_intake_queue.get_nowait()
        except queue.Empty:
            return
        if kind == "progress":
            self.main_window.show_font_intake_progress(payload["message"])
            return
        process = self.font_intake_process
        if process:
            process.join(timeout=0.2)
        self.font_intake_process = self.font_intake_queue = self.font_intake_cancel = None
        if kind == "complete":
            result = payload["result"]
            if result.get("project_id") == self.font_intake_project_id and result.get("status") == "IMPORTED":
                # The note worker has already committed glyphs to the captured project.
                # Refresh the currently selected project so the dataset badges and
                # counts update immediately without ever mixing project state.
                self._refresh_font_projects()
            if result.get("project_id") != self.font_intake_project_id:
                self.main_window.show_font_intake_error("Project mismatch: this sample belongs to another font project.")
            elif result.get("project_id") != self.config.active_font_project_id:
                # A job retains the ID captured when it started.  Do not render
                # its result into a project selected while it was running.
                self._refresh_font_projects()
            else:
                self.main_window.show_font_intake_result(result)
        else:
            self.main_window.show_font_intake_error(payload.get("message", "Sample analysis failed."))

    @Slot(str, str)
    def accept_font_sample(self, sample_id: str, character: str) -> None:
        try:
            entry = self.font_projects.accept_isolated_sample(self.config.active_font_project_id, sample_id, character)
            self.main_window.show_font_sample_accepted(entry)
            self._refresh_font_projects()
        except Exception as exc:
            self.main_window.show_font_intake_error(str(exc))

    @Slot(str, str)
    def accept_font_candidate(self, sample_id: str, candidate_id: str) -> None:
        try:
            entry = self.font_projects.accept_candidate(
                self.config.active_font_project_id, sample_id, candidate_id,
            )
            self.main_window.show_font_sample_accepted(entry)
            self._refresh_font_projects()
        except Exception as exc:
            self.main_window.show_font_intake_error(str(exc))

    @Slot(str)
    def review_font_sample(self, sample_id: str) -> None:
        try:
            self.font_projects.review_sample(self.config.active_font_project_id, sample_id)
            self._refresh_font_projects()
        except Exception as exc:
            self.main_window.show_font_intake_error(str(exc))

    @Slot(str)
    def remove_font_sample(self, sample_id: str) -> None:
        try:
            self.font_projects.remove_staged_sample(self.config.active_font_project_id, sample_id)
            self._refresh_font_projects()
        except Exception as exc:
            self.main_window.show_font_intake_error(str(exc))

    @Slot()
    def merge_font_samples(self) -> None:
        try:
            count = self.font_projects.merge_accepted_samples(self.config.active_font_project_id)
            self.main_window.show_font_samples_merged(count)
            self._refresh_font_projects()
        except Exception as exc:
            self.main_window.show_font_intake_error(str(exc))

    # ── Font generation backend ───────────────────────────────────────────────

    @Slot()
    def start_font_generation(self) -> None:
        if not self.config.enable_font:
            self.main_window.show_font_error("Enable Create Font to generate your handwriting font.")
            return
        if self.font_state != "IDLE":
            return
        self.finish_font_worker(terminate=True)
        project_id = self.config.active_font_project_id
        try:
            project = self.font_projects.get(project_id)
            manifest_path, glyphs_dir = self.font_projects.dataset_paths(project_id)
            output_dir, version = self.font_projects.generation_directory(project_id)
        except Exception as exc:
            self.main_window.show_font_error(str(exc))
            return

        try:
            self.font_process, self.font_result_queue, self.font_cancel_event = start_font_worker(
                manifest_path=str(manifest_path),
                glyphs_dir=str(glyphs_dir),
                output_dir=str(output_dir),
                font_name=project["project_name"],
                build_otf=True,
            )
            self.font_state = "GENERATING"
            self.font_generation_project_id = project_id
            self.font_generation_version = version
            self.main_window.update_font_status("Starting font generator...", 0.05)
            logging.info("Started font generation worker process (pid=%s)", self.font_process.pid)
        except Exception as exc:
            logging.exception("Failed to start font worker")
            self.main_window.show_font_error(f"Could not start font generator: {exc}")

    @Slot()
    def cancel_font_generation(self) -> None:
        if self.font_cancel_event:
            self.font_cancel_event.set()
        self.finish_font_worker(terminate=True)
        if self.font_generation_project_id and self.font_generation_version:
            self.font_projects.discard_generation_directory(
                self.font_generation_project_id, self.font_generation_version)
        self.font_state = "IDLE"
        self.main_window.show_font_cancelled()
        logging.info("Font generation was cancelled by user")

    def poll_font(self) -> None:
        process, results = self.font_process, self.font_result_queue
        if not process or not results:
            return
        try:
            message = results.get_nowait()
        except queue.Empty:
            if self.font_state == "GENERATING" and not process.is_alive():
                self.finish_font_worker()
                self.font_state = "IDLE"
                self.main_window.show_font_error("The font generator process stopped unexpectedly.")
            return

        kind = message[0]
        if kind == "progress":
            msg, pct = message[1], message[2]
            self.main_window.update_font_status(msg, pct)
            return

        self.finish_font_worker()
        self.font_state = "IDLE"

        if kind == "cancelled":
            self.font_projects.discard_generation_directory(
                self.font_generation_project_id, self.font_generation_version)
            self.main_window.show_font_cancelled()
        elif kind == "error":
            self.font_projects.discard_generation_directory(
                self.font_generation_project_id, self.font_generation_version)
            err = message[1]
            self.main_window.show_font_error(err)
            logging.error("Font generation error: %s", err)
        elif kind == "success":
            data = message[1]
            data.update({"project_id": self.font_generation_project_id, "version": self.font_generation_version})
            self.font_projects.record_generation(self.font_generation_project_id, data)
            self._refresh_font_projects()
            if self.config.active_font_project_id == self.font_generation_project_id:
                self.main_window.show_font_result(data)
            count = data.get("glyph_count", 0)
            import datetime
            ts_str = datetime.datetime.now().strftime("%b %d, %H:%M")
            entry = f"{self.font_generation_project_id} v{self.font_generation_version:03d} ({count} glyphs) - {ts_str}"
            # Font history is deliberately project-local; global history is not
            # used for generated-font records.
            logging.info("Font generation completed successfully: %s", entry)

    @Slot()
    def download_ttf(self) -> None:
        ttf_path = Path(self.main_window.font_page._ttf_path or "")
        if not ttf_path.exists():
            self.main_window.show_font_error("Font has not been generated yet.")
            return
        dest, _ = QFileDialog.getSaveFileName(
            self.main_window, "Save Handwriting Font (TTF)", ttf_path.name, "TrueType Fonts (*.ttf)")
        if dest:
            try:
                shutil.copy2(str(ttf_path), dest)
                logging.info("Exported TTF font to %s", dest)
            except Exception as exc:
                self.main_window.show_font_error(f"Failed to save TTF font: {exc}")

    @Slot()
    def download_otf(self) -> None:
        otf_path = Path(self.main_window.font_page._otf_path or "")
        if not otf_path.exists():
            self.main_window.show_font_error("OTF font has not been generated yet.")
            return
        dest, _ = QFileDialog.getSaveFileName(
            self.main_window, "Save Handwriting Font (OTF)", otf_path.name, "OpenType Fonts (*.otf)")
        if dest:
            try:
                shutil.copy2(str(otf_path), dest)
                logging.info("Exported OTF font to %s", dest)
            except Exception as exc:
                self.main_window.show_font_error(f"Failed to save OTF font: {exc}")

    def finish_font_worker(self, terminate: bool = False) -> None:
        process = self.font_process
        if process:
            if terminate and process.is_alive():
                process.terminate()
            process.join(timeout=1)
            if process.is_alive():
                process.terminate()
                process.join(timeout=1)
        self.font_process = self.font_result_queue = self.font_cancel_event = None

    @Slot(bool)
    def handle_font_toggled(self, enabled: bool) -> None:
        self.config.enable_font = enabled
        self.config.save()
        logging.info("Create Font feature toggled: %s", enabled)
        if not enabled and self.font_state == "GENERATING":
            self.cancel_font_generation()

    # ── PDF generation backend ────────────────────────────────────────────────

    @Slot(str, str, str, object)
    def start_pdf_generation(self, title: str, content: str, selected_font_path: str = "", html_pages: list[str] | None = None) -> None:
        if not self.config.enable_files:
            self.main_window.show_pdf_error("Enable Create Files to generate PDF documents.")
            return
        if self.files_state != "IDLE":
            return

        font_path = Path(selected_font_path).resolve() if selected_font_path else None
        if font_path is None and not html_pages:
            legacy_font = (application_output_root() / "fonts" / "Verbum_Handwriting.ttf").resolve()
            font_path = legacy_font if legacy_font.is_file() else None
        if selected_font_path and (font_path is None or not font_path.is_file()):
            self.main_window.show_pdf_error("The selected handwriting font is missing. Choose a valid generated font version.")
            return
        if selected_font_path:
            try:
                matched = False
                for project in self.font_projects.list_projects():
                    project_id = project.get("project_id", "")
                    for record in self.font_projects.generation_history(project_id):
                        version = int(record.get("version", 0))
                        validated = self.font_projects.validated_generation(project_id, version)
                        if validated:
                            for key in ("ttf_path", "otf_path"):
                                raw_p = validated.get(key)
                                if raw_p and Path(raw_p).resolve() == font_path:
                                    matched = True
                                    break
                        if matched:
                            break
                    if matched:
                        break
                if not matched:
                    raise ValueError("Selected font is not a validated artifact of a known font project/version.")
            except Exception as exc:
                self.main_window.show_pdf_error(f"Personal font project validation failed: {exc}")
                return

        self.finish_pdf_worker(terminate=True)
        output_dir = application_output_root() / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        safe_title = "".join(c for c in title if c.isalnum() or c in ("-", "_")).strip() or "handwritten_document"
        out_pdf = str(output_dir / f"{safe_title}.pdf")

        try:
            self.pdf_process, self.pdf_result_queue, self.pdf_cancel_event = start_pdf_worker(
                content=content,
                title=title,
                font_path=str(font_path) if font_path else "",
                output_pdf_path=out_pdf,
                page_size="letter",
                html_pages=html_pages,
            )
            self.files_state = "GENERATING"
            self.main_window.update_pdf_status("Initializing document layout...", 0.1)
            logging.info("Started PDF generation worker process (pid=%s)", self.pdf_process.pid)
        except Exception as exc:
            logging.exception("Failed to start PDF worker")
            self.main_window.show_pdf_error(f"Could not start PDF generator: {exc}")

    @Slot()
    def cancel_pdf_generation(self) -> None:
        if self.pdf_cancel_event:
            self.pdf_cancel_event.set()
        self.finish_pdf_worker(terminate=True)
        self.files_state = "IDLE"
        self.main_window.show_pdf_cancelled()
        logging.info("PDF generation was cancelled by user")

    def poll_pdf(self) -> None:
        process, results = self.pdf_process, self.pdf_result_queue
        if not process or not results:
            return
        try:
            message = results.get_nowait()
        except queue.Empty:
            if self.files_state == "GENERATING" and not process.is_alive():
                self.finish_pdf_worker()
                self.files_state = "IDLE"
                self.main_window.show_pdf_error("The PDF generator process stopped unexpectedly.")
            return

        kind = message[0]
        if kind == "progress":
            msg, pct = message[1], message[2]
            self.main_window.update_pdf_status(msg, pct)
            return

        self.finish_pdf_worker()
        self.files_state = "IDLE"

        if kind == "cancelled":
            self.main_window.show_pdf_cancelled()
        elif kind == "error":
            err = message[1]
            self.main_window.show_pdf_error(err)
            logging.error("PDF generation error: %s", err)
        elif kind == "success":
            data = message[1]
            self.last_generated_pdf_path = data.get("pdf_path", "")
            self.main_window.show_pdf_result(data)
            pages = data.get("page_count", 1)
            pdf_name = Path(self.last_generated_pdf_path).name if self.last_generated_pdf_path else "document.pdf"
            import datetime
            ts_str = datetime.datetime.now().strftime("%b %d, %H:%M")
            entry = f"{pdf_name} ({pages} page{'s' if pages > 1 else ''}) - {ts_str}"
            self.config.add_files_history(entry)
            self.main_window.files_page.populate_history(
                self.config.files_history, self.main_window.copy_requested.emit)
            logging.info("PDF generation completed successfully: %s", entry)

    @Slot()
    def download_pdf(self) -> None:
        pdf_path = self.last_generated_pdf_path or str(application_output_root() / "output" / "test_document.pdf")
        if not Path(pdf_path).exists():
            self.main_window.show_pdf_error("PDF document has not been generated yet.")
            return
        default_name = Path(pdf_path).name
        dest, _ = QFileDialog.getSaveFileName(
            self.main_window, "Save PDF Document", default_name, "PDF Documents (*.pdf)")
        if dest:
            try:
                shutil.copy2(pdf_path, dest)
                logging.info("Exported PDF document to %s", dest)
            except Exception as exc:
                self.main_window.show_pdf_error(f"Failed to save PDF document: {exc}")

    @Slot()
    def open_pdf(self) -> None:
        pdf_path = self.last_generated_pdf_path or str(application_output_root() / "output" / "test_document.pdf")
        if not Path(pdf_path).exists():
            self.main_window.show_pdf_error("PDF document not found.")
            return
        try:
            QDesktopServices.openUrl(QUrl.fromLocalFile(pdf_path))
            logging.info("Opened PDF in system viewer: %s", pdf_path)
        except Exception as exc:
            self.main_window.show_pdf_error(f"Could not open PDF viewer: {exc}")

    def finish_pdf_worker(self, terminate: bool = False) -> None:
        process = self.pdf_process
        if process:
            if terminate and process.is_alive():
                process.terminate()
            process.join(timeout=1)
            if process.is_alive():
                process.terminate()
                process.join(timeout=1)
        self.pdf_process = self.pdf_result_queue = self.pdf_cancel_event = None

    @Slot(bool)
    def handle_files_toggled(self, enabled: bool) -> None:
        self.config.enable_files = enabled
        self.config.save()
        logging.info("Create Files feature toggled: %s", enabled)
        if not enabled and self.files_state == "GENERATING":
            self.cancel_pdf_generation()

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
        self.finish_translation_worker(terminate=True)
        self.finish_font_worker(terminate=True)
        self.finish_pdf_worker(terminate=True)
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
