# Verbum — Project Status: Finished Functionality & Current Tasks

> **Platform:** Windows 10/11 (64-bit)  
> **Framework:** Python 3 + PySide6 (Qt)  
> **Core Architecture:** 100% Local-First Desktop Productivity Suite (No data leaves the device)  
> **Last Updated:** October 2026

---

## 1. Executive Summary

**Verbum** (originally VoiceInput) is a local-first Windows desktop productivity application designed for privacy, speed, and offline capability. It integrates voice transcription, multi-format text extraction (OCR & document parsing), and neural machine translation into a modern Qt-based collapsible sidebar interface.

Every core engine operates locally without cloud dependencies:
- **Audio/Voice:** Local Whisper (`faster-whisper`)
- **Document/Image Extraction:** Local ONNX OCR (`rapidocr-onnxruntime`), `PyMuPDF`, `python-docx`, `xml.etree`
- **Translation:** Local quantized CTranslate2 M2M-100 model (`ctranslate2` + `sentencepiece` + `langdetect`)

---

## 2. Finished Works & Functionality Breakdown

### 2.1 Voice Transcription & Dictation
* **Engine:** OpenAI Whisper via `faster-whisper` (CTranslate2 inference engine).
* **Model Choices:** `tiny`, `base`, `small`, `medium` stored locally in `%LOCALAPPDATA%\VoiceInput\models` or repository `./models`.
* **Hybrid Hotkey System:**
  * **Push-to-Talk (Hold):** Holding `Ctrl + Space` (> 350 ms) records while pressed and transcribes immediately upon release.
  * **Toggle Mode (Tap):** Quick tap (< 350 ms) latches recording on; tapping again stops recording and transcribes.
  * Native Windows low-level keyboard hook (`SetWindowsHookExW`, `WH_KEYBOARD_LL`) running on an isolated thread.
  * Space key suppression during hotkey activation to avoid accidental language/IME switching.
* **Audio Features:**
  * Real-time microphone RMS level visualization (streaming to both desktop overlay and UI waveform widget).
  * Microphone device selection via `sounddevice` enumerating all hardware input devices.
  * Double-pass VAD (Voice Activity Detection) with automatic fallback if quiet speech was aggressively filtered.
* **Output Integration:**
  * Automatic clipboard copy (`pyperclip` / Qt clipboard).
  * Direct auto-paste into active Windows application via simulated keystrokes (`SendInput`).
  * Non-intrusive floating recording overlay with visual status indicators (`Recording`, `Transcribing`, `✓ Copied`, `✓ Pasted`, `No speech detected`).

---

### 2.2 Text Extraction & Multi-Format OCR
* **Engine:** RapidOCR (`rapidocr-onnxruntime`) powered by ONNX Runtime.
* **Supported File Types:**
  * **Images (`.png`, `.jpg`, `.jpeg`, `.bmp`, `.webp`, `.tiff`):** High-accuracy local OCR using pre-packaged ONNX models.
  * **PDFs (`.pdf`):** Dual-pass extraction — first extracts embedded digital text streams via `fitz` (`PyMuPDF`); renders high-DPI raster pages to ONNX OCR for scanned/image pages.
  * **Word Documents (`.docx`):** Native structure parsing with `python-docx` across paragraphs and tables.
  * **Vector Graphics (`.svg`):** Safe XML parsing extracting embedded text elements and paths.
* **Worker Process:** Isolated background worker (`app/extraction_worker.py`) keeping the main UI completely non-blocking during large batch OCR or document parsing.
* **UI Features:**
  * Drag-and-drop file drop zone.
  * Progress updates and error reporting.
  * Extracted text view with single-click copy and history recording.

---

### 2.3 Offline Multilingual Translation (Recently Implemented)
* **Model:** Facebook M2M-100 418M quantized to CTranslate2 int8 (`gn64/M2M100_418M_CTranslate2`, ~490 MB footprint).
  * **License review:** The upstream `facebook/m2m100_418M` model card and the installed conversion both declare the MIT license. The CTranslate2 runtime is MIT; `langdetect` is local and permissively licensed. The model remains outside version control in the local `models/` cache.
