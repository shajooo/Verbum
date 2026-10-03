from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from xml.etree import ElementTree


class ExtractionError(RuntimeError):
    """A user-facing local extraction failure."""


class UnsupportedInputError(ExtractionError):
    pass


@dataclass(frozen=True)
class DetectedInput:
    kind: str
    path: Path


@dataclass(frozen=True)
class ExtractionResult:
    text: str
    output_path: Path
    input_kind: str


class InputDetector:
    """Identify supported local inputs by signatures before falling back to PIL.

    Detection order is critical:
      1. PDF  (unambiguous magic bytes)
      2. DOCX (ZIP + word/document.xml)
      3. Raster image via PIL   ← MUST come before SVG so that PNG/JPEG/WEBP
         files containing embedded XMP/SVG metadata are not misidentified.
      4. SVG  (text XML containing <svg>)
    """

    raster_extensions = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif", ".ico", ".avif"}

    def detect(self, path: str | Path) -> DetectedInput:
        source = Path(path)
        if not source.is_file():
            raise ExtractionError("The selected file no longer exists or cannot be read.")
        try:
            with source.open("rb") as input_file:
                header = input_file.read(4096)
        except OSError as exc:
            raise ExtractionError(f"Could not read the selected file: {exc}") from exc
        suffix = source.suffix.lower()

        # 1. PDF — unambiguous binary magic bytes
        if header.startswith(b"%PDF-"):
            return DetectedInput("pdf", source)

        # 2. DOCX — ZIP container with word/document.xml
        if self._looks_like_docx(source):
            return DetectedInput("docx", source)

        # 3. Raster image — check with PIL BEFORE SVG so that PNG/JPEG/WEBP
        #    files containing embedded XMP or SVG thumbnail metadata are not
        #    accidentally routed to the SVG parser.
        if self._is_raster_image(source):
            return DetectedInput("raster", source)

        # 4. SVG — plain-text XML; only reaches here when PIL failed (i.e. not
        #    a recognised raster format), which is the expected situation for a
        #    real SVG file.
        if self._looks_like_svg(header, suffix):
            return DetectedInput("svg", source)

        if suffix in {".pdf", ".docx", ".svg", *self.raster_extensions}:
            raise UnsupportedInputError(
                f"The selected {suffix.upper()} file is corrupt or is not a supported "
                f"{suffix.upper()} file."
            )
        raise UnsupportedInputError(
            f"Unsupported file type: {suffix or 'unknown'}. "
            "Choose an image, SVG, PDF, or DOCX file."
        )

    @staticmethod
    def _looks_like_docx(path: Path) -> bool:
        if not zipfile.is_zipfile(path):
            return False
        try:
            with zipfile.ZipFile(path) as archive:
                return "word/document.xml" in archive.namelist()
        except (OSError, zipfile.BadZipFile):
            return False

    @staticmethod
    def _looks_like_svg(header: bytes, suffix: str = "") -> bool:
        """Return True only when the file looks like a plain-text SVG document.

        We require *both*:
          - The decoded header contains <svg (case-insensitive)
          - The suffix is .svg OR the file starts with text-like bytes
            (no binary null bytes in the first 256 bytes, which would indicate
            a binary format that merely embeds SVG metadata, such as PNG XMP).
        """
        # Fast path: if there are binary null bytes near the start, it is not a
        # plain-text SVG document even if it contains <svg somewhere.
        if b"\x00" in header[:256]:
            return False
        text = header.decode("utf-8", errors="ignore").lstrip("\ufeff \t\r\n").lower()
        return "<svg" in text[:1024]

    @staticmethod
    def _is_raster_image(path: Path) -> bool:
        try:
            from PIL import Image
            with Image.open(path) as image:
                image.verify()
            return True
        except Exception:
            return False


class TextProcessor:
    """Conservative cleanup: retain extracted reading order and meaningful lines."""

    def normalize(self, text: str) -> str:
        text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
        result: list[str] = []
        blank = False
        for line in lines:
            if not line:
                if result and not blank:
                    result.append("")
                blank = True
            else:
                result.append(line)
                blank = False
        return "\n".join(result).strip()


