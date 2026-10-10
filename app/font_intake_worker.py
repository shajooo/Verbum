"""Non-blocking Phase 1 sample ingestion. It never writes into verified datasets."""
from __future__ import annotations

import multiprocessing as mp
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .font_projects import FontProjectStore
from .custom_character_ocr import CustomCharacterOCR
from tools.pipeline.cell_extractor import CellExtractor
from tools.pipeline.config import get_template_for_sheet
from tools.pipeline.grid_detector import GridDetector
from tools.pipeline.image_io import ImageLoader
from tools.pipeline.normalizer import GlyphNormalizer
from tools.pipeline.page_detector import PageDetector
from tools.pipeline.quality_scorer import QualityScorer

SUPPORTED = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif", ".pdf"}


def _emit(queue: mp.Queue, state: str, **payload: Any) -> None:
    queue.put((state, payload))


def _load(path: Path) -> np.ndarray:
    if path.suffix.lower() == ".pdf":
        import fitz
        with fitz.open(path) as pdf:
            if not pdf.page_count:
                raise ValueError("The PDF has no pages.")
            pix = pdf[0].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            array = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)
            return cv2.cvtColor(array, cv2.COLOR_RGB2BGR)
    image, _ = ImageLoader.load_image(path)
    return image


def _classify(image: np.ndarray) -> tuple[str, float, dict[str, Any]]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape[:2]
    if min(h, w) < 24:
        return "UNCERTAIN", 0.0, {"reason": "Image is too small to analyze."}
    edges = cv2.Canny(gray, 50, 150)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=max(35, min(h, w) // 5),
                            minLineLength=max(30, min(h, w) // 5), maxLineGap=12)
    horizontal = vertical = 0
    if lines is not None:
        for x1, y1, x2, y2 in lines.reshape(-1, 4):
            angle = abs(np.degrees(np.arctan2(y2 - y1, x2 - x1)))
            if angle < 8 or angle > 172: horizontal += 1
            if 82 < angle < 98: vertical += 1
    grid_strength = min(horizontal, vertical)
    if grid_strength >= 5:
        return "STRUCTURED_GLYPH_SHEET", min(0.95, 0.55 + grid_strength / 30), {
            "horizontal_lines": horizontal, "vertical_lines": vertical, "template_recognized": False,
        }
    _, ink = cv2.threshold(gray, 220, 255, cv2.THRESH_BINARY_INV)
    components, _, stats, _ = cv2.connectedComponentsWithStats(ink)
    areas = stats[1:, cv2.CC_STAT_AREA] if components > 1 else np.array([])
    substantial = int(np.sum(areas > 18))
    ink_ratio = float(np.count_nonzero(ink)) / float(h * w)
    bbox = cv2.boundingRect(ink) if np.count_nonzero(ink) else (0, 0, 0, 0)
    bbox_ratio = (bbox[2] * bbox[3]) / float(h * w) if h * w else 0.0
    if 1 <= substantial <= 4 and ink_ratio < 0.30 and bbox_ratio < 0.72:
        return "ISOLATED_GLYPH", max(0.60, min(0.94, 0.94 - 0.04 * max(0, substantial - 1))), {"components": substantial}
    if substantial >= 6 or ink_ratio >= 0.08:
        return "HANDWRITTEN_NOTE", min(0.92, 0.55 + min(substantial, 25) / 80 + min(ink_ratio, .2)), {"components": substantial}
    return "UNCERTAIN", 0.45, {"reason": "No reliable grid, isolated glyph, or handwriting-page pattern was found."}


def _extract_known_sheet(
    image: np.ndarray, source_name: str, root: Path, sample_id: str, queue: mp.Queue, cancel: mp.Event,
) -> tuple[list[dict[str, Any]], dict[str, int], str]:
    """Run the established Step 2 primitives, but stage rather than publish glyphs."""
    template = get_template_for_sheet(source_name)
    _emit(queue, "progress", message="Correcting page orientation and perspective…")
    rectified, _ = PageDetector.rectify_sheet(image, template.deskew_angle)
    if cancel.is_set():
        return [], {"GOOD": 0, "REVIEW": 0, "REJECT": 0}, template.template_id
    _emit(queue, "progress", message="Detecting grid and extracting glyph candidates…")
    cells, _ = GridDetector.detect_grid(rectified, template)
    normalizer = GlyphNormalizer()
    candidates: list[dict[str, Any]] = []
    counts = {"GOOD": 0, "REVIEW": 0, "REJECT": 0}
    for index, cell in enumerate(cells):
        if cancel.is_set():
            break
        extracted = CellExtractor.extract_glyph_from_cell(rectified, cell)
        norm_gray, norm_bin, norm_meta = normalizer.normalize(extracted)
        assessment = QualityScorer.assess_glyph(extracted, norm_gray, norm_bin, norm_meta)
        counts[assessment.status] += 1
        candidate_id = f"{sample_id}_{index:03d}"
        candidate_path = root / "dataset" / "staging" / "candidates" / f"{candidate_id}.png"
        cv2.imwrite(str(candidate_path), norm_gray)
        candidates.append({
            "candidate_id": candidate_id,
            "candidate_path": str(candidate_path),
            "character": cell.char_meta.char,
            "category": cell.char_meta.category,
            "quality": assessment.status,
            "quality_score": assessment.score,
            "issues": assessment.issues,
            "review_state": "PENDING",
            "row": cell.row_idx,
            "column": cell.col_idx,
        })
    _emit(queue, "progress", message="Quality checking complete. Ready for review.")
    return candidates, counts, template.template_id


NOTE_CHARACTERS = set(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.,:-()[]{}"
)


def _ocr_note_words(image: np.ndarray) -> list[dict[str, Any]]:
    """Return OCR word/line boxes while keeping this worker fully local."""
    from PIL import Image, ImageEnhance, ImageOps

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    pil = Image.fromarray(gray)
    scale = 1.0
    if min(pil.size) < 900:
        scale = min(3.0, 900 / float(min(pil.size)))
        pil = pil.resize(
            (round(pil.width * scale), round(pil.height * scale)),
            Image.Resampling.LANCZOS,
        )
    pil = ImageOps.autocontrast(pil)
    pil = ImageEnhance.Contrast(pil).enhance(1.20)

    from rapidocr_onnxruntime import RapidOCR
    engine = RapidOCR()
    results, _elapsed = engine(np.asarray(pil.convert("L")))
    words: list[dict[str, Any]] = []
    for item in results or []:
        if len(item) < 2 or not item[1]:
            continue
        box = item[0] or []
        text = str(item[1]).strip()
        if not box or not text:
            continue
        try:
            confidence = float(item[2]) if len(item) >= 3 else 0.0
        except (TypeError, ValueError):
            confidence = 0.0
        xs = [int(round(point[0])) for point in box]
        ys = [int(round(point[1])) for point in box]
        words.append({
            "text": text,
            "confidence": confidence,
            "x1": max(0, round(min(xs) / scale)),
            "y1": max(0, round(min(ys) / scale)),
            "x2": max(0, round(max(xs) / scale)),
            "y2": max(0, round(max(ys) / scale)),
        })
    words.sort(key=lambda item: (item["y1"], item["x1"]))
    return words


def _contextualize_note_words(image: np.ndarray, words: list[dict[str, Any]], queue: mp.Queue) -> list[dict[str, Any]]:
    """Use the custom word model plus sentence context to correct uncertain OCR words."""
    if not words:
        return words
    try:
        from .font_word_ocr import WordOCR
        from .context_word_resolver import ContextWordResolver
        model_path = Path(__file__).resolve().parents[1] / "models" / "word_ocr" / "word_crnn.pt"
        context_path = Path(__file__).resolve().parents[1] / "models" / "context_ocr"
        if not model_path.is_file() or not context_path.is_dir():
            return words
        recognizer = WordOCR(model_path, device="cpu")
        resolver = ContextWordResolver(context_path, device="cpu")
    except Exception:
        return words

    from PIL import Image
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    provisional = ["".join(ch.lower() for ch in str(item["text"]) if ch.isalpha()) for item in words]
    _emit(queue, "progress", message="Using sentence context to resolve uncertain handwritten words…")
    for index, word in enumerate(words):
        x1, y1, x2, y2 = word["x1"], word["y1"], word["x2"], word["y2"]
        if x2 <= x1 or y2 <= y1:
            continue
        crop = gray[y1:y2, x1:x2]
        if crop.size == 0:
            continue
        try:
            prediction = recognizer.predict(Image.fromarray(crop))
            model_text = str(prediction["text"]).lower()
            model_confidence = float(prediction["confidence"])
        except Exception:
            model_text = ""
            model_confidence = 0.0

        raw_text = str(word["text"]).lower()
        primary = raw_text or model_text
        candidates = set(resolver.candidate_words(raw_text, limit=24))
        candidates.update(resolver.candidate_words(model_text, limit=24))
        if raw_text.isalpha():
            candidates.add(raw_text)
        if model_text.isalpha():
            candidates.add(model_text)
        left = provisional[max(0, index - 8):index]
        right = provisional[index + 1:index + 9]
        candidates = [c for c in candidates if c.isalpha()]
        if candidates:
            resolved = resolver.resolve(primary, left, right, candidates)
            word["raw_ocr_text"] = word["text"]
            word["word_model_text"] = model_text
            word["word_model_confidence"] = round(model_confidence, 3)
            word["context_text"] = resolved["word"]
            word["context_confidence"] = round(float(resolved["confidence"]), 3)
            word["context_candidates"] = resolved["candidates"][:5]
            if resolved["word"]:
                word["text"] = resolved["word"]
    return words


def _segment_word_crop(gray: np.ndarray, character_count: int) -> tuple[list[np.ndarray], list[str]]:
    """Split one OCR word crop into character candidates using vertical ink valleys."""
    if character_count <= 0:
        return [], ["NO_OCR_CHARACTERS"]

    ink = cv2.threshold(gray, 220, 255, cv2.THRESH_BINARY_INV)[1]
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    ink = cv2.morphologyEx(ink, cv2.MORPH_OPEN, kernel)
    ys, xs = np.where(ink > 0)
    if len(xs) == 0:
        return [], ["NO_INK"]

    x1, x2 = int(xs.min()), int(xs.max() + 1)
    y1, y2 = int(ys.min()), int(ys.max() + 1)
    crop = gray[y1:y2, x1:x2]
    if crop.size == 0:
        return [], ["EMPTY_CROP"]

    if character_count == 1:
        return [crop], []

    profile = np.count_nonzero(ink[y1:y2, x1:x2], axis=0).astype(np.float32)
    profile = cv2.GaussianBlur(profile.reshape(1, -1), (1, 9), 0).ravel()
    width = len(profile)

    # Pick low-ink valleys near the expected character boundaries.
    cuts: list[int] = []
    issues: list[str] = []
    for i in range(1, character_count):
        expected = int(round(i * width / character_count))
        radius = max(3, width // max(12, character_count * 3))
        lo = max(2, expected - radius)
        hi = min(width - 2, expected + radius)
        region = profile[lo:hi + 1]
        cut = lo + int(np.argmin(region)) if region.size else expected
        cuts.append(cut)

    cuts = sorted(set(cuts))
    if len(cuts) != character_count - 1:
        issues.append("AMBIGUOUS_CHARACTER_BOUNDARIES")

    boundaries = [0, *cuts, width]
    segments: list[np.ndarray] = []
    for left, right in zip(boundaries, boundaries[1:]):
        if right - left < 2:
            issues.append("TINY_CHARACTER_SEGMENT")
            continue
        segment = crop[:, left:right]
        if np.count_nonzero(cv2.threshold(segment, 220, 255, cv2.THRESH_BINARY_INV)[1]) < 8:
            issues.append("LOW_INK_CHARACTER_SEGMENT")
        segments.append(segment)

    if len(segments) != character_count:
        issues.append(f"SEGMENT_COUNT_{len(segments)}_EXPECTED_{character_count}")
    return segments, issues


def _normalize_note_crop(gray: np.ndarray, target_size: int = 128, margin: int = 16) -> tuple[np.ndarray, dict[str, Any]]:
    """Normalize one note-derived character crop into the same canvas used by glyph generation."""
    mask = cv2.threshold(gray, 220, 255, cv2.THRESH_BINARY_INV)[1]
    ys, xs = np.where(mask > 0)
    if len(xs) == 0:
        return np.full((target_size, target_size), 255, dtype=np.uint8), {"ink_pixels": 0}

    x1, x2 = int(xs.min()), int(xs.max() + 1)
    y1, y2 = int(ys.min()), int(ys.max() + 1)
    content = gray[y1:y2, x1:x2]
    max_dim = max(content.shape[:2])
    scale = (target_size - 2 * margin) / float(max_dim)
    new_w = max(1, int(round(content.shape[1] * scale)))
    new_h = max(1, int(round(content.shape[0] * scale)))
    resized = cv2.resize(
        content, (new_w, new_h),
        interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC,
    )
    canvas = np.full((target_size, target_size), 255, dtype=np.uint8)
    ox = margin + (target_size - 2 * margin - new_w) // 2
    oy = margin + (target_size - 2 * margin - new_h) // 2
    canvas[oy:oy + new_h, ox:ox + new_w] = resized
    return canvas, {
        "ink_pixels": int(np.count_nonzero(mask)),
        "norm_w": new_w,
        "norm_h": new_h,
        "aspect_ratio": round(content.shape[1] / float(max(1, content.shape[0])), 3),
    }


def _extract_note_candidates(
    image: np.ndarray,
    root: Path,
    sample_id: str,
    queue: mp.Queue,
    cancel: mp.Event,
) -> tuple[list[dict[str, Any]], str, dict[str, int], list[str]]:
    """OCR-align a generic note into reviewable per-character glyph candidates."""
    _emit(queue, "progress", message="Reading handwritten lines locally…")
    words = _ocr_note_words(image)
    if cancel.is_set():
        return [], "", {"GOOD": 0, "REVIEW": 0, "REJECT": 0}, []
    words = _contextualize_note_words(image, words, queue)
    if cancel.is_set():
        return [], "", {"GOOD": 0, "REVIEW": 0, "REJECT": 0}, []

    recognized_text = " ".join(item["text"] for item in words)
    candidates: list[dict[str, Any]] = []
    counts = {"GOOD": 0, "REVIEW": 0, "REJECT": 0}
    unsupported: list[str] = []
    from PIL import Image
    recognizer = CustomCharacterOCR(device="cpu")
    _emit(queue, "progress", message="Comparing extracted letters with the trained handwriting model…")

    for word_index, word in enumerate(words):
        text = "".join(ch for ch in word["text"] if ch in NOTE_CHARACTERS)
        unsupported.extend(ch for ch in word["text"] if ch not in NOTE_CHARACTERS and not ch.isspace())
        if not text:
            continue

        x1, y1, x2, y2 = word["x1"], word["y1"], word["x2"], word["y2"]
        if x2 <= x1 or y2 <= y1:
            continue
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        crop = gray[y1:y2, x1:x2]
        segments, split_issues = _segment_word_crop(crop, len(text))
        exact_split = len(segments) == len(text) and not split_issues

        for char_index, char in enumerate(text):
            if cancel.is_set():
                break
            segment = segments[char_index] if char_index < len(segments) else crop
            normalized, meta = _normalize_note_crop(segment)
            candidate_id = f"{sample_id}_w{word_index:03d}_c{char_index:02d}"
            candidate_path = root / "dataset" / "staging" / "candidates" / f"{candidate_id}.png"
            cv2.imwrite(str(candidate_path), normalized)

            prediction = recognizer.predict(Image.fromarray(normalized))
            predicted_char = prediction["character"]
            predicted_confidence = float(prediction["confidence"])
            issues = list(split_issues)
            if not exact_split:
                issues.append("OCR_ALIGNED_HEURISTIC_SPLIT")
            if word["confidence"] < 0.60:
                issues.append("LOW_OCR_CONFIDENCE")
            if predicted_char != char:
                issues.append("CUSTOM_OCR_DISAGREEMENT")
            if predicted_confidence < 0.75:
                issues.append("LOW_CUSTOM_OCR_CONFIDENCE")
            if len(predicted_char) != 1 or predicted_char not in NOTE_CHARACTERS:
                issues.append("CUSTOM_OCR_LABEL_NOT_IMPORTABLE")
                predicted_char = char
            label_agrees = predicted_char == char
            state = (
                "GOOD"
                if exact_split
                and word["confidence"] >= 0.85
                and predicted_confidence >= 0.75
                and label_agrees
                and meta.get("ink_pixels", 0) >= 20
                else "REVIEW"
            )
            counts[state] += 1
            quality_score = min(
                1.0,
                max(0.0, (word["confidence"] * 0.35) + (predicted_confidence * 0.65))
            )
            candidates.append({
                "candidate_id": candidate_id,
                "candidate_path": str(candidate_path),
                "character": predicted_char,
                "ocr_character": char,
                "custom_ocr_character": prediction["character"],
                "custom_ocr_confidence": round(predicted_confidence, 3),
                "custom_ocr_top_k": prediction["top_k"],
                "category": "user_added",
                "quality": state,
                "quality_score": round(quality_score, 3),
                "issues": sorted(set(issues)) or ["NONE"],
                "review_state": "PENDING",
                "source_word": word["text"],
                "ocr_confidence": round(word["confidence"], 3),
                "segmentation": "ocr_word_box_projection_plus_custom_character_ocr",
                "metadata": meta,
            })

    return candidates, recognized_text, counts, sorted(set(unsupported))


def _process(project_id: str, path_str: str, queue: mp.Queue, cancel: mp.Event,
             store_root: str | None = None) -> None:
    store = FontProjectStore(Path(store_root) if store_root else None)
    root = store.project_root(project_id)
    path = Path(path_str)
    if path.suffix.lower() not in SUPPORTED:
        raise ValueError("Unsupported sample type. Choose PNG, JPG, WEBP, BMP, TIFF, or PDF.")
    if not path.is_file():
        raise ValueError("The selected file no longer exists.")
    upload_id = uuid.uuid4().hex
    destination = root / "dataset" / "staging" / "uploads" / f"{upload_id}_{path.name}"
    _emit(queue, "progress", message="Copying sample into this font project…")
    shutil.copy2(path, destination)
    if cancel.is_set(): return
    _emit(queue, "progress", message="Analyzing sample…")
    image = _load(destination)  # validates real file contents, not just extension
    sample_type, confidence, details = _classify(image)
    result: dict[str, Any] = {"sample_id": upload_id, "project_id": project_id, "file_name": path.name,
        "file_size": destination.stat().st_size, "source_path": str(destination), "sample_type": sample_type,
        "confidence": round(confidence, 3), "classification_method": "heuristic_geometry_v1",
        "status": "READY_FOR_REVIEW", "details": details, "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "candidates": []}
    if sample_type == "STRUCTURED_GLYPH_SHEET":
        try:
            get_template_for_sheet(path.name)
        except ValueError:
            result["status"] = "TEMPLATE_REVIEW_REQUIRED"
            result["message"] = "Grid detected, but the template is not recognized. Labels will not be guessed."
        else:
            candidates, quality_counts, template_id = _extract_known_sheet(
                image, path.name, root, upload_id, queue, cancel,
            )
            result.update({
                "candidates": candidates,
                "template_id": template_id,
                "quality_counts": quality_counts,
                "status": "READY_FOR_REVIEW",
                "message": f"Recognized template '{template_id}'. Candidates are staged for review.",
                "extraction_method": "step2_page_grid_cell_normalize_quality_v1",
            })
    elif sample_type == "HANDWRITTEN_NOTE":
        candidates, recognized_text, quality_counts, unsupported = _extract_note_candidates(
            image, root, upload_id, queue, cancel,
        )
        _emit(queue, "progress", message=f"Storing {len(candidates)} extracted glyph(s) in this font project…")
        imported_count = store.import_note_glyphs(project_id, upload_id, candidates)
        result.update({
            "candidates": [],
            "recognized_text": recognized_text,
            "quality_counts": quality_counts,
            "unsupported_characters": unsupported,
            "imported_glyph_count": imported_count,
            "extraction_method": "ocr_word_box_projection_plus_custom_character_ocr_v2",
            "review_glyph_count": quality_counts.get("REVIEW", 0),
            "status": "IMPORTED",
        })
        if imported_count:
            result["message"] = (
                f"Handwritten note processed locally. {imported_count} glyph(s) were "
                f"stored directly in this font project's dataset."
            )
            if unsupported:
                result["message"] += " Some OCR characters were not eligible for glyph extraction."
        else:
            result["status"] = "REVIEW_REQUIRED"
            result["message"] = (
                "Handwritten note detected, but no usable OCR character candidates were found. "
                "Review the image or upload a clearer sample."
            )
    elif sample_type == "ISOLATED_GLYPH":
        _emit(queue, "progress", message="Preparing isolated glyph for review…")
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        _, mask = cv2.threshold(gray, 220, 255, cv2.THRESH_BINARY_INV)
        ys, xs = np.where(mask > 0)
        if len(xs) == 0:
            result.update({"sample_type": "UNCERTAIN", "status": "REVIEW_REQUIRED", "message": "No handwriting ink was found."})
        else:
            x1, x2, y1, y2 = xs.min(), xs.max(), ys.min(), ys.max()
            crop = gray[max(0, y1-6):y2+7, max(0, x1-6):x2+7]
            norm = cv2.resize(crop, (112, 112), interpolation=cv2.INTER_AREA)
            canvas = np.full((128, 128), 255, dtype=np.uint8); canvas[8:120, 8:120] = norm
            candidate = root / "dataset" / "staging" / "candidates" / f"{upload_id}.png"
            cv2.imwrite(str(candidate), canvas)
            result["candidates"] = [{"candidate_path": str(candidate), "character": "", "quality": "REVIEW",
                "issues": ["LABEL_CONFIRMATION_REQUIRED"], "review_state": "PENDING"}]
            result["message"] = "Isolated glyph prepared. Confirm its character before accepting it."
    else:
        result["status"] = "REVIEW_REQUIRED"
        result["message"] = "Sample type could not be determined confidently. Review or remove it."
    analyzed = root / "dataset" / "staging" / "analyzed" / f"{upload_id}.json"
    analyzed.write_text(__import__("json").dumps(result, indent=2), encoding="utf-8")
    _emit(queue, "complete", result=result)


def _entry(project_id: str, path: str, queue: mp.Queue, cancel: mp.Event,
           store_root: str | None = None) -> None:
    try:
        _process(project_id, path, queue, cancel, store_root)
    except Exception as exc:
        _emit(queue, "error", message=str(exc))


def start_font_intake_worker(project_id: str, path: str,
                             store_root: str | None = None) -> tuple[mp.Process, mp.Queue, mp.Event]:
    queue, cancel = mp.Queue(), mp.Event()
    process = mp.Process(target=_entry, args=(project_id, path, queue, cancel, store_root), daemon=True)
    process.start()
    return process, queue, cancel