* **Tokenizer:** Local BPE tokenization via `sentencepiece`.
* **Language Identification:** Fast local language detection via `langdetect`.
* **Coverage:** 100 languages directly translated into natural English.
* **Key Capabilities:**
  * **100% Offline & Private:** Zero API keys, zero internet required once weights are cached.
  * **Dual Detection Modes:**
    * **Auto Mode:** Automatically detects input language with confidence scoring. If ambiguous or low-confidence, prompts user to select manually.
    * **Manual Mode:** Explicit source language selection from a searchable dropdown of all 100 supported languages.
  * **English Pass-Through:** If the source text is detected or selected as English, unnecessary neural translation is bypassed.
  * **Sentence Chunking:** Smart sentence-aware splitting (`_split_text`) preserving context across large paragraphs.
  * **Persistent Long-Lived Worker (`app/translation_worker.py`):**
    * Model remains cached in memory across translation tasks while the feature is active, eliminating repetitive ~1–2 second reload delays.
    * Communicates via `multiprocessing.Queue` protocol (`translate`, explicit `install`, `unload`, `shutdown`, `status`, `result`).
    * Cleanly unloads model and terminates worker process when Translation is toggled OFF in settings.
  * **Explicit model setup:** A missing model produces an actionable local setup state. Only the user-initiated **Install model** action may download the cache; normal translation never contacts a network service.
  * **Graceful CUDA & CPU Hardware Probing:**
    * Probes GPU initialization safely. If CUDA runtime DLLs (e.g., `cublas64_12.dll`) are absent or fail, gracefully falls back to CPU int8 execution without crashing.
  * **Job Cancellation:** User can cancel in-flight translations at any time via UI cancel buttons or queue events.

---

### 2.4 Modern UI & Application Shell
* **Window Design:** Frameless/styled modern desktop window built with PySide6 (Qt).
* **Collapsible Sidebar:**
  * Toggle between expanded view (icons + labels) and compact icon-only rail.
  * Smooth animations and active tab indicators.
* **Navigation Views:**
  1. **Capture:** Live audio transcription, real-time waveform visualizer, hotkey instructions, and quick results.
  2. **Extract Text:** Drag-and-drop file ingestion, OCR/document text extractor, and formatted output viewer.
  3. **Translate:** Multi-lingual translator to English, mode selector (Auto vs. Manual), swap controls, confidence feedback, and direct translation history.
  4. **Create Font:** Project-isolated glyph intake and vector font generation, validated version history, real generated-TTF preview, and local font export.
  5. **Create Files:** Multi-page rich-text editor, `.vdoc` persistence, PDF import, project-scoped generated TTF selection, formatting, lists/tables/images, pen annotation, and searchable rich-PDF export. Phase 3 acceptance remains partial; see the dated status update below.
  6. **History:** Unified central audit log categorizing past Voice, Extraction, and Translation entries (each with timestamps, source metadata, and one-click copy).
  7. **Settings:** Hotkey management, Whisper model selection, compute backend (`auto`, `cpu`, `cuda`), microphone input picker, startup with Windows toggle, auto-paste toggle, and feature enablement toggles.
* **System Tray & Lifecycle:**
  * Minimizes to system tray.
  * Single-instance mutex prevents duplicate instances from conflicting on global hotkeys.
  * Graceful shutdown hooks terminating all background worker subprocesses cleanly.

---

### 2.5 Test Suite & Quality Assurance
* **Full Automated Test Suite:** 56 unit and integration tests passing (`pytest tests/`).
* **Test Coverage Highlights:**
  * Language normalization, detection accuracy on diverse scripts (Arabic, Cyrillic, Devanagari, Japanese, Latin, Malayalam).
  * Worker process queue communication, status events, error propagation, and cancellation.
  * Hardware device probing and fallback paths.
  * PySide6 UI signals and HistoryPage integration.

