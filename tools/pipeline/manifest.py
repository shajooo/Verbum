"""
Manifest Management and Output Dataset Serialization.
Generates machine-readable CSV and JSON manifests for all extracted glyphs.
"""
from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Dict, Any, Tuple


@dataclass
class ManifestEntry:
    glyph_id: str
    label: str
    char: str
    category: str
    source_image: str
    sheet_id: str
    block_idx: int
    row: int
    column: int
    crop_x1: int
    crop_y1: int
    crop_x2: int
    crop_y2: int
    norm_size: int
    scale: float
    ink_pixels: int
    contrast: float
    blur_variance: float
    quality_score: float
    confidence: float
    review_status: str
    issues: str
    output_path: str


class ManifestManager:
    """Writes and validates the dataset manifest."""

    def __init__(self, metadata_dir: str | Path = "metadata"):
        self.metadata_dir = Path(metadata_dir)
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        self.entries: List[ManifestEntry] = []

    def add_entry(self, entry: ManifestEntry) -> None:
        self.entries.append(entry)

    def write_manifests(self) -> Tuple[Path, Path]:
        csv_path = self.metadata_dir / "glyph_manifest.csv"
        json_path = self.metadata_dir / "glyph_manifest.json"

        # Write CSV
        fieldnames = [
            "glyph_id", "label", "char", "category", "source_image", "sheet_id",
            "block_idx", "row", "column", "crop_x1", "crop_y1", "crop_x2", "crop_y2",
            "norm_size", "scale", "ink_pixels", "contrast", "blur_variance",
            "quality_score", "confidence", "review_status", "issues", "output_path"
        ]

        with open(csv_path, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for entry in self.entries:
                writer.writerow(asdict(entry))

        # Write JSON
        json_data = {
            "version": "1.0.0",
            "pipeline": "Verbum-Step2-GlyphExtractor",
            "total_glyphs": len(self.entries),
            "summary": {
                "GOOD": sum(1 for e in self.entries if e.review_status == "GOOD"),
                "REVIEW": sum(1 for e in self.entries if e.review_status == "REVIEW"),
                "REJECT": sum(1 for e in self.entries if e.review_status == "REJECT"),
            },
            "entries": [asdict(e) for e in self.entries]
        }

        with open(json_path, mode="w", encoding="utf-8") as f:
            json.dump(json_data, f, indent=2)

        return csv_path, json_path
