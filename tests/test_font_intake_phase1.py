"""Phase 1 intake checks using the existing local handwriting resources."""
from __future__ import annotations

import multiprocessing as mp
from pathlib import Path

import cv2
import numpy as np

from app.custom_character_ocr import CustomCharacterOCR
from app.font_intake_worker import _classify, _extract_known_sheet, _extract_note_candidates, _load, _segment_word_crop, start_font_intake_worker
from app.font_projects import FontProjectStore


def test_known_baseline_sheet_is_staged_with_labels_and_quality(tmp_path: Path) -> None:
    source = Path("dataset/raw/media_1791228862843.jpg")
    image = _load(source)
    sample_type, confidence, _details = _classify(image)
    assert sample_type == "STRUCTURED_GLYPH_SHEET"
    assert confidence >= 0.80

    root = tmp_path / "project"
    (root / "dataset/staging/candidates").mkdir(parents=True)
    candidates, quality_counts, template_id = _extract_known_sheet(
        image, source.name, root, "known_sheet", mp.Queue(), mp.Event(),
    )
    assert template_id == "uppercase_a_to_l"
    assert len(candidates) == 168
    assert sum(quality_counts.values()) == len(candidates)
    assert all(candidate["character"] and candidate["candidate_id"] for candidate in candidates)
    assert all(Path(candidate["candidate_path"]).is_file() for candidate in candidates)


def test_isolated_note_and_uncertain_classification_paths() -> None:
    isolated = np.full((160, 160, 3), 255, dtype=np.uint8)
    cv2.putText(isolated, "A", (45, 120), cv2.FONT_HERSHEY_SIMPLEX, 2.2, (0, 0, 0), 4)
    assert _classify(isolated)[0] == "ISOLATED_GLYPH"

    note = np.full((300, 800, 3), 255, dtype=np.uint8)
    cv2.putText(note, "handwritten note sample", (20, 160), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 3)
    assert _classify(note)[0] == "HANDWRITTEN_NOTE"

    uncertain = np.full((160, 160, 3), 255, dtype=np.uint8)
    assert _classify(uncertain)[0] == "UNCERTAIN"


def test_generic_note_word_segmentation_returns_one_candidate_per_ocr_character() -> None:
    image = np.full((180, 360), 255, dtype=np.uint8)
    cv2.rectangle(image, (30, 40), (100, 145), 0, -1)
    cv2.rectangle(image, (220, 40), (290, 145), 0, -1)

    segments, issues = _segment_word_crop(image, 2)
    assert len(segments) == 2
    assert not issues


def test_custom_character_ocr_loads_project_model_and_predicts_known_glyph() -> None:
    import json
    from PIL import Image

    manifest = json.loads(Path("metadata/glyph_manifest.json").read_text(encoding="utf-8"))
    entry = next(item for item in manifest["entries"] if item.get("review_status") == "GOOD")
    result = CustomCharacterOCR(device="cpu").predict(Image.open(entry["output_path"]))
    assert result["character"] == entry["char"]
    assert result["confidence"] >= 0.75
    assert len(result["top_k"]) == 5


def test_note_glyph_import_skips_review_candidates(tmp_path: Path) -> None:
    store = FontProjectStore(tmp_path / "font_projects")
    project = store.create("Review filtering")
    source = tmp_path / "candidate.png"
    image = np.full((128, 128), 255, dtype=np.uint8)
    cv2.putText(image, "A", (30, 95), cv2.FONT_HERSHEY_SIMPLEX, 2.0, 0, 3)
    assert cv2.imwrite(str(source), image)
    candidates = [
        {"candidate_path": str(source), "character": "A", "quality": "REVIEW", "quality_score": 0.5},
        {"candidate_path": str(source), "character": "A", "quality": "GOOD", "quality_score": 0.95},
    ]
    assert store.import_note_glyphs(project["project_id"], "sample123", candidates) == 1
    assert len(store.entries(project["project_id"])) == 1


def test_note_glyph_import_is_project_scoped_and_direct(tmp_path: Path) -> None:
    store = FontProjectStore(tmp_path / "font_projects")
    first = store.create("First")
    second = store.create("Second")
    source = tmp_path / "candidate.png"
    image = np.full((128, 128), 255, dtype=np.uint8)
    cv2.putText(image, "A", (30, 95), cv2.FONT_HERSHEY_SIMPLEX, 2.0, 0, 3)
    assert cv2.imwrite(str(source), image)

    imported = store.import_note_glyphs(first["project_id"], "sample123", [{
        "candidate_path": str(source),
        "character": "A",
        "category": "user_added",
        "quality": "GOOD",
        "quality_score": 0.95,
        "ocr_confidence": 0.96,
        "source_file": "note.png",
        "source_image": "note.png",
        "source_word": "A",
        "issues": [],
    }])
    assert imported == 1
    first_entries = store.entries(first["project_id"])
    second_entries = store.entries(second["project_id"])
    assert len(first_entries) == 1
    assert first_entries[0]["char"] == "A"
    assert second_entries == []
    assert (first["project_id"] in first_entries[0]["project_id"])

def test_worker_keeps_captured_project_when_another_project_is_active(tmp_path: Path) -> None:
    store = FontProjectStore(tmp_path / "font_projects")
    casual = store.create("Test Casual")
    formal = store.create("Test Formal")
    source = tmp_path / "isolated_A.png"
    image = np.full((160, 160, 3), 255, dtype=np.uint8)
    cv2.putText(image, "A", (45, 120), cv2.FONT_HERSHEY_SIMPLEX, 2.2, (0, 0, 0), 4)
    assert cv2.imwrite(str(source), image)

    # This simulates selecting Formal immediately after Casual's job is queued.
    process, _queue, _cancel = start_font_intake_worker(
        casual["project_id"], str(source), str(tmp_path / "font_projects"),
    )
    active_project_after_switch = formal["project_id"]
    process.join(timeout=15)
    assert not process.is_alive()

    assert FontProjectStore(tmp_path / "font_projects").staged_samples(casual["project_id"])
    assert FontProjectStore(tmp_path / "font_projects").staged_samples(active_project_after_switch) == []