---

### 2.4 Handwriting & Font Pipeline — Step 2: Automatic Glyph Extraction & Normalization
* **Goal:** Convert photographic character grid sheets into a clean, labeled, validated, and normalized 128×128 character image dataset.
* **Scope Boundary Enforced:** No OCR/HTR training, no font generation; pure dataset extraction, cleaning, normalization, and quality auditing. Raw sheets in `dataset/raw/` remain strictly immutable.
* **Extraction Toolchain (`tools/` & `tools/pipeline/`):**
  * `tools/pipeline/config.py`: Template schemas, character definitions, category mappings, safe folder names, multi-component specifications, and physical grid line anchors.
  * `tools/pipeline/image_io.py`: Non-destructive image loading with EXIF orientation auto-transposition.
  * `tools/pipeline/page_detector.py`: Tilt angle estimation and rotational deskewing (e.g., 1.37° affine deskew for 'z' strip).
  * `tools/pipeline/grid_detector.py`: Illumination normalization, morphological line filtering, projection profiles, and anchor-guided grid line lattice solver.
  * `tools/pipeline/cell_extractor.py`: Cell cropping with safe inset (4 px), perimeter component scrubbing, L-junction/frame line suppression, intelligent multi-component grouping ('i', 'j', ':', '()', '{}', '[]'), and noise speck rejection.
  * `tools/pipeline/normalizer.py`: Aspect-ratio-preserving proportional scaling, centering on 128×128 canvas, anti-aliased grayscale rendering with pure 255 background.
  * `tools/pipeline/quality_scorer.py`: Contrast evaluation, local bounding-box blur variance (Laplacian), perimeter clipping threshold, component sanity checks, and GOOD/REVIEW/REJECT classification.
  * `tools/pipeline/manifest.py`: Machine-readable CSV and JSON manifest serialization.
  * `tools/extract_glyphs.py`: Complete production-grade batch extraction CLI with `--all` or `--sheet` flags.
  * `tools/inspect_grid.py`: Visual debug overlay generator for grid validation (`dataset/processed/debug_inspect/`).
  * `tools/build_contact_sheet.py`: High-resolution visual QA contact sheet generator by category and flagged audit cards (`dataset/review/`).
  * `tools/eval_methods.py`: Empirical method comparison script benchmarked across illumination, grid detection, and suppression methods.
* **Dataset Extraction Results:**
  * **Total Raw Sheets Processed:** 6 (including newly photographed uppercase A–L sheet `media_1791228862843.jpg`)
  * **Total Expected Glyphs:** 966 (100% accounted for)
  * **Total Extracted Glyphs:** 966
    * **Uppercase:** 364 glyphs (26 characters A–Z × 14 samples each)
    * **Lowercase:** 364 glyphs (26 characters a–z × 14 samples each)
    * **Numbers:** 140 glyphs (10 digits 0–9 × 14 samples each)
    * **Punctuation / Symbols:** 98 glyphs (7 symbols: `. , : () {} [] -` × 14 samples each)
  * **Quality Audit Breakdown:**
    * **GOOD:** 913 glyphs (94.51%)
    * **REVIEW:** 53 glyphs (5.49% — softer focus/smooth ballpoint pen strokes on sheet 3 flagged for human audit)
    * **REJECT:** 0 glyphs (0.00%)
* **Artifacts & Quality Assurance:**
  * Manifests generated: `metadata/glyph_manifest.csv` and `metadata/glyph_manifest.json` (966 detailed records with bounding boxes, ink area, contrast, blur score, and review status).
  * High-resolution visual QA contact sheets in `dataset/review/`:
    * `contact_sheet_uppercase.png` (26 rows × 14 cols: full A through Z matrix)
    * `contact_sheet_lowercase.png` (26 rows × 14 cols: full a through z matrix)
    * `contact_sheet_numbers.png` (10 rows × 14 cols: 0 through 9 matrix)
    * `contact_sheet_punctuation.png` (7 rows × 14 cols: symbol matrix)
    * `contact_sheet_flagged_review.png` (53 review cards)
  * Grid inspection debug overlays in `dataset/processed/debug_inspect/grid_inspect_*.png`.

