"""Runtime locations for bundled, read-only application resources."""
from __future__ import annotations

import sys
from pathlib import Path


def resource_root() -> Path:
    """Return the root containing packaged resources in either runtime mode."""
    if getattr(sys, "frozen", False):
        bundle_root = getattr(sys, "_MEIPASS", None)
        if not bundle_root:
            raise RuntimeError("Frozen application has no PyInstaller resource root.")
        return Path(bundle_root).resolve()
    return Path(__file__).resolve().parent.parent


def application_output_root() -> Path:
    """Return the existing writable-output location for the active app layout."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def font_dataset_paths() -> tuple[Path, Path]:
    """Return the manifest and glyph directory from one runtime resource root."""
    root = resource_root()
    return root / "metadata" / "glyph_manifest.json", root / "dataset" / "glyphs"
