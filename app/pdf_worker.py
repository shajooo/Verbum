"""
Multiprocessing worker for non-blocking PDF generation using custom handwriting font.
"""
from __future__ import annotations

import logging
import multiprocessing as mp
from typing import Tuple

from .pdf_generator import generate_handwritten_pdf
from .rich_pdf_export import generate_rich_pdf


def _pdf_worker_entry(
    content: str,
    title: str,
    font_path: str,
    output_pdf_path: str,
    page_size: str,
    result_queue: mp.Queue,
    cancel_event: mp.Event,
    html_pages: list[str] | None = None,
) -> None:
    """Worker process function for PDF generation."""
    try:
        if cancel_event.is_set():
            result_queue.put(("cancelled", "Operation was cancelled."))
            return

        result_queue.put(("progress", "Initializing document layout...", 0.2))

        if cancel_event.is_set():
            result_queue.put(("cancelled", "Operation was cancelled."))
            return

        result_queue.put(("progress", "Embedding handwriting font...", 0.5))

        if html_pages:
            res = generate_rich_pdf(html_pages, title, font_path, output_pdf_path)
        else:
            res = generate_handwritten_pdf(
                content=content,
                title=title,
                font_path=font_path,
                output_pdf_path=output_pdf_path,
                page_size=page_size,
                generate_preview=True
            )

        if cancel_event.is_set():
            result_queue.put(("cancelled", "Operation was cancelled."))
            return

        if not res.success:
            result_queue.put(("error", res.error_message or "Unknown PDF generation error."))
            return

        result_queue.put((
            "success",
            {
                "pdf_path": res.pdf_path,
                "page_count": res.page_count,
                "preview_image_path": res.preview_image_path,
                "unsupported_chars": res.unsupported_chars,
                "validation_passed": res.validation_passed,
                "validation_details": res.validation_details,
            }
        ))
    except Exception as exc:
        logging.exception("PDF worker process error")
        result_queue.put(("error", str(exc)))


def start_pdf_worker(
    content: str,
    title: str,
    font_path: str,
    output_pdf_path: str,
    page_size: str = "letter",
    html_pages: list[str] | None = None,
) -> Tuple[mp.Process, mp.Queue, mp.Event]:
    """
    Spawns an isolated background subprocess for PDF generation.
    Returns: (process, result_queue, cancel_event)
    """
    result_queue = mp.Queue()
    cancel_event = mp.Event()

    process = mp.Process(
        target=_pdf_worker_entry,
        args=(content, title, font_path, output_pdf_path, page_size, result_queue, cancel_event, html_pages),
        daemon=True
    )
    process.start()
    return process, result_queue, cancel_event