---

## 3. Current Task & Implementation Status

### 3.1 What Was Just Completed
1. **Handwriting Pipeline Step 2 (Automatic Glyph Extraction & Dataset Correction):**
   * Resolved missing uppercase A–L by ingesting and calibrating `media_1791228862843.jpg` (12 rows × 14 cols).
   * Resolved "i"-like artifact in Z / z_001 by fixing the vertical grid line anchor of the `z` strip (snapped to true paper boundary at x=22 rather than floral margin) and adding aspect-ratio perimeter safeguards.
   * Extracted all 966 characters across all 6 photographed sheets with 100% extraction rate and zero rejects.
   * Generated comprehensive visual QA contact sheets (full 26-row A–Z and a–z sheets) and machine-readable manifests (`glyph_manifest.csv` / `.json`).
   * Maintained 100% pass across all 65 automated tests in `pytest`.
2. **Architectural Transition to Persistent Translation Worker:**
   * Replaced one-off subprocess spawning with a long-lived `translation_worker.py` process.
   * Model weights remain warm in RAM while Translation is active, dropping repeat translation latency from ~2s to ~0.3–0.6s.
3. **Translation UI & History Integration:**
   * Added interactive mode selection (Auto Detect vs. Manual selection).
   * Wired "Select language manually" action button when language detection is unconfident.
   * Centralized translation entries into the global `HistoryPage` with badge tags (`Translation`, `Voice`, `Extraction`).
4. **Build & Spec Hardening:**
   * Updated `VoiceInput.spec` and `requirements.txt` to package `huggingface-hub`, `ctranslate2`, `sentencepiece`, and `langdetect`.
   * Verified local offline execution and test suite compliance.

### 2.4 Personal Handwriting Font Generator (Step 3 Completed)
* **Engine:** Custom vectorization & OpenType/TrueType builder (`app/font_generator.py`) using OpenCV Teh-Chin border following, Douglas-Peucker polygon reduction, and TrueType Quadratic Spline midpoint curve fitting (`qCurveTo`).
* **Typographical Coordinate Space:**
  * UnitsPerEm = 1000 (standard OpenType/TrueType em square).
  * Baseline Y = 0; Cap Height = 700; x-height = 490; Ascender = 720; Descender = -210.
  * Line Gap = 200; Default LSB = 55; Default RSB = 55; Space advance = 320.
* **Glyph Coverage & Table Construction:**
  * Full coverage across 69 character classes (26 uppercase A–Z, 26 lowercase a–z, 10 digits 0–9, 7 punctuation classes with paired brackets/parentheses/braces split into 10 distinct glyphs: `. , : - ( ) [ ] { }`).
  * Full TrueType tables via `fontTools.fontBuilder.FontBuilder`: `head`, `hhea`, `maxp`, `OS/2`, `name`, `cmap` (Format 4 Unicode BMP), `glyf`, `hmtx`, `post`.
  * OpenType CFF table generated for OTF export.
* **Generated Outputs:**
  * `fonts/Verbum_Handwriting.ttf` (TrueType Font, 20,412 bytes, 73 glyphs).
  * `fonts/Verbum_Handwriting.otf` (OpenType Font with CFF glyph outlines, 8,688 bytes).
  * `dataset/review/font_specimen_preview.png` (High-resolution specimen test sheet).
* **System & UI Integration:**
  * Verified Windows GDI registration (`AddFontResourceExW`) and Qt application font registration (`QFontDatabase.addApplicationFont`).
  * Non-blocking background worker (`app/font_worker.py`) with cancel support and progress updates.
  * UI page (`CreateFontPage`): Dataset statistics, progress bar, specimen display, live test input rendered in the personal handwriting font, and TTF/OTF export download buttons.