class TextFileWriter:
    def write(self, source: Path, text: str) -> Path:
        base = source.with_suffix(".txt")
        candidates = [base, source.with_name(f"{source.stem} (extracted).txt")]
        candidates.extend(source.with_name(f"{source.stem} (extracted {n}).txt") for n in range(2, 1000))
        for candidate in candidates:
            try:
                with candidate.open("x", encoding="utf-8", newline="\n") as output_file:
                    output_file.write(text)
                    if text and not text.endswith("\n"):
                        output_file.write("\n")
                return candidate
            except FileExistsError:
                continue
            except OSError as exc:
                raise ExtractionError(f"Could not create the text file beside the source: {exc}") from exc
        raise ExtractionError("Could not find a safe output filename after 1,000 attempts.")


class ImageOCR:
    """
    Local OCR adapter backed by RapidOCR (ONNX Runtime).

    The engine is isolated behind this class so it can be replaced without
    touching any extraction pipeline code.  Cancellation is supported via an
    optional ``cancelled`` callable that is checked before invoking the engine.
    """

    # Discard any detection whose confidence is below this threshold.
    MIN_CONFIDENCE: float = 0.30

    def __init__(self) -> None:
        self._engine = None

    def extract_path(self, path: Path, cancelled: Callable[[], bool] | None = None) -> str:
        from PIL import Image
        if cancelled and cancelled():
            raise ExtractionError("Extraction was cancelled.")
        try:
            with Image.open(path) as image:
                image.load()
                return self.extract_image(image.copy(), cancelled=cancelled)
        except ExtractionError:
            raise
        except Exception as exc:
            raise ExtractionError(f"Could not open the image for OCR: {exc}") from exc

    def extract_image(self, image, cancelled: Callable[[], bool] | None = None) -> str:
        import numpy as np
        if cancelled and cancelled():
            raise ExtractionError("Extraction was cancelled.")
        prepared = self._preprocess(image)
        engine = self._get_engine()
        try:
            results, _elapsed = engine(np.asarray(prepared))
        except Exception as exc:
            raise ExtractionError(f"Local OCR could not process this image: {exc}") from exc
        if not results:
            return ""
        return self._reconstruct(results)

    def _get_engine(self):
        if self._engine is None:
            try:
                from rapidocr_onnxruntime import RapidOCR
                self._engine = RapidOCR()
            except Exception as exc:
                raise ExtractionError("The local OCR engine could not be initialised. Reinstall the application dependencies.") from exc
        return self._engine

    @staticmethod
    def _preprocess(image):
        from PIL import Image, ImageEnhance, ImageOps, ImageStat
        image = ImageOps.exif_transpose(image)
        if image.mode in {"RGBA", "LA"}:
            background = image.convert("RGBA")
            canvas = Image.new("RGBA", background.size, "white")
            canvas.alpha_composite(background)
            image = canvas.convert("RGB")
        elif image.mode == "P":
            # Palette mode may include transparency
            image = image.convert("RGBA")
            canvas = Image.new("RGBA", image.size, "white")
            canvas.alpha_composite(image)
            image = canvas.convert("RGB")
        elif image.mode != "RGB":
            image = image.convert("RGB")
        # Upscale only genuinely small inputs. This helps screenshots without
        # spending memory on normal document pages.
        small_side = min(image.size)
        if 0 < small_side < 900:
            scale = min(3.0, 900 / small_side)
            image = image.resize(
                (round(image.width * scale), round(image.height * scale)),
                Image.Resampling.LANCZOS,  # class attribute, not instance attribute
            )
        gray = ImageOps.grayscale(image)
        contrast = ImageStat.Stat(gray).stddev[0]
        if contrast < 42:
            gray = ImageOps.autocontrast(gray, cutoff=1)
            gray = ImageEnhance.Contrast(gray).enhance(1.35)
        return gray

    @staticmethod
    def _reconstruct(results) -> str:
        """
        Reconstruct reading-order text from RapidOCR output.

        Each item is (box, text, confidence) where box is a quad of [x, y] points.
        Low-confidence detections are silently discarded.
        """
        entries: list[tuple[float, float, float, str]] = []
        for item in results:
            if len(item) < 2 or not item[1]:
                continue
            box = item[0] or []
            value = str(item[1]).strip()
            if not value:
                continue
            # Optional confidence filtering (item[2] may be float or str float)
            if len(item) >= 3:
                try:
                    if float(item[2]) < ImageOCR.MIN_CONFIDENCE:
                        continue
                except (TypeError, ValueError):
                    pass
            xs = [float(p[0]) for p in box] if box else [0.0]
            ys = [float(p[1]) for p in box] if box else [0.0]
            entries.append((min(ys), min(xs), max(ys) - min(ys), value))
        if not entries:
            return ""
        entries.sort(key=lambda entry: (entry[0], entry[1]))
        lines: list[list[tuple[float, float, float, str]]] = []
        for entry in entries:
            if not lines:
                lines.append([entry])
                continue
            last = lines[-1]
            line_y = sum(item[0] for item in last) / len(last)
            typical_height = max(10.0, sum(item[2] for item in last) / len(last))
            if abs(entry[0] - line_y) <= typical_height * 0.65:
                last.append(entry)
            else:
                lines.append([entry])
        return "\n".join(" ".join(item[3] for item in sorted(line, key=lambda entry: entry[1])) for line in lines)


