import json
from pathlib import Path

from app.font_projects import FontProjectStore


def test_projects_keep_manifests_and_samples_isolated(tmp_path: Path) -> None:
    store = FontProjectStore(tmp_path / "font_projects")
    casual = store.create("Test Casual")
    formal = store.create("Test Formal")

    candidate = tmp_path / "candidate.png"
    candidate.write_bytes(b"test image")
    analyzed = store.project_root(casual["project_id"]) / "dataset/staging/analyzed/sample.json"
    analyzed.write_text(json.dumps({
        "project_id": casual["project_id"], "file_name": "casual.png",
        "classification_method": "test", "confidence": 1.0,
        "candidates": [{"candidate_path": str(candidate)}],
    }), encoding="utf-8")

    store.accept_isolated_sample(casual["project_id"], "sample", "A")
    assert len(store.entries(casual["project_id"])) == 1
    assert store.entries(formal["project_id"]) == []
    assert store.merge_accepted_samples(casual["project_id"]) == 1
    assert len(list((store.project_root(casual["project_id"]) / "dataset/glyphs").rglob("*.png"))) == 1
    assert (store.project_root(formal["project_id"]) / "dataset/glyphs").is_dir()
    assert not list((store.project_root(formal["project_id"]) / "dataset/glyphs").rglob("*.png"))


def test_staged_review_records_never_cross_project_boundaries(tmp_path: Path) -> None:
    store = FontProjectStore(tmp_path / "font_projects")
    casual = store.create("Test Casual")
    formal = store.create("Test Formal")
    record = {
        "sample_id": "note_01", "project_id": casual["project_id"],
        "file_name": "casual-note.jpg", "sample_type": "HANDWRITTEN_NOTE",
        "created_at": "2026-10-07T12:00:00+00:00", "candidates": [],
    }
    analyzed = store.project_root(casual["project_id"]) / "dataset/staging/analyzed/note_01.json"
    analyzed.write_text(json.dumps(record), encoding="utf-8")

    assert [item["sample_id"] for item in store.staged_samples(casual["project_id"])] == ["note_01"]
    assert store.staged_samples(formal["project_id"]) == []
    store.review_sample(casual["project_id"], "note_01")
    assert (store.project_root(casual["project_id"]) / "dataset/review/note_01.json").is_file()
    assert not (store.project_root(formal["project_id"]) / "dataset/review/note_01.json").exists()


def test_project_mismatch_stops_review_operation(tmp_path: Path) -> None:
    store = FontProjectStore(tmp_path / "font_projects")
    casual = store.create("Test Casual")
    formal = store.create("Test Formal")
    record = {"sample_id": "uncertain", "project_id": casual["project_id"], "candidates": []}
    analyzed = store.project_root(formal["project_id"]) / "dataset/staging/analyzed/uncertain.json"
    analyzed.write_text(json.dumps(record), encoding="utf-8")

    try:
        store.review_sample(formal["project_id"], "uncertain")
    except ValueError as exc:
        assert "Project mismatch" in str(exc)
    else:
        raise AssertionError("A sample must not be reviewable from another project")


def test_generated_versions_and_history_are_project_scoped(tmp_path: Path) -> None:
    """A completed job may only publish into its captured project's namespace."""
    store = FontProjectStore(tmp_path / "font_projects")
    casual = store.create("Test Casual")
    formal = store.create("Test Formal")

    casual_dir, casual_v1 = store.generation_directory(casual["project_id"])
    casual_meta = {
        "project_id": casual["project_id"], "version": casual_v1,
        "ttf_path": str(casual_dir / "Test_Casual.ttf"), "validation_passed": True,
    }
    store.record_generation(casual["project_id"], casual_meta)
    casual_dir_2, casual_v2 = store.generation_directory(casual["project_id"])
    formal_dir, formal_v1 = store.generation_directory(formal["project_id"])

    assert (casual_dir / "metadata.json").is_file()
    assert casual_v2 == casual_v1 + 1
    assert formal_v1 == 1
    assert formal_dir.parent == store.project_root(formal["project_id"]) / "generated"
    assert not list((store.project_root(formal["project_id"]) / "history").glob("*.json"))

    # Cancellation cleans the unrecorded allocation without touching v001.
    store.discard_generation_directory(casual["project_id"], casual_v2)
    assert casual_dir.exists()
    assert not casual_dir_2.exists()


def test_validated_generation_rejects_artifacts_outside_project_version(tmp_path: Path) -> None:
    store = FontProjectStore(tmp_path / "font_projects")
    project = store.create("Safe Font")
    output, version = store.generation_directory(project["project_id"])

    external = tmp_path / "external.ttf"
    external.write_bytes(b"not a real font")
    record = {
        "project_id": project["project_id"],
        "version": version,
        "ttf_path": str(external),
        "validation_passed": True,
    }
    store.record_generation(project["project_id"], record)

    assert store.validated_generation(project["project_id"], version) is None
    assert store.latest_generation(project["project_id"]) is None
    assert output.exists()
