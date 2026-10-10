"""Isolated, local storage for Phase 1 handwriting font projects."""
from __future__ import annotations

import csv
import json
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .resources import application_output_root, resource_root


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class FontProjectStore:
    """Owns project discovery and validates every project-scoped destination."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or application_output_root() / "font_projects"
        self.root.mkdir(parents=True, exist_ok=True)

    def list_projects(self) -> list[dict[str, Any]]:
        projects = []
        for path in self.root.iterdir():
            info = path / "project.json"
            if not info.is_file():
                continue
            try:
                project = json.loads(info.read_text(encoding="utf-8"))
                if project.get("project_id") == path.name:
                    projects.append(project)
            except (OSError, json.JSONDecodeError):
                continue
        return sorted(projects, key=lambda item: item.get("created_at", ""))

    def project_root(self, project_id: str) -> Path:
        safe = re.fullmatch(r"[a-z0-9][a-z0-9_-]{2,79}", project_id or "")
        if not safe:
            raise ValueError("Invalid font project ID")
        path = (self.root / project_id).resolve()
        if path.parent != self.root.resolve() or not (path / "project.json").is_file():
            raise ValueError("Unknown font project")
        return path

    def get(self, project_id: str) -> dict[str, Any]:
        return json.loads((self.project_root(project_id) / "project.json").read_text(encoding="utf-8"))

    def create(self, name: str, *, legacy: bool = False) -> dict[str, Any]:
        name = " ".join(name.split())
        if not name or len(name) > 80:
            raise ValueError("Font project name must contain 1 to 80 characters.")
        slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "font_project"
        project_id = f"{slug[:48]}_{uuid.uuid4().hex[:8]}"
        root = self.root / project_id
        for relative in ("dataset/raw", "dataset/glyphs", "dataset/staging/uploads", "dataset/staging/analyzed",
                         "dataset/staging/candidates", "dataset/staging/accepted", "dataset/staging/rejected",
                         "dataset/review", "metadata", "generated", "history"):
            (root / relative).mkdir(parents=True, exist_ok=True)
        project: dict[str, Any] = {
            "project_id": project_id, "project_name": name, "created_at": _now(),
            "schema_version": 1, "legacy_read_only": legacy,
        }
        if legacy:
            source = resource_root()
            project["legacy_dataset_root"] = str(source / "dataset" / "glyphs")
            project["legacy_manifest"] = str(source / "metadata" / "glyph_manifest.json")
            # Metadata is copied once so the project has its own manifest without duplicating glyph images.
            src = source / "metadata" / "glyph_manifest.json"
            if src.is_file():
                data = json.loads(src.read_text(encoding="utf-8"))
                data.update({"project_id": project_id, "project_name": name, "legacy_read_only": True})
                (root / "metadata" / "glyph_manifest.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
                shutil.copy2(src.with_suffix(".csv"), root / "metadata" / "glyph_manifest.csv")
        else:
            self._write_manifest(root, project_id, [])
        (root / "project.json").write_text(json.dumps(project, indent=2), encoding="utf-8")
        return project

    def ensure_legacy_project(self) -> dict[str, Any]:
        current_root = resource_root()
        expected_manifest = str((current_root / "metadata" / "glyph_manifest.json").resolve())
        expected_glyphs = str((current_root / "dataset" / "glyphs").resolve())
        for item in self.list_projects():
            if not item.get("legacy_read_only"):
                continue
            root = self.project_root(item["project_id"])
            changed = (
                item.get("legacy_manifest") != expected_manifest
                or item.get("legacy_dataset_root") != expected_glyphs
            )
            if changed:
                item["legacy_manifest"] = expected_manifest
                item["legacy_dataset_root"] = expected_glyphs
                (root / "project.json").write_text(
                    json.dumps(item, indent=2), encoding="utf-8"
                )
            return item
        return self.create("Legacy verified dataset", legacy=True)

    def manifest_path(self, project_id: str) -> Path:
        return self.project_root(project_id) / "metadata" / "glyph_manifest.json"

    def dataset_paths(self, project_id: str) -> tuple[Path, Path]:
        """Resolve a project's only allowed font-generation input dataset."""
        project = self.get(project_id)
        manifest = self.manifest_path(project_id)
        glyphs = self.project_root(project_id) / "dataset" / "glyphs"
        if project.get("legacy_read_only"):
            manifest = Path(project["legacy_manifest"])
            glyphs = Path(project["legacy_dataset_root"])
        else:
            glyphs.mkdir(parents=True, exist_ok=True)
        if not manifest.is_file() or not glyphs.is_dir():
            raise ValueError("This font project's verified dataset is unavailable.")
        return manifest, glyphs

    def generation_directory(self, project_id: str) -> tuple[Path, int]:
        """Allocate a new immutable version directory inside one project."""
        root = self.project_root(project_id) / "generated"
        versions = [int(p.name[1:]) for p in root.glob("v[0-9][0-9][0-9]") if p.name[1:].isdigit()]
        version = max(versions, default=0) + 1
        target = root / f"v{version:03d}"
        target.mkdir(parents=True, exist_ok=False)
        return target, version

    def discard_generation_directory(self, project_id: str, version: int) -> None:
        """Remove an unrecorded, failed generation directory for this project only."""
        root = self.project_root(project_id) / "generated"
        target = (root / f"v{version:03d}").resolve()
        if target.parent != root.resolve() or (target / "metadata.json").exists():
            return
        if target.exists():
            shutil.rmtree(target)

    def record_generation(self, project_id: str, metadata: dict[str, Any]) -> None:
        root = self.project_root(project_id)
        if metadata.get("project_id") != project_id:
            raise ValueError("Project mismatch: this font belongs to another font project.")
        metadata["created_at"] = _now()
        version = int(metadata["version"])
        generated = root / "generated" / f"v{version:03d}"
        (generated / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        (root / "history" / f"v{version:03d}.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    def generation_history(self, project_id: str) -> list[dict[str, Any]]:
        root = self.project_root(project_id) / "history"
        records = []
        for path in root.glob("v*.json"):
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
                if item.get("project_id") == project_id:
                    records.append(item)
            except (OSError, json.JSONDecodeError):
                continue
        return sorted(records, key=lambda item: int(item.get("version", 0)), reverse=True)

    def validated_generation(self, project_id: str, version: int) -> dict[str, Any] | None:
        """Return a validated generated font whose artifacts stay inside one project version."""
        project_root = self.project_root(project_id)
        expected_dir = (project_root / "generated" / f"v{int(version):03d}").resolve()
        for item in self.generation_history(project_id):
            if int(item.get("version", -1)) != int(version) or not item.get("validation_passed"):
                continue
            try:
                if item.get("project_id") != project_id:
                    return None
                if not (expected_dir / "metadata.json").is_file():
                    return None
                paths = {key: Path(item[key]).resolve() for key in ("ttf_path", "otf_path", "specimen_path")
                         if item.get(key)}
                if "ttf_path" not in paths or paths["ttf_path"].parent != expected_dir or not paths["ttf_path"].is_file():
                    return None
                if paths and any(path.parent != expected_dir or not path.is_file() for path in paths.values()):
                    return None
                return item
            except (KeyError, OSError, ValueError):
                return None
        return None

    def latest_generation(self, project_id: str) -> dict[str, Any] | None:
        """Return only this project's latest validated font record with safe artifact paths."""
        for item in self.generation_history(project_id):
            version = item.get("version")
            if version is None:
                continue
            validated = self.validated_generation(project_id, int(version))
            if validated is not None:
                return validated
        return None

    def entries(self, project_id: str) -> list[dict[str, Any]]:
        try:
            return json.loads(self.manifest_path(project_id).read_text(encoding="utf-8")).get("entries", [])
        except (OSError, json.JSONDecodeError):
            return []

    def import_note_glyphs(
        self,
        project_id: str,
        sample_id: str,
        candidates: list[dict[str, Any]],
    ) -> int:
        """Commit OCR-derived handwritten-note glyphs directly into one project's dataset."""
        root = self.project_root(project_id)
        project = self.get(project_id)
        if project.get("legacy_read_only"):
            raise ValueError("The Legacy verified dataset is read-only. Create a new font project before uploading handwriting.")
        if not candidates:
            return 0
        entries = self.entries(project_id)
        known = {entry.get("glyph_id") for entry in entries}
        imported = 0

        for candidate in candidates:
            if candidate.get("quality") != "GOOD":
                continue
            source = Path(candidate.get("candidate_path", ""))
            character = str(candidate.get("character", ""))
            if not source.is_file() or len(character) != 1:
                continue
            glyph_id = f"{character}_{sample_id[:10]}_{imported:03d}"
            while glyph_id in known:
                glyph_id = f"{character}_{sample_id[:10]}_{uuid.uuid4().hex[:5]}"
            known.add(glyph_id)

            category = candidate.get("category", "user_added")
            target = root / "dataset" / "glyphs" / category / character / f"{glyph_id}.png"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

            entries.append({
                "glyph_id": glyph_id,
                "project_id": project_id,
                "char": character,
                "label": character,
                "category": category,
                "source_file": candidate.get("source_file", ""),
                "source_type": "handwritten_note",
                "sample_type": "HANDWRITTEN_NOTE",
                "extraction_method": "ocr_word_box_projection_plus_custom_character_ocr_v2",
                "quality": candidate.get("quality", "REVIEW"),
                "quality_score": candidate.get("quality_score", 0.0),
                "confidence": candidate.get("ocr_confidence", 0.0),
                "review_state": "IMPORTED",
                "review_status": candidate.get("quality", "REVIEW"),
                "timestamp": _now(),
                "output_path": str(target),
                "source_image": candidate.get("source_image", ""),
                "source_sample_id": sample_id,
                "source_word": candidate.get("source_word", ""),
                "issues": ";".join(candidate.get("issues", [])) or "NONE",
            })
            imported += 1

        self._write_manifest(root, project_id, entries)
        return imported

    def staged_samples(self, project_id: str) -> list[dict[str, Any]]:
        """Return analyzed records from exactly one project's staging namespace."""
        root = self.project_root(project_id)
        records: list[dict[str, Any]] = []
        for path in (root / "dataset" / "staging" / "analyzed").glob("*.json"):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if record.get("project_id") == project_id:
                records.append(record)
        return sorted(
            (item for item in records if item.get("status") != "IMPORTED"),
            key=lambda item: item.get("created_at", ""),
            reverse=True,
        )

    def _write_manifest(self, root: Path, project_id: str, entries: list[dict[str, Any]]) -> None:
        summary = {state: sum(1 for item in entries if item.get("review_status") == state)
                   for state in ("GOOD", "REVIEW", "REJECT")}
        payload = {"version": "2.0.0", "project_id": project_id,
                   "pipeline": "Verbum-Phase1-Staging", "total_glyphs": len(entries),
                   "summary": summary, "entries": entries}
        metadata = root / "metadata"
        metadata.mkdir(parents=True, exist_ok=True)
        (metadata / "glyph_manifest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        fields = sorted({key for entry in entries for key in entry} | {"glyph_id", "project_id", "char", "review_status"})
        with (metadata / "glyph_manifest.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader(); writer.writerows(entries)

    def add_entries(self, project_id: str, entries: list[dict[str, Any]]) -> None:
        root = self.project_root(project_id)
        if any(entry.get("project_id") != project_id for entry in entries):
            raise ValueError("Project mismatch: this sample belongs to another font project.")
        old = self.entries(project_id)
        known = {entry.get("glyph_id") for entry in old}
        for entry in entries:
            while entry["glyph_id"] in known:
                entry["glyph_id"] = f"{entry['glyph_id']}_{uuid.uuid4().hex[:5]}"
            known.add(entry["glyph_id"])
        self._write_manifest(root, project_id, old + entries)

    def accept_candidate(self, project_id: str, sample_id: str, candidate_id: str, character: str | None = None) -> dict[str, Any]:
        """Promote one reviewed candidate into this project's accepted staging only."""
        root = self.project_root(project_id)
        record_path = root / "dataset" / "staging" / "analyzed" / f"{sample_id}.json"
        record = json.loads(record_path.read_text(encoding="utf-8"))
        if record.get("project_id") != project_id:
            raise ValueError("Project mismatch: this sample belongs to another font project.")
        candidates = record.get("candidates", [])
        candidate = next((item for item in candidates if item.get("candidate_id", sample_id) == candidate_id), None)
        if not candidate:
            raise ValueError("This sample has no glyph candidate to accept.")
        character = character or candidate.get("character", "")
        if not character or len(character) > 2:
            raise ValueError("Enter a valid glyph label.")
        source = Path(candidate["candidate_path"])
        if not source.is_file():
            raise ValueError("The staged glyph candidate is missing.")
        glyph_id = f"{character}_{uuid.uuid4().hex[:10]}"
        target = root / "dataset" / "staging" / "accepted" / glyph_id[:1] / f"{glyph_id}.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        entry = {"glyph_id": glyph_id, "project_id": project_id, "char": character,
                 "label": character, "category": "user_added", "source_file": record["file_name"],
                 "source_type": "uploaded_file", "sample_type": "ISOLATED_GLYPH",
                 "extraction_method": record["classification_method"], "quality": "REVIEW",
                 "confidence": record["confidence"], "review_state": "ACCEPTED_STAGED",
                 "review_status": "REVIEW", "timestamp": _now(), "output_path": str(target),
                 "source_image": record["file_name"], "issues": "LABEL_CONFIRMED_BY_USER"}
        entry["sample_type"] = record.get("sample_type", "ISOLATED_GLYPH")
        entry["category"] = candidate.get("category", entry["category"])
        entry["quality"] = candidate.get("quality", entry["quality"])
        entry["issues"] = ";".join(candidate.get("issues", [])) or "NONE"
        self.add_entries(project_id, [entry])
        candidate["review_state"] = "ACCEPTED_STAGED"
        candidate["accepted_glyph_id"] = glyph_id
        record["status"] = "ACCEPTED_STAGED"; record["accepted_glyph_id"] = glyph_id
        record_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
        return entry

    def accept_isolated_sample(self, project_id: str, sample_id: str, character: str) -> dict[str, Any]:
        return self.accept_candidate(project_id, sample_id, sample_id, character)

    def review_sample(self, project_id: str, sample_id: str) -> None:
        root = self.project_root(project_id)
        analyzed = root / "dataset" / "staging" / "analyzed" / f"{sample_id}.json"
        record = json.loads(analyzed.read_text(encoding="utf-8"))
        if record.get("project_id") != project_id:
            raise ValueError("Project mismatch: this sample belongs to another font project.")
        record["status"] = "REVIEW_REQUESTED"
        record["review_requested_at"] = _now()
        analyzed.write_text(json.dumps(record, indent=2), encoding="utf-8")
        (root / "dataset" / "review" / f"{sample_id}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")

    def remove_staged_sample(self, project_id: str, sample_id: str) -> None:
        """Remove only a project's unaccepted staging artifacts; never verified glyphs."""
        root = self.project_root(project_id)
        analyzed = root / "dataset" / "staging" / "analyzed" / f"{sample_id}.json"
        record = json.loads(analyzed.read_text(encoding="utf-8"))
        if record.get("project_id") != project_id:
            raise ValueError("Project mismatch: this sample belongs to another font project.")
        if any(item.get("review_state") == "ACCEPTED_STAGED" for item in record.get("candidates", [])):
            raise ValueError("Accepted candidates cannot be removed here. They remain staged for explicit dataset import.")
        for candidate in record.get("candidates", []):
            Path(candidate.get("candidate_path", "")).unlink(missing_ok=True)
        Path(record.get("source_path", "")).unlink(missing_ok=True)
        analyzed.unlink(missing_ok=True)

    def merge_accepted_samples(self, project_id: str) -> int:
        """Explicitly import reviewed staging samples into this project's dataset only."""
        root = self.project_root(project_id)
        entries = self.entries(project_id)
        changed = 0
        for entry in entries:
            if entry.get("project_id") != project_id:
                raise ValueError("Project mismatch: this sample belongs to another font project.")
            if entry.get("review_state") != "ACCEPTED_STAGED":
                continue
            source = Path(entry.get("output_path", ""))
            if not source.is_file():
                raise ValueError(f"Accepted staging sample is missing: {entry.get('glyph_id')}")
            target = root / "dataset" / "glyphs" / entry.get("category", "user_added") / entry["char"] / source.name
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                target = target.with_name(f"{target.stem}_{uuid.uuid4().hex[:5]}{target.suffix}")
            shutil.copy2(source, target)
            entry["output_path"] = str(target)
            entry["review_state"] = "IMPORTED"
            entry["imported_at"] = _now()
            changed += 1
        self._write_manifest(root, project_id, entries)
        return changed