class SVGExtractor:
    """
    Extract text from SVG files.

    Strategy:
      1. Parse the XML and collect all <text>, <tspan>, <textPath> content.
         If any text is found, return it — no rasterisation needed.
      2. If the SVG has no text elements, rasterise via pymupdf (bundled,
         no native libcairo required on Windows) then pass through ImageOCR.
    """

    def __init__(self, image_ocr: ImageOCR) -> None:
        self.image_ocr = image_ocr

    def extract(self, path: Path, cancelled: Callable[[], bool] | None = None) -> str:
        try:
            raw = path.read_bytes()
            root = ElementTree.fromstring(raw)
        except (OSError, ElementTree.ParseError) as exc:
            raise ExtractionError(f"Could not parse the SVG file: {exc}") from exc
        fragments: list[str] = []
        for element in root.iter():
            tag = element.tag.rsplit("}", 1)[-1].lower()
            if tag in {"text", "tspan", "textpath"}:
                value = "".join(element.itertext()).strip()
                if value and value not in fragments:
                    fragments.append(value)
        if fragments:
            return "\n".join(fragments)
        # No text elements — rasterise and OCR
        if cancelled and cancelled():
            raise ExtractionError("Extraction was cancelled.")
        return self._rasterise_and_ocr(raw, cancelled)

    def _rasterise_and_ocr(self, raw: bytes, cancelled: Callable[[], bool] | None) -> str:
        try:
            import pymupdf
            from PIL import Image

            doc = pymupdf.open(stream=raw, filetype="svg")
            try:
                page = doc[0]
                pix = page.get_pixmap(matrix=pymupdf.Matrix(2.0, 2.0), alpha=False)
                png = pix.tobytes("png")
            finally:
                doc.close()

            with Image.open(io.BytesIO(png)) as image:
                return self.image_ocr.extract_image(image.copy(), cancelled=cancelled)
        except ExtractionError:
            raise
        except Exception as exc:
            raise ExtractionError(f"Could not render the SVG for local OCR: {exc}") from exc


