"""
Multiprocessing worker for non-blocking font generation.
"""
from __future__ import annotations

import logging
import multiprocessing as mp
import os
from pathlib import Path
from typing import Tuple

from .font_generator import create_handwriting_font, render_font_preview_specimen


def _font_worker_entry(
    manifest_path: str,
    glyphs_dir: str,
    output_dir: str,
    font_name: str,
    build_otf: bool,
    result_queue: mp.Queue,
    cancel_event: mp.Event
) -> None:
    """Worker process function for font generation."""
    try:
        def progress(msg: str, pct: float) -> None:
            if cancel_event.is_set():
                raise InterruptedError("Font generation cancelled by user.")
            result_queue.put(("progress", msg, pct))

        res = create_handwriting_font(
            manifest_path=manifest_path,
            glyphs_dir=glyphs_dir,
            output_dir=output_dir,
            font_name=font_name,
            build_otf=build_otf,
            progress_cb=progress
        )

        if cancel_event.is_set():
            result_queue.put(("cancelled", "Operation was cancelled."))
            return

        if not res.success:
            result_queue.put(("error", res.error_message or "Unknown font generation error."))
            return

        # Render preview specimen image
        specimen_path = os.path.join(output_dir, "specimen_preview.png")
        try:
            render_font_preview_specimen(res.ttf_path, specimen_path)
        except Exception:
            specimen_path = None

        result_queue.put((
            "success",
            {
                "ttf_path": res.ttf_path,
                "otf_path": res.otf_path,
                "glyph_count": res.glyph_count,
                "mapped_chars": res.mapped_characters,
                "specimen_path": specimen_path,
                "validation_passed": res.validation_passed,
                "validation_details": res.validation_details,
            }
        ))
    except InterruptedError:
        result_queue.put(("cancelled", "Font generation was cancelled."))
    except Exception as exc:
        logging.exception("Font worker process error")
        result_queue.put(("error", str(exc)))


def start_font_worker(
    manifest_path: str,
    glyphs_dir: str,
    output_dir: str,
    font_name: str = "Verbum Handwriting",
    build_otf: bool = True
) -> Tuple[mp.Process, mp.Queue, mp.Event]:
    """
    Spawns an isolated background subprocess for font generation.
    Returns: (process, result_queue, cancel_event)
    """
    result_queue = mp.Queue()
    cancel_event = mp.Event()

    process = mp.Process(
        target=_font_worker_entry,
        args=(manifest_path, glyphs_dir, output_dir, font_name, build_otf, result_queue, cancel_event),
        daemon=True
    )
    process.start()
    return process, result_queue, cancel_event