---

### 2.5 Handwritten Document & Searchable PDF Generator (Step 4 Completed)
* **Engine:** ReportLab Flowable document builder + PyMuPDF validation (`app/pdf_generator.py`).
* **True Vector Font Embedding:**
  * Embeds `Verbum_Handwriting.ttf` directly into the PDF font subset table (`AAAAAA+VerbumHandwriting-Regular`).
  * Text is 100% vector-based, crisp at any zoom level, fully selectable, searchable, and copyable. Zero raster page screenshot workarounds.
* **Layout & Pagination:**
  * Configurable margins, flowing paragraphs, automated line wrapping, and explicit page break support using `---` dividers.
  * Page preview rasterization using PyMuPDF Matrix rendering (`output/test_document_page_1_preview.png`).
  * Graceful handling of unsupported characters with transparent user notification.
* **Worker & UI Integration:**
  * Non-blocking background worker (`app/pdf_worker.py`) with cancel support and status queue.
  * UI page (`CreateFilesPage`): Document title input, multiline content editor, "Load sample text" preset, live page count badge, high-DPI page preview thumbnail, "Save PDF As..." file dialog, and "Open PDF" in native Windows viewer.

---

## 3. Current Task & Implementation Status

### 3.1 What Was Just Completed
1. **Handwriting Pipeline Step 3 (Font Generation / Glyph Vectorization):**
   * Implemented `app/font_generator.py` converting extracted 128x128 glyphs into standard TrueType (`.ttf`) and OpenType (`.otf`) fonts.
   * Tested and verified TrueType contour winding (Shoelace formula), midpoint B-spline fitting, and typographic metric baseline alignment.
   * Built multiprocessing worker `app/font_worker.py` and connected UI in `app/ui/main_window.py` and `app/main.py`.
   * Verified Qt live text rendering in `CreateFontPage`.
2. **Handwriting Pipeline Step 4 (Searchable/Selectable PDF Generation):**
   * Implemented `app/pdf_generator.py` using ReportLab to embed the custom vector handwriting font.
   * Verified with PyMuPDF: selectable, copyable text, embedded font subset verification, and page preview rendering.
   * Built multiprocessing worker `app/pdf_worker.py` and connected UI in `app/ui/main_window.py` and `app/main.py`.
   * Verified "Save PDF As..." and "Open PDF" system integration.
3. **Automated Unit Test Suite Expansion:**
   * Created `tests/test_font_generation.py` (8 test cases) and `tests/test_pdf_generation.py` (5 test cases).
   * Verified 100% pass across all 78 unit tests in `pytest`.
4. **Packaging & Dependencies:**
   * Updated `requirements.txt` with `fonttools>=4.66.0`, `reportlab>=5.0.0`, and `opencv-python>=4.9.0`.
   * Updated `VoiceInput.spec` with `fontTools` and `reportlab` hiddenimports and `collect_all`.

### 3.2 Current In-Progress / Next Tasks
1. **Packaging & PyInstaller Executable Verification:**
   * Build the standalone `.exe` using `build.bat` / PyInstaller and verify runtime bundling.

---

## 4. File Structure Reference