class PDFTextExtractor:
    """
    Extract text from PDF files.

    Per-page strategy:
      - If selectable text exists on the page: extract it directly (no OCR).
      - Otherwise: render at 2.5× and OCR.

    Supports single-page, multi-page, and mixed PDFs.
    Cancellation is checked between pages.
    """

    RENDER_SCALE = 2.5

    def __init__(self, image_ocr: ImageOCR) -> None:
        self.image_ocr = image_ocr

    def extract(self, path: Path, cancelled: Callable[[], bool] | None = None,
                on_ocr_needed: Callable[[], None] | None = None) -> str:
        try:
            import pymupdf
            document = pymupdf.open(str(path))
        except Exception as exc:
            raise ExtractionError(f"Could not open the PDF: {exc}") from exc
        try:
            if document.needs_pass and not document.authenticate(""):
                raise ExtractionError("This PDF is encrypted and needs a password before it can be extracted.")
            pages: list[str] = []
            ocr_notified = False
            for index, page in enumerate(document, start=1):
                if cancelled and cancelled():
                    raise ExtractionError("Extraction was cancelled.")
                direct_text = page.get_text("text").strip()
                if direct_text:
                    pages.append(direct_text)
                    continue
                # This page needs OCR — notify once
                if not ocr_notified and on_ocr_needed:
                    on_ocr_needed()
                    ocr_notified = True
                pages.append(self._ocr_page(page, index, cancelled))
            return "\n\n".join(
                f"Page {number}\n{value}" if value else f"Page {number}"
                for number, value in enumerate(pages, start=1)
            )
        except ExtractionError:
            raise
        except Exception as exc:
            raise ExtractionError(f"Could not extract the PDF pages: {exc}") from exc
        finally:
            document.close()

    def _ocr_page(self, page, index: int, cancelled: Callable[[], bool] | None) -> str:
        from PIL import Image
        import pymupdf
        try:
            matrix = pymupdf.Matrix(self.RENDER_SCALE, self.RENDER_SCALE)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            png = pix.tobytes("png")
            with Image.open(io.BytesIO(png)) as image:
                return self.image_ocr.extract_image(image.copy(), cancelled=cancelled)
        except ExtractionError:
            raise
        except Exception as exc:
            raise ExtractionError(f"Could not OCR page {index} of the PDF: {exc}") from exc


class DOCXExtractor:
    """
    Extract text from .docx files without requiring Microsoft Word.

    Extracts paragraphs, headings, and table content in document order.
    Merged table cells are deduplicated (python-docx repeats them).
    """

    def extract(self, path: Path, cancelled: Callable[[], bool] | None = None) -> str:
        try:
            from docx import Document
            from docx.table import Table
            from docx.text.paragraph import Paragraph
            document = Document(path)
        except Exception as exc:
            raise ExtractionError(f"Could not open the Word document: {exc}") from exc
        blocks: list[str] = []
        for child in document.element.body.iterchildren():
            if cancelled and cancelled():
                raise ExtractionError("Extraction was cancelled.")
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "p":
                value = Paragraph(child, document).text.strip()
                if value:
                    blocks.append(value)
            elif tag == "tbl":
                table = Table(child, document)
                for row in table.rows:
                    # Deduplicate merged cells (python-docx repeats the same
                    # cell object for each column in a merged range)
                    seen: list[str] = []
                    for cell in row.cells:
                        text = cell.text.strip().replace("\n", " ")
                        if not seen or text != seen[-1]:
                            seen.append(text)
                    row_text = " | ".join(c for c in seen if c)
                    if row_text:
                        blocks.append(row_text)
        return "\n\n".join(blocks)


class ExtractionManager:
    """
    Routes a local input through the correct extractor and writes a text file.

    Cancellation: pass ``cancelled=some_callable`` that returns True when the
    job should stop.  All inner extractors propagate the check.
    """

    def __init__(self, detector: InputDetector | None = None, writer: TextFileWriter | None = None) -> None:
        self.detector = detector or InputDetector()
        self.writer = writer or TextFileWriter()
        self.processor = TextProcessor()

    def extract_file(self, path: str | Path, cancelled: Callable[[], bool] | None = None) -> ExtractionResult:
        detected = self.detector.detect(path)
        image_ocr = ImageOCR()
        if detected.kind == "raster":
            text = image_ocr.extract_path(detected.path, cancelled=cancelled)
        elif detected.kind == "svg":
            text = SVGExtractor(image_ocr).extract(detected.path, cancelled=cancelled)
        elif detected.kind == "pdf":
            text = PDFTextExtractor(image_ocr).extract(detected.path, cancelled=cancelled)
        elif detected.kind == "docx":
            text = DOCXExtractor().extract(detected.path, cancelled=cancelled)
        else:
            raise UnsupportedInputError(f"Unsupported input kind: {detected.kind}")
        text = self.processor.normalize(text)
        if not text:
            raise ExtractionError("No printed or selectable text was found in this file.")
        output_path = self.writer.write(detected.path, text)
        return ExtractionResult(text=text, output_path=output_path, input_kind=detected.kind)
