"""
translation_worker.py — Long-lived worker subprocess for local translation jobs.

Maintains the loaded translation model in memory across translation requests
while the Translation feature is ON, preventing repetitive reload latency.
Releases model and shuts down cleanly when Translation is toggled OFF.

Protocol:
Commands (sent via commands queue):
  ("translate", request_id, text, source_lang)
  ("install", request_id)  # explicit, user-initiated one-time setup
  ("unload",)
  ("shutdown",)

Results (sent via results queue):
  ("status", request_id, kind, message)
  ("result", request_id, "ok", translated_text, source_lang, source_name)
  ("result", request_id, "error", message)
  ("result", request_id, "cancelled")
  ("result", request_id, "installed")
  ("result", request_id, "model_missing", message)
"""
from __future__ import annotations

import logging
import multiprocessing as mp
import queue
import traceback
import errno

log = logging.getLogger(__name__)


def _install_error(exc: Exception) -> tuple[str, str]:
    """Return a stable error code and safe recovery text for model setup."""
    text = str(exc).lower()
    if isinstance(exc, PermissionError) or "access is denied" in text or "permission" in text:
        return "PERMISSION_ERROR", "Verbum cannot write to the translation model directory."
    if isinstance(exc, OSError) and getattr(exc, "errno", None) == errno.ENOSPC:
        return "DISK_SPACE_ERROR", "Not enough disk space to install the translation model."
    if "no space" in text or "disk full" in text or "not enough space" in text:
        return "DISK_SPACE_ERROR", "Not enough disk space to install the translation model."
    if exc.__class__.__name__ == "TranslationModelValidationError":
        return "VALIDATION_FAILED", "The translation model download is incomplete or corrupted."
    if "connect" in text or "network" in text or "timeout" in text or "http" in text:
        return "NETWORK_ERROR", "Could not download the translation model."
    return "INITIALIZATION_FAILED", "The translation model was installed but could not be initialized."


def _run(commands: mp.Queue, results: mp.Queue, cancel_event: mp.Event) -> None:
    """Worker process loop: caches model in memory and executes translation jobs."""
    provider = None
    detector = None

    def cancelled() -> bool:
        return cancel_event.is_set()

    try:
        from .translation import (
            LanguageDetector,
            TranslationModelProvider,
            TranslationModelNotInstalledError,
            TranslationModelValidationError,
            SUPPORTED_LANGUAGES,
            normalise_lang,
            is_model_downloaded,
        )

        detector = LanguageDetector()
        provider = TranslationModelProvider()

        while True:
            try:
                cmd = commands.get()
            except (EOFError, OSError):
                break

            if cmd is None or cmd[0] == "shutdown":
                if provider and provider.is_loaded:
                    provider.unload()
                break

            if cmd[0] == "unload":
                if provider and provider.is_loaded:
                    provider.unload()
                continue

            if cmd[0] == "install":
                _, request_id = cmd

                def install_status(kind: str, msg: str) -> None:
                    results.put(("status", request_id, kind, msg))

                try:
                    install_status("installing", "Preparing translation model setup…")
                    provider.install(lambda msg: install_status("installing", msg))
                    install_status("loading", "Loading translation model...")
                    provider.load(lambda msg: install_status("loading", msg), device="auto")
                    results.put(("result", request_id, "installed"))
                except Exception as exc:
                    code, user_message = _install_error(exc)
                    technical = traceback.format_exc()
                    log.error("Translation model installation failed [%s]:\n%s", code, technical)
                    # Keep diagnostics out of the UI, but forward them to the
                    # controller's configured application log.
                    results.put(("result", request_id, "error", user_message, code, technical))
                continue

            if cmd[0] != "translate":
                continue

            _, request_id, text, source_lang = cmd

            def status(kind: str, msg: str) -> None:
                results.put(("status", request_id, kind, msg))

            text = text.strip()
            if not text:
                results.put(("result", request_id, "error", "Input text is empty."))
                continue

            if cancelled():
                results.put(("result", request_id, "cancelled"))
                continue

            try:
                # ── Step 1: Resolve Source Language ───────────────────────────
                resolved_lang = ""
                resolved_name = ""

                if source_lang in ("", "auto"):
                    status("detecting", "Detecting language…")
                    detection = detector.detect(text)

                    if cancelled():
                        results.put(("result", request_id, "cancelled"))
                        continue

                    if not detection.confident:
                        results.put((
                            "result",
                            request_id,
                            "error",
                            "Language could not be identified confidently. "
                            "Please select the source language manually.",
                        ))
                        continue

                    resolved_lang = detection.code
                    resolved_name = detection.name
                    status("detecting", f"Detected: {resolved_name}")
                else:
                    resolved_lang = normalise_lang(source_lang)
                    resolved_name = SUPPORTED_LANGUAGES.get(resolved_lang, resolved_lang.upper())

                # ── Step 2: English Pass-through ──────────────────────────────
                if resolved_lang in ("en", "eng"):
                    results.put(("result", request_id, "ok", text, "en", "English"))
                    continue

                # ── Step 3: Verify Language Support ───────────────────────────
                if resolved_lang not in SUPPORTED_LANGUAGES:
                    results.put((
                        "result",
                        request_id,
                        "error",
                        f"The language '{resolved_name}' is not supported by the installed model.",
                    ))
                    continue

                if cancelled():
                    results.put(("result", request_id, "cancelled"))
                    continue

                # ── Step 4: Lazy Load Model (Cached across requests) ──────────
                if not provider.is_loaded:
                    if not is_model_downloaded():
                        results.put((
                            "result", request_id, "model_missing",
                            "Translation model is not installed. Select Install model to set it up once.",
                        ))
                        continue
                    status("loading", "Loading translation model into memory…")
                    provider.load(
                        progress_cb=lambda msg: status("loading", msg),
                        device="auto",
                    )

                if cancelled():
                    results.put(("result", request_id, "cancelled"))
                    continue

                # ── Step 5: Translate ─────────────────────────────────────────
                status("translating", f"Translating {resolved_name} → English…")

                translated = provider.translate(
                    text=text,
                    source_lang=resolved_lang,
                    target_lang="en",
                    cancelled=cancelled,
                )

                if cancelled():
                    results.put(("result", request_id, "cancelled"))
                    continue

                results.put(("result", request_id, "ok", translated, resolved_lang, resolved_name))

            except TranslationModelNotInstalledError as exc:
                results.put(("result", request_id, "model_missing", str(exc)))
            except InterruptedError:
                results.put(("result", request_id, "cancelled"))
            except Exception as exc:
                tb = traceback.format_exc()
                log.error("Translation job failed:\n%s", tb)
                results.put(("result", request_id, "error",
                             "Translation failed. Please try again."))

    except Exception:
        tb = traceback.format_exc()
        log.error("Translation worker process failed:\n%s", tb)
    finally:
        if provider and provider.is_loaded:
            try:
                provider.unload()
            except Exception:
                pass


def start_translation_worker() -> tuple[mp.Process, mp.Queue, mp.Queue, mp.Event]:
    """
    Launch long-running translation worker subprocess.
    Returns (process, commands_queue, results_queue, cancel_event).
    """
    commands: mp.Queue = mp.Queue()
    results: mp.Queue = mp.Queue()
    cancel_event: mp.Event = mp.Event()

    process = mp.Process(
        target=_run,
        args=(commands, results, cancel_event),
        daemon=True,
    )
    process.start()
    return process, commands, results, cancel_event
