"""
Short-lived extraction worker process.

One process is spawned per extraction job so that the entire job
can be cancelled cleanly either by:
  - Soft cancel: cancel_event.set()  (checked between OCR calls / PDF pages)
  - Hard cancel: process.terminate() (immediate, always works)

Result protocol (put on results queue):
  ("status", "preparing", message)         -- detecting file type
  ("status", "loading_model", message)     -- OCR engine initialising
  ("status", "extracting", message)        -- actively processing
  ("result", "ok",    text, output_path, input_kind)
  ("result", "error", message)
"""

from __future__ import annotations

import multiprocessing as mp
import traceback

from .extraction import (
    ExtractionError, ExtractionManager, InputDetector, ImageOCR,
    SVGExtractor, PDFTextExtractor, DOCXExtractor, TextProcessor, TextFileWriter,
)


def _run(path: str, results: mp.Queue, cancel_event: mp.Event) -> None:
    try:
        # Step 1: detect file type (fast — no model needed)
        results.put(("status", "preparing", "Detecting file type\u2026"))
        detector = InputDetector()
        detected = detector.detect(path)

        if cancel_event.is_set():
            results.put(("result", "error", "Extraction was cancelled."))
            return

        processor = TextProcessor()
        writer = TextFileWriter()
        image_ocr = ImageOCR()

        if detected.kind == "raster":
            # Raster images always need OCR
            results.put(("status", "loading_model", "Initialising OCR engine\u2026"))
            text = image_ocr.extract_path(detected.path, cancelled=cancel_event.is_set)

        elif detected.kind == "svg":
            # SVGs may or may not need OCR
            results.put(("status", "extracting", "Reading SVG content\u2026"))
            # SVGExtractor handles both text-only and rasterised+OCR paths internally
            # Pass a status callback so we can update if OCR becomes needed
            text = SVGExtractor(image_ocr).extract(detected.path, cancelled=cancel_event.is_set)

        elif detected.kind == "pdf":
            results.put(("status", "extracting", "Reading PDF\u2026"))
            text = PDFTextExtractor(image_ocr).extract(
                detected.path,
                cancelled=cancel_event.is_set,
                on_ocr_needed=lambda: results.put(("status", "loading_model", "Initialising OCR engine for scanned pages\u2026")),
            )

        elif detected.kind == "docx":
            # DOCX never needs OCR
            results.put(("status", "extracting", "Reading Word document\u2026"))
            text = DOCXExtractor().extract(detected.path, cancelled=cancel_event.is_set)

        else:
            from .extraction import UnsupportedInputError
            raise UnsupportedInputError(f"Unsupported input kind: {detected.kind}")

        if cancel_event.is_set():
            results.put(("result", "error", "Extraction was cancelled."))
            return

        text = processor.normalize(text)
        if not text:
            results.put(("result", "error", "No printed or selectable text was found in this file."))
            return

        output_path = writer.write(detected.path, text)
        results.put(("result", "ok", text, str(output_path), detected.kind))

    except ExtractionError as exc:
        results.put(("result", "error", str(exc)))
    except Exception:
        tb = traceback.format_exc()
        results.put(("result", "error", f"Extraction worker failed unexpectedly:\n{tb}"))


def start_extraction_worker(path: str) -> tuple[mp.Process, mp.Queue, mp.Event]:
    """
    Spawn one short-lived process per extraction job.

    Returns (process, results_queue, cancel_event).

    Soft cancel:  cancel_event.set() — checked between pages/images
    Hard cancel:  process.terminate() — immediate
    Collect:      results_queue.get(timeout=N)
    """
    results: mp.Queue = mp.Queue()
    cancel_event: mp.Event = mp.Event()
    process = mp.Process(target=_run, args=(path, results, cancel_event), daemon=True)
    process.start()
    return process, results, cancel_event
