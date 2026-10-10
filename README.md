# Voice Input

Windows tray utility for local, push-to-talk transcription. Hold **Ctrl + Space**, speak, then release. The result is copied to the clipboard; it is never auto-pasted.

## Run

```powershell
.\.venv\Scripts\python.exe main.py
```

The model is loaded only after recording ends, in a separate process. It is released as soon as transcription finishes, keeping idle CPU/GPU use low. The first use may download the chosen local Whisper model.

To launch automatically after you sign in to Windows, open the tray icon's **Settings**, enable **Start with Windows**, and save. This creates a per-user Windows startup entry; no administrator permission is needed.

The Settings window also has an image picker (the selected image is saved for later processing) and shows the five most recent completed transcriptions.

Voice Input opens to a desktop control centre. Closing that window hides it to the system tray while recording and transcription continue in the background. Use the tray icon or **Open Voice Input** from its menu to restore the window; choose **Exit** to stop the app.

Whisper starts loading as soon as you begin a recording and remains loaded in a background worker for later recordings. If model loading, transcription, or the worker fails, the app shows an error instead of waiting indefinitely.

## Local translation

The **Translate** page translates supported source languages into English entirely on-device. It uses the MIT-licensed Meta `facebook/m2m100_418M` model in a CTranslate2 int8 cache and the local `langdetect` package for language identification. The installed model cache is about 473 MiB (495,891,833 bytes in the current development cache); it is excluded from Git.

If the model is absent, select **Install model** explicitly on the Translate page. That one-time setup is the only translation path that contacts the model host. A normal Translate action never downloads anything and works offline after setup. Turning Translation off terminates its worker and releases the warm model.

## Build

```powershell
.\.venv\Scripts\pyinstaller.exe --noconfirm --clean --windowed --name VoiceInput --collect-all faster_whisper main.py
```

The executable will be at `dist\VoiceInput\VoiceInput.exe`.

## Handwriting Glyph Extraction Pipeline (Step 2)

Verbum includes a high-precision computer vision toolchain for extracting, cleaning, and normalizing handwritten character datasets from photographed grid sheets into standard 128×128 grayscale glyphs.

### Extract All Glyphs

Extract all characters across all 6 raw handwriting sheets, score quality, and automatically generate visual QA contact sheets and manifests:

```powershell
.\.venv\Scripts\python.exe tools/extract_glyphs.py --all
```

Or extract a specific sheet:
```powershell
.\.venv\Scripts\python.exe tools/extract_glyphs.py --sheet media_1791224864942.jpg
```

### Visual Grid Inspection

Render detected cell lattices, row/column boundaries, and character mappings over the rectified input images:

```powershell
.\.venv\Scripts\python.exe tools/inspect_grid.py --all
```
Outputs are saved to `dataset/processed/debug_inspect/grid_inspect_*.png`.

### Generate QA Contact Sheets

Build categorized visual audit grids and a flagged review sheet:

```powershell
.\.venv\Scripts\python.exe tools/build_contact_sheet.py
```
Outputs are saved to `dataset/review/`:
- `contact_sheet_uppercase.png` (26 characters × 14 variations)
- `contact_sheet_lowercase.png` (26 characters × 14 variations)
- `contact_sheet_numbers.png` (10 digits × 14 variations)
- `contact_sheet_punctuation.png` (7 symbols × 14 variations)
- `contact_sheet_flagged_review.png` (Audit sheet of low-contrast or blurred samples)

### Empirical Method Benchmark

Run benchmark comparisons between thresholding, grid detection, and suppression algorithms:

```powershell
.\.venv\Scripts\python.exe tools/eval_methods.py
```

### Run Extraction Unit Tests

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_glyph_extraction.py
```