```text
Transcriber/
├── app/
│   ├── ui/
│   │   ├── icons.py               # Vector SVG icons & canvas painters
│   │   ├── main_window.py         # Main window, navigation, sidebar, TranslatePage, HistoryPage
│   │   ├── recording_overlay.py   # Floating desktop overlay for voice status & RMS meter
│   │   ├── settings_window.py     # Modal settings dialog
│   │   └── tray.py                # System tray icon and menu
│   ├── clipboard.py               # Clipboard manipulation & Windows SendInput auto-paste
│   ├── config.py                  # Dataclass configuration & JSON persistence
│   ├── extraction.py              # OCR & document parsing backend
│   ├── extraction_worker.py       # Subprocess worker for extraction/OCR
│   ├── font_generator.py          # Vectorizer and TTF/OTF builder
│   ├── font_worker.py             # Multiprocessing worker for font generation
│   ├── hotkey.py                  # Windows low-level keyboard hook (Ctrl+Space)
│   ├── main.py                    # Application controller, state management, worker bridges
│   ├── pdf_generator.py           # ReportLab searchable PDF builder & PyMuPDF validator
│   ├── pdf_worker.py              # Multiprocessing worker for PDF generation
│   ├── recorder.py                # Audio capture & RMS metering via sounddevice
│   ├── translation.py             # M2M-100 model provider, detector, tokenizer
│   ├── translation_worker.py      # Persistent background translation worker
│   └── worker.py                  # Whisper transcription worker
├── dataset/
│   ├── raw/                       # Immutable original handwriting photos (6 sheets)
│   ├── glyphs/                    # Normalized 128x128 character images (966 glyphs)
│   │   ├── uppercase/             # A-Z (26 characters x 14 variations)
│   │   ├── lowercase/             # a-z (26 characters x 14 variations)
│   │   ├── numbers/               # 0-9 (10 digits x 14 variations)
│   │   └── punctuation/           # . , : () {} [] - (7 symbols x 14 variations)
│   ├── review/                    # Flagged review samples, rejected, and contact sheets
│   └── processed/
│       └── debug_inspect/         # Visual grid overlay inspection images
├── fonts/                         # Generated TrueType and OpenType personal handwriting fonts
│   ├── Verbum_Handwriting.ttf     # Installable TrueType font with vector contours
│   └── Verbum_Handwriting.otf     # OpenType CFF personal handwriting font
├── metadata/
│   ├── glyph_manifest.csv         # Full CSV manifest with bounding boxes & metrics
│   └── glyph_manifest.json        # Full JSON manifest with dataset summaries
├── models/                        # Local model cache directory (Whisper & Translation)
├── output/                        # Generated PDF documents and page preview images
│   ├── test_document.pdf          # Multi-page test document embedding Verbum font
│   └── test_document_page_1_preview.png # High-DPI raster preview of document page 1
├── tests/
│   ├── test_autostart.py          # Windows autostart registry tests
│   ├── test_config.py             # App configuration tests
│   ├── test_extraction.py         # Extraction & OCR test cases
│   ├── test_font_generation.py    # Step 3 handwriting font generation unit tests
│   ├── test_glyph_extraction.py   # Step 2 glyph extraction pipeline unit tests
│   ├── test_hotkey.py             # Hotkey logic tests
│   ├── test_pdf_generation.py     # Step 4 searchable PDF generation unit tests
│   ├── test_transcriber.py        # Whisper transcription worker tests
│   └── test_translation.py        # M2M-100 translation, detector & worker tests
├── tools/
│   ├── pipeline/                  # Modular glyph extraction pipeline components
│   │   ├── cell_extractor.py      # Grid suppression, component clustering
│   │   ├── config.py              # Template schemas & physical grid anchors
│   │   ├── grid_detector.py       # Peak-snapping lattice solver
│   │   ├── image_io.py            # EXIF orientation & image loading
│   │   ├── manifest.py            # CSV / JSON manifest generator
│   │   ├── normalizer.py          # Proportional 128x128 centering
│   │   ├── page_detector.py       # Rotational deskewing
│   │   └── quality_scorer.py      # Contrast & blur quality assessment
│   ├── build_contact_sheet.py     # Contact sheet generator CLI
│   ├── eval_methods.py            # Empirical CV method comparative evaluation
│   ├── extract_glyphs.py          # Main batch extraction CLI
│   └── inspect_grid.py            # Grid visualization CLI
├── build.bat                      # PyInstaller build script for Windows
├── config.json                    # User preferences & recent history
├── requirements.txt               # Python package dependencies
├── VoiceInput.spec                # PyInstaller packaging spec
└── PROJECT_STATUS.md              # Current status, finished works & task tracker
```

