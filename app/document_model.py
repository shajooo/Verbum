"""Local editable document persistence helpers for Create Files."""
from __future__ import annotations
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

@dataclass
class DocumentPage:
    html: str = "<html><body><p><br></p></body></html>"

@dataclass
class EditableDocument:
    title: str = "Untitled"
    pages: list[DocumentPage] = field(default_factory=lambda: [DocumentPage()])
    font_ref: dict[str, Any] = field(default_factory=dict)
    source_pdf: str | None = None
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "title": self.title,
                "pages": [{"html": p.html} for p in self.pages],
                "font_ref": dict(self.font_ref), "source_pdf": self.source_pdf}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EditableDocument":
        pages = [DocumentPage(str(p.get("html", ""))) for p in data.get("pages", []) if isinstance(p, dict)]
        return cls(title=str(data.get("title", "Untitled"))[:200],
                   pages=pages or [DocumentPage()],
                   font_ref=data.get("font_ref", {}) if isinstance(data.get("font_ref", {}), dict) else {},
                   source_pdf=data.get("source_pdf"), schema_version=1)

def save_document(path: str | Path, document: EditableDocument) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(document.to_dict(), stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except Exception:
        try: os.unlink(temporary)
        except OSError: pass
        raise

def load_document(path: str | Path) -> EditableDocument:
    with Path(path).open("r", encoding="utf-8") as stream:
        data = json.load(stream)
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("Unsupported or invalid Verbum document format.")
    return EditableDocument.from_dict(data)
