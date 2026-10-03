from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

DEFAULTS = {
    "hotkey": ["ctrl", "space"], "model": "small", "language": "auto",
    "device": "auto", "compute_type": "auto", "microphone": "default",
    "auto_copy": True, "auto_paste": False, "sound_feedback": False,
    "start_with_windows": False, "image_path": "",
    # Separate history lists per feature (each capped at 5)
    "voice_history": [],
    "extraction_history": [],
    "font_history": [],
    "files_history": [],
    # Feature toggles
    "enable_extraction": True,
    "enable_font": False,
    "enable_files": False,
    # UI state
    "sidebar_collapsed": False,
    # Legacy: keep for backwards compat — maps to voice_history on load
    "recent_transcriptions": [],
}


def config_path() -> Path:
    if getattr(sys, "frozen", False):
        folder = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "VoiceInput"
        folder.mkdir(parents=True, exist_ok=True)
        return folder / "config.json"
    return Path(__file__).resolve().parent.parent / "config.json"


@dataclass
class Config:
    hotkey: list
    model: str
    language: str
    device: str
    compute_type: str
    microphone: str
    auto_copy: bool
    auto_paste: bool
    sound_feedback: bool
    start_with_windows: bool
    image_path: str
    voice_history: list
    extraction_history: list
    font_history: list
    files_history: list
    enable_extraction: bool
    enable_font: bool
    enable_files: bool
    sidebar_collapsed: bool
    # Legacy field kept for JSON compat
    recent_transcriptions: list

    @classmethod
    def load(cls) -> "Config":
        path = config_path()
        values = DEFAULTS.copy()
        try:
            if path.exists():
                stored = json.loads(path.read_text(encoding="utf-8"))
                values.update(stored)
                # Migrate: if voice_history is empty but recent_transcriptions isn't
                if not values["voice_history"] and values["recent_transcriptions"]:
                    values["voice_history"] = list(values["recent_transcriptions"])
        except (OSError, json.JSONDecodeError):
            pass
        # Build only known keys
        kwargs = {key: values[key] for key in DEFAULTS}
        return cls(**kwargs)

    def save(self) -> None:
        # Keep recent_transcriptions in sync with voice_history for backwards compat
        self.recent_transcriptions = list(self.voice_history)
        config_path().write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    # ── per-feature history helpers ──────────────────────────────────────────

    def add_voice_history(self, text: str) -> None:
        self.voice_history = [text, *self.voice_history][:5]
        self.recent_transcriptions = list(self.voice_history)
        self.save()

    def add_extraction_history(self, text: str, label: str = "") -> None:
        entry = f"{label}: {text}" if label else text
        self.extraction_history = [entry, *self.extraction_history][:5]
        self.save()

    def add_font_history(self, entry: str) -> None:
        self.font_history = [entry, *self.font_history][:5]
        self.save()

    def add_files_history(self, entry: str) -> None:
        self.files_history = [entry, *self.files_history][:5]
        self.save()

    # Legacy helper — kept so old call-sites still compile
    def add_recent_transcription(self, text: str) -> None:
        self.add_voice_history(text)