---

## Phase 3 implementation update — 2026-10-09

**Status: PARTIALLY COMPLETE — further acceptance testing remains.**

Implemented in the local working tree:

- `app/document_model.py`: versioned `.vdoc` document model with multiple rich-HTML pages and atomic JSON replacement.
- `app/ui/main_window.py`: Create Files now has multi-page rich-text editors, undo/redo, save/open/save-as, dirty-state prompts, font family/size, bold/italic/underline, paragraph alignment, lists, tables, image insertion/resizing, basic nondestructive brightness/exposure/crop derivatives, pen annotation canvas, PDF import, and project-aware generated TTF selection.
- `app/rich_pdf_export.py`: Qt rich-document PDF export that preserves searchable text, rich HTML formatting, tables, images and page separation; generated TTFs are loaded privately and removed after export. Export writes to a temporary file, validates it, and only then replaces the destination.
- `app/pdf_worker.py` and `app/main.py`: the existing PDF worker accepts rich page HTML and a validated project/version font path.
- `VoiceInput.spec` and `build.bat`: package Qt Print Support and keep the PyInstaller cache within `.tmp`.
- `tests/test_document_model.py` and `tests/test_rich_pdf_export.py`: persistence, atomic save, malformed input, rich multi-page PDF, selectable text, font embedding, image/table output, standard-font export, and worker coverage.

Validation recorded so far:

- Baseline before Phase 3 edits: **98 passed**.
- Document model, PDF worker, UI contract targeted tests: passed during development.
- Rich PDF export tests: **5 passed** (multi-page formatting/table/list, image, standard-font fallback, safe failure, existing worker).
- Offscreen Create Files smoke test: passed for project-font discovery/selection, two-page editing and `.vdoc` save/reopen, text-PDF import, and scanned-PDF visual fallback.
- Rich PDF export independently reopened with PyMuPDF; selectable text and embedded Verbum font were confirmed in the generated-font test.
- Final Python syntax compilation: passed.
- Final full regression suite after the latest UI/export/signal changes: **107 passed, 0 failed**.
- Final offscreen Create Files smoke test: passed for active-project font selection, multi-page editing and `.vdoc` save/reopen, editable text-PDF import, and scanned-page image fallback.
- MainWindow signal smoke test: passed; PDF export forwards all four arguments (title, plain text, selected font path, rich HTML pages). Pen canvas image save smoke test passed.
- `build.bat` completed successfully using the project-local PyInstaller cache, work directory, and staging output. Staged executable: `.tmp/dist_phase3/VoiceInput/VoiceInput.exe`. Verified that `QtPrintSupport` and all three OCR model groups are present in the package.
- Attempted to launch the staged EXE with its user data redirected into `.tmp`; the existing global single-instance mutex routed/closed the launch while the two existing `dist/VoiceInput/VoiceInput.exe` processes remained running. I did not terminate those user processes. Therefore a fresh interactive packaged-UI session remains unverified.

Known limitations / remaining work:

- PDF import reconstructs extractable text as editable text; scanned pages are preserved as image fallbacks and warned as non-editable. Complex mixed PDFs do not yet guarantee faithful reconstruction of every drawing, form, or table.
- Image manipulation creates new local derivative assets, preserving the original source. The annotation canvas inserts a raster annotation image; strokes are not individually editable after insertion.
- Document HTML stores local image asset references, so moving a `.vdoc` together with no matching local assets may break image resolution.
- Font embedding is validated for the generated Verbum TTF path on this machine; the standard-font fallback and rich export tests also pass. Mixed personal-font families in one document, uncommon PDF structures, and broad interactive testing need further validation.
- The provided `VERBUM_FULL_PROJECT_MASTER_SPEC.md` was available as a conversation attachment but was not present in the checked-out project root, so this update is recorded here rather than fabricating a replacement master file.
