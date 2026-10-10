# Verbum (Voice Input) — Complete Project Documentation

> **Current Version: Verbum (v6+)** | **Platform: Windows 10/11 (64-bit)** | **Language: Python 3.14**

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Feature List & Capabilities](#2-feature-list--capabilities)
3. [Architecture and How It Works](#3-architecture--how-it-works)
4. [File and Folder Structure](#4-file--folder-structure)
5. [Module Reference](#5-module-reference)
6. [Configuration Reference](#6-configuration-reference)
7. [UI Reference](#7-ui-reference)
8. [How to Build (Development & Executable)](#8-how-to-build-development-to-executable)
9. [Handwriting Glyph Extraction Pipeline](#9-handwriting-glyph-extraction-pipeline)
10. [Version History](#10-version-history)
11. [Known Issues Fixed in v6](#11-known-issues-fixed-in-v6)
12. [Dependencies](#12-dependencies)
13. [Logs and Debugging](#13-logs--debugging)

---

## 1. Project Overview

**Verbum** (originally Voice Input) is a 100% private, local-first Windows desktop productivity suite.
It provides local voice transcription, multi-format text extraction (OCR & document parsing), offline neural machine translation to English, and an automated handwriting glyph extraction pipeline. All processing runs completely on-device without telemetry or cloud calls.


### Core Concept

| Step | What Happens |
|------|-------------|
| 1 | User presses Ctrl + Space |
| 2 | Microphone starts recording |
| 3 | User releases or taps again Ctrl + Space |
| 4 | Audio is sent to background Whisper worker |
| 5 | Transcribed text is copied to clipboard and/or pasted at cursor |
| 6 | Overlay flashes confirmation; app returns to idle |

---

## 2. Feature List & Capabilities
 
### Voice Transcription
- 100% local and offline — Whisper runs on your machine, zero cloud calls
- Whisper model selector: tiny, base, small, medium (more accurate = slower to load)
- Language selector: auto (auto-detect) or en (force English)
- Device selector: auto (CPU), cpu, or cuda (NVIDIA GPU acceleration)
- VAD fallback: If Whisper VAD filters out quiet speech, a second pass runs without VAD to catch it
- CUDA fallback: If GPU is selected but CUDA runtime DLLs are missing, worker silently falls back to CPU/int8
 
### Hotkey System (Hybrid Push-to-Talk + Toggle)
- Hold mode (Push-to-Talk): Hold Ctrl+Space for more than 350ms, records while held, transcribes on release
- Tap mode (Toggle): Quick tap under 350ms latches recording ON; tap again to stop and transcribe
- Implemented with a native Windows low-level keyboard hook (SetWindowsHookExW, WH_KEYBOARD_LL) on its own dedicated thread
- Space key is suppressed while Ctrl+Space is active to prevent accidental input-language switches
 
### Output Options
- Copy to clipboard (default): transcript text goes to your clipboard
- Auto-paste: after copying, simulates Ctrl+V to paste directly into the active application at cursor position
 
### Text Extraction & Multi-Format OCR
- RapidOCR (ONNX Runtime) for images (`.png`, `.jpg`, `.jpeg`, `.bmp`, `.webp`, `.tiff`)
- Dual-pass PDF parsing: digital text stream via PyMuPDF (`fitz`), falling back to ONNX OCR for scanned pages
- Word documents (`.docx`) paragraph and table extraction via `python-docx`
- Vector SVG text extraction via XML parser
- Non-blocking background worker (`app/extraction_worker.py`)
 
### Local Multilingual Translation (M2M-100)
- Local CTranslate2 int8 quantized Meta `facebook/m2m100_418M` model
- 100 languages directly translated into English with local `langdetect` detection
- Long-lived persistent background worker (`app/translation_worker.py`) caching weights in RAM
- Auto detect and manual language selection modes
- Zero cloud reliance; fully offline once weights are present
 
### Modern UI & Desktop Experience
- Modern collapsible sidebar navigation (expanded icons+labels or compact rail)
- Distinct pages: Capture, Extract Text, Translate, Create Font, Create Files, History, Settings
- System tray integration with background minimization
- Animated floating recording overlay with live status feedback
- Unified History page tracking Voice, Extraction, and Translation events
 
### System
- Single-instance mutex: Only one copy of VoiceInput.exe can run at a time (CreateMutexW)
- Windows startup: optional registry entry under HKCU Software Microsoft Windows CurrentVersion Run
- Pre-warmed Whisper worker on application start
- Isolated worker processes for CPU/memory separation


---

## 3. Architecture and How It Works

### Process Layout

VoiceInput.exe / Verbum (main process) contains:
- Qt Event Loop (main thread) with `VoiceInputApp` controller, `MainWindow` (collapsible navigation tabs: Capture, Extract, Translate, Font, Files, History, Settings), `RecordingOverlay`, `SettingsWindow`, `Tray`
- `VoiceInputHotkey` (daemon thread) with Windows message loop and native `WH_KEYBOARD_LL` hook
- Whisper Worker (separate OS process, daemon) with `faster-whisper` WhisperModel loaded in RAM
- Extraction Worker (separate OS subprocess) executing RapidOCR and document parsers off-thread
- Translation Worker (separate OS long-lived persistent process) keeping quantized M2M-100 model in RAM

### Data Flow

1. **Voice Dictation**:
   - Keyboard Hook Thread: `Ctrl+Space` down fires `pressed` signal via `HotkeyBridge`
   - Qt Main Thread `start_recording`: `Recorder.start()` opens sounddevice `InputStream` at 16kHz float32 mono
   - Keyboard Hook Thread: `Ctrl+Space` up or second tap fires `released` signal
   - Qt Main Thread `stop_recording`: `Recorder.stop()` concatenates numpy chunks, sends to Whisper worker via Queue
   - Worker Process `_run`: `WhisperModel.transcribe` with `vad_filter=True`, fallback without VAD if empty, puts result on queue
   - Qt Main Thread `poll_worker` (100ms QTimer): reads result, updates history/config, updates UI, copies to clipboard and/or auto-pastes
2. **Document / OCR Extraction**:
   - Files dropped into `ExtractPage` -> queued to `extraction_worker.py`
   - PDF digital text extracted via `PyMuPDF` (`fitz`); scanned pages parsed via `RapidOCR`
   - Word (`.docx`) parsed via `python-docx`; SVGs parsed via XML text node traversal
   - Results emitted back to UI and recorded into `HistoryPage`
3. **Neural Machine Translation**:
   - Source text entered on `TranslatePage` -> queued to `translation_worker.py`
   - Language identified via `langdetect` (or chosen manually)
   - Translated to English via int8 quantized `facebook/m2m100_418M` on CTranslate2
   - Cached warm model provides sub-second repeat translations

### Worker Lifecycle

- Whisper: `ensure_worker()` called on app start for pre-warming. Worker loop reads command queue and transcribes.
- Translation: `ensure_translation_worker()` spawns long-lived worker when translation is enabled; model stays resident until disabled or app exit.
- Extraction: Dispatches jobs asynchronously without blocking Qt rendering.

### HotkeyBridge

The keyboard hook lives on a non-Qt thread. Direct Qt UI calls from non-Qt threads crash the app.
`HotkeyBridge` is a QObject with two signals: `pressed` and `released`.
The hook callbacks call `signal.emit()` which Qt safely marshals to the main thread via `QueuedConnection`.

---

## 4. File and Folder Structure

```text
c:/Projects/Transcriber/
├── main.py                    # Entry point, calls app.main.run()
├── requirements.txt           # Python dependencies
├── VoiceInput.spec            # PyInstaller build spec
├── config.json                # User config (auto-created, JSON)
├── build.bat                  # PyInstaller Windows build script
├── PROJECT_DOCS.md            # Complete project documentation
├── PROJECT_STATUS.md          # Current project status and task tracker
├── README.md                  # Project overview and instructions
│
├── app/
│   ├── main.py                # VoiceInputApp controller + run()
│   ├── config.py              # Config dataclass + JSON persistence
│   ├── hotkey.py              # Native WH_KEYBOARD_LL low-level hook
│   ├── recorder.py            # 16kHz sounddevice microphone recorder
│   ├── transcriber.py         # Whisper model loader + transcribe logic
│   ├── worker.py              # Multiprocessing Whisper worker process
│   ├── extraction.py          # RapidOCR & document parsing (PDF, DOCX, SVG)
│   ├── extraction_worker.py   # Subprocess worker for extraction/OCR
│   ├── translation.py         # M2M-100 model loader & tokenizer logic
│   ├── translation_worker.py  # Persistent background translation worker
│   ├── clipboard.py           # copy_text() + paste_text() via SendInput
│   ├── autostart.py           # Windows registry startup entry
│   └── ui/
│       ├── icons.py           # Vector SVG icons & canvas painters
│       ├── main_window.py     # Main window with sidebar navigation
│       ├── recording_overlay.py # Floating recording indicator widget
│       ├── settings_window.py # Modal settings dialog
│       └── tray.py            # System tray icon and menu
│
├── dataset/
│   ├── raw/                   # Immutable original handwriting photos (6 sheets)
│   ├── glyphs/                # Normalized 128x128 character images (966 glyphs)
│   │   ├── uppercase/         # A-Z (26 characters x 14 variations)
│   │   ├── lowercase/         # a-z (26 characters x 14 variations)
│   │   ├── numbers/           # 0-9 (10 digits x 14 variations)
│   │   └── punctuation/       # . , : () {} [] - (7 symbols x 14 variations)
│   ├── review/                # Contact sheets and flagged review samples
│   └── processed/
│       └── debug_inspect/     # Visual grid overlay inspection images
│
├── metadata/
│   ├── glyph_manifest.csv     # Full CSV manifest with bounding boxes & metrics
│   └── glyph_manifest.json    # Full JSON manifest with dataset summaries
│
├── tools/
│   ├── pipeline/              # Modular glyph extraction pipeline components
│   │   ├── cell_extractor.py  # Grid suppression, component clustering
│   │   ├── config.py          # Template schemas & physical grid anchors
│   │   ├── grid_detector.py   # Peak-snapping lattice solver
│   │   ├── image_io.py        # EXIF orientation & image loading
│   │   ├── manifest.py        # CSV / JSON manifest generator
│   │   ├── normalizer.py      # Proportional 128x128 centering
│   │   ├── page_detector.py   # Rotational deskewing
│   │   └── quality_scorer.py  # Contrast & blur quality assessment
│   ├── build_contact_sheet.py # Contact sheet generator CLI
│   ├── eval_methods.py        # Empirical CV method comparative evaluation
│   ├── extract_glyphs.py      # Main batch extraction CLI
│   └── inspect_grid.py        # Grid visualization CLI
│
├── tests/                     # Automated test suite (pytest: 65 tests passing)
│   ├── test_autostart.py
│   ├── test_config.py
│   ├── test_extraction.py
│   ├── test_glyph_extraction.py
│   ├── test_hotkey.py
│   ├── test_transcriber.py
│   └── test_translation.py
│
├── release-v6/                # Executable release build
│   └── VoiceInput/
│       └── VoiceInput.exe     # The compiled executable
└── models/                    # Local model cache (excluded from git)
```

---

## 5. Module Reference

### app/main.py — Controller

HotkeyBridge(QObject)
 Signals: pressed, released
 Thread-safe bridge between the keyboard hook thread and the Qt event loop

VoiceInputApp(QObject)
 Central controller. Owns config, recorder, worker, all UI, and the hotkey.
 Key methods:
 - ensure_worker() — starts worker process if not alive
 - start_recording() — opens microphone stream, shows overlay
 - stop_recording() — captures audio, sends to worker, shows Transcribing
 - poll_worker() — 100ms QTimer, reads result queue, updates UI
 - handle_worker_message() — dispatches ready, startup_error, result messages
 - handle_worker_failure() — tears down worker, shows error, auto-recovers to IDLE
 - finish_worker() — gracefully shuts down worker process
 - settings_saved() — restarts worker if settings changed
 - shutdown() — full app teardown

run()
 1. mp.freeze_support() first (required for PyInstaller multiprocessing)
 2. CreateMutexW single-instance check
 3. File logging to %LOCALAPPDATA%\VoiceInput\logs\voice-input.log
 4. Creates QApplication and VoiceInputApp, enters event loop

---

### app/hotkey.py — Global Hotkey

PushToTalkHotkey
 Uses SetWindowsHookExW(WH_KEYBOARD_LL) — a low-level keyboard hook that intercepts all keystrokes system-wide.
 Runs on a dedicated daemon thread with its own Windows message loop (GetMessageW).
 Tracks _ctrl and _space boolean state independently.
 
 Hybrid tap/hold logic:
 - Press both Ctrl+Space: record press time
 - On key-up if held under 350ms: latch (stay recording, _latched = True)
 - On key-up if held 350ms or more: fire on_release immediately (push-to-talk)
 - While latched: next Ctrl+Space press fires on_release (toggle off)
 
 Stop: PostThreadMessageW(WM_APP_STOP) gracefully ends the message loop.
 Space keystrokes are suppressed while Ctrl is held.

---

### app/recorder.py — Audio Capture

Recorder
 sample_rate = 16000 Hz, mono, float32 — exactly what Whisper expects.
 start(): opens sounddevice.InputStream, collects numpy chunks via callback.
 stop(): closes stream, concatenates all chunks into one flat numpy array.
 Thread-safe chunk collection via threading.Lock.
 Returns np.empty(0) if nothing captured.

---

### app/transcriber.py — Whisper Interface

resolve_runtime(device, compute_type)
 auto device resolves to cpu with int8 compute (reliable, no GPU DLL requirements).
 cuda device with auto compute resolves to float16.

load_model(model_name, device, compute_type)
 Loads faster_whisper.WhisperModel. First run downloads model files to Hugging Face cache.

transcribe_loaded_model(model, audio, language)
 First pass: vad_filter=True (Voice Activity Detection strips silence).
 If result is empty: second pass with vad_filter=False (catches quiet speech).
 Returns stripped text string.

---

### app/worker.py — Background Process

_run(settings, commands, results) - runs in child process:
 1. load_model() with configured device
 2. If CUDA: test-transcribe a silent array; if exception, reload on CPU
 3. Send (ready, ) on results queue
  4. Loop: commands.get() blocking then transcribe_loaded_model() then results.put()
  5. None command triggers clean exit
  6. All transcription exceptions are caught and returned as error results

start_worker(settings)
  Spawns the process, returns (process, commands_queue, results_queue).

---

### app/clipboard.py — Text Output

copy_text(text)
  pyperclip.copy(text) — puts text on clipboard.

paste_text(text)
  1. pyperclip.copy(text) — put text on clipboard
  2. time.sleep(0.05) — wait for physical Ctrl+Space keys to be released
  3. Simulate Ctrl+V using Windows SendInput API with KEYBDINPUT structs
  4. Pastes into whatever window currently has focus

---

### app/extraction.py & app/extraction_worker.py — Text Extraction & OCR

- RapidOCR integration for image OCR (`.png`, `.jpg`, `.jpeg`, `.bmp`, `.webp`, `.tiff`).
- Multi-format document parser:
  - `.pdf`: Digital text extraction using `PyMuPDF` (`fitz`), automatic OCR fallback for scanned pages.
  - `.docx`: Paragraph and table text extraction using `python-docx`.
  - `.svg`: XML parsing extracting embedded text nodes.
- Background worker execution (`app/extraction_worker.py`) keeping the UI thread responsive during heavy OCR.

---

### app/translation.py & app/translation_worker.py — Offline Neural Machine Translation

- Local CTranslate2 int8 model (`facebook/m2m100_418M`).
- Tokenizer: `sentencepiece` BPE tokenizer.
- Language identification: `langdetect` with confidence score.
- Auto & manual source language selection with 100 language coverage.
- Long-lived persistent worker process (`app/translation_worker.py`) maintaining warm model weights in memory.
- Safe CUDA initialization with graceful CPU fallback.

---

### app/config.py — Persistent Settings

Config dataclass fields:
  hotkey                  list[str]   [ctrl, space]   Fixed, not user-changeable
  model                   str         small           Whisper model size
  language                str         auto            Transcription language
  device                  str         auto            Inference device
  compute_type            str         auto            CTranslate2 quantization
  microphone              str         default         Input device name
  auto_copy               bool        True            Copy transcript to clipboard
  auto_paste              bool        False           Also paste at cursor
  sound_feedback          bool        False           Reserved, not yet used
  start_with_windows      bool        False           Registry startup entry
  image_path              str         ""              Reference image path
  voice_history           list        []              Last 5 voice transcripts
  extraction_history      list        []              Last 5 extraction entries
  font_history            list        []              Last 5 font entries
  files_history           list        []              Last 5 files entries
  translation_history     list        []              Last 5 translation records
  enable_extraction       bool        True            Enable Extract feature
  enable_font             bool        False           Enable Font feature
  enable_files            bool        False           Enable Files feature
  enable_translation      bool        False           Enable Translation feature
  translation_detect_mode str         "auto"          "auto" | "manual"
  translation_source_lang str         "fr"            ISO code used in manual mode
  sidebar_collapsed       bool        False           Sidebar state
  recent_transcriptions   list        []              Legacy field synced with voice_history

Config file location:
  Frozen EXE: %LOCALAPPDATA%\VoiceInput\config.json
  Development: project_root\config.json

add_voice_history(text): prepends text, keeps last 5, saves immediately.
add_extraction_history(text, label): prepends extraction result, keeps last 5, saves immediately.
add_translation_history(source_lang, source_name, original, translated): prepends translation record, keeps last 5, saves immediately.


---

### app/autostart.py — Windows Startup

Writes/removes registry key at:
HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run\VoiceInput
Value is the full path to the executable. Uses HKCU so no admin rights are needed.

---

### app/ui/main_window.py — Main Window & Navigation

MainWindow(QMainWindow) features a modern desktop layout with collapsible sidebar navigation:
- **Collapsible Sidebar**:
  - Expanded mode (icons + labels) and compact icon-only rail mode.
  - Page selectors: Capture, Extract Text, Translate, Create Font, Create Files, History, Settings.
- **Pages**:
  - **CapturePage**: Status indicator, waveform/RMS visualizer, push-to-talk / toggle hotkey guide, and latest transcript display.
  - **ExtractPage**: File drop zone (PDF, DOCX, SVG, PNG, JPG, WEBP), progress bar, formatted extraction output, and copy button.
  - **TranslatePage**: Source text input, Auto / Manual language selection (100 languages), swap controls, confidence indicator, and instant translation to English.
  - **FontPage**: Project-aware glyph intake, generation/version history, generated-font specimen, live handwriting preview, and font export.
  - **FilesPage / Create Files**: Multi-page rich-text editor, atomic `.vdoc` save/open, PDF import with scanned-page visual fallback, standard and active-project generated TTF selection, text/paragraph formatting, lists, tables, images with nondestructive adjustment, pen annotation image insertion, and rich searchable PDF export through the existing background worker.
  - **HistoryPage**: Unified chronological feed of all past Voice, Extraction, and Translation operations with badge filters, timestamps, and copy actions.
  - **SettingsPage / SettingsWindow**: Complete preference management (Whisper model, audio device, autostart, auto-paste, feature toggles).


---

### app/ui/recording_overlay.py — Floating Indicator

RecordingOverlay: Frameless, always-on-top, non-focusable Qt window.
Transparent background with dark rounded rectangle.
Pulse widget: custom paintEvent, animated radius via QPropertyAnimation (8-16px, 650ms, InOutSine, infinite loop).
Positions itself at horizontal center, 70px above taskbar.
States: show_recording (red dot animating + Recording), show_processing (static + Transcribing...), hide_overlay.
Text updated externally: check Pasted, check Copied, No speech detected.

---

### app/ui/settings_window.py — Settings Form

QFormLayout with fields for all Config fields.
Microphone dropdown populated live from sounddevice.query_devices().
Image picker via QFileDialog.
On save: updates self.config fields in-place, calls config.save(), emits saved signal.
saved signal triggers app.settings_saved() which refreshes UI and restarts worker if needed.

---

### app/ui/tray.py — System Tray

Uses QSystemTrayIcon with a standard Qt media-play icon.
Menu: Status (disabled label), Open, Settings, About, Exit.
set_status(status, detail): updates tooltip; shows balloon notification for detail messages.
Single-click or double-click on tray icon opens main window.

---

## 6. Configuration Reference

Config is stored as plain JSON (`config.json` in root during development, or `%LOCALAPPDATA%\VoiceInput\config.json` in frozen EXE).

Default configuration schema:
```json
{
  "hotkey": ["ctrl", "space"],
  "model": "small",
  "language": "auto",
  "device": "auto",
  "compute_type": "auto",
  "microphone": "default",
  "auto_copy": true,
  "auto_paste": false,
  "sound_feedback": false,
  "start_with_windows": false,
  "image_path": "",
  "voice_history": [],
  "extraction_history": [],
  "font_history": [],
  "files_history": [],
  "translation_history": [],
  "enable_extraction": true,
  "enable_font": false,
  "enable_files": false,
  "enable_translation": false,
  "translation_detect_mode": "auto",
  "translation_source_lang": "fr",
  "sidebar_collapsed": false,
  "recent_transcriptions": []
}
```

### Model Performance Guide

| Model | Size | Speed | Accuracy | VRAM (CUDA) |
|--------|--------|-------------|----------|-------------|
| tiny | ~75MB | Very fast | Low | ~1GB |
| base | ~145MB | Fast | OK | ~1GB |
| small | ~465MB | Medium | Good | ~2GB |
| medium | ~1.5GB | Slow | Best | ~5GB |

### Device Guide

| Setting | Behaviour |
|---------|-----------|
| auto | Uses CPU with int8 quantization (safest, no driver requirements) |
| cpu | Explicit CPU, uses compute_type setting |
| cuda | Tries NVIDIA GPU; falls back to CPU if CUDA DLLs are missing |


---

## 7. UI Reference

### States and Colors

| State | Color | Trigger |
|---------------|----------|---------|
| IDLE | Blue | App start, after result shown |
| RECORDING | Red | Ctrl+Space pressed |
| TRANSCRIBING | Yellow | Audio sent to worker |
| SUCCESS | Green | Transcription returned text |
| ERROR | Red | Any failure |

### Keyboard Shortcuts

| Shortcut | Action |
|----------------------------------|--------|
| Ctrl+Space tap under 350ms | Toggle recording ON; tap again to stop |
| Ctrl+Space hold 350ms or more | Push-to-talk; release to transcribe |

---

## 8. How to Build (Development to Executable)

### Prerequisites

- Python 3.14 (or Python 3.10+)
- Windows 10 or 11 (64-bit)

### Setup First Time

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Run in Development Mode

```powershell
.\.venv\Scripts\python.exe main.py
```

### Run Tests

Run the full automated test suite (65 passing unit and integration tests):

```powershell
.\.venv\Scripts\python.exe -m pytest tests/
```

### Build the Executable

Use the provided build batch script or PyInstaller directly with `VoiceInput.spec`:

```powershell
.\build.bat
```

Or via PowerShell:
```powershell
.\.venv\Scripts\pyinstaller.exe --noconfirm --clean VoiceInput.spec
```

`VoiceInput.spec` automatically bundles runtime binaries and assets for:
- `faster_whisper`
- `ctranslate2`
- `rapidocr_onnxruntime`
- `pymupdf`
- `python-docx`
- `sentencepiece`
- `langdetect`
- `huggingface_hub`

Output location: `dist\VoiceInput\VoiceInput.exe`

### Deploy to Release Folder

```powershell
robocopy dist\VoiceInput release-v6\VoiceInput /E /PURGE /IS /IT
```

### Important Build Notes

- `mp.freeze_support()` must be the very first call in `run()` for multiprocessing to work in frozen exe
- The single-instance mutex check comes immediately after `freeze_support()` so duplicate launches exit instantly
- All dynamic dependencies and model runtimes are declared in `VoiceInput.spec`
- The worker processes inherit the frozen executable module path via PyInstaller's `pyi_rth_multiprocessing` hook

---

## 9. Handwriting Glyph Extraction Pipeline

Verbum includes a high-precision computer vision pipeline in `tools/` and `tools/pipeline/` for converting photographed handwriting grid sheets into standard 128×128 grayscale character images.

### Pipeline Stages

1. **Orientation & Loading (`image_io.py`)**: Loads images non-destructively, correcting camera EXIF orientation flags.
2. **Deskewing (`page_detector.py`)**: Estimates tilt angle and applies rotational deskewing (e.g., 1.37° affine correction).
3. **Lattice Solving (`grid_detector.py`)**: Morphological line filtering and anchor-guided peak snapping against physical grid lines.
4. **Component Extraction (`cell_extractor.py`)**: Crops cells with safe inset padding, removes border intersections / L-junctions, and intelligently groups multi-stroke characters (`i`, `j`, `:`, `()`, `{}`).
5. **Centering & Normalization (`normalizer.py`)**: Scales characters proportionally, centering on a 128×128 canvas with pure 255 background.
6. **Quality Scoring (`quality_scorer.py`)**: Computes ink contrast, edge blur (Laplacian variance), bounding-box margin sanity, and categorizes into GOOD, REVIEW, or REJECT.
7. **Manifests (`manifest.py`)**: Serializes full metadata into `metadata/glyph_manifest.csv` and `metadata/glyph_manifest.json`.

### CLI Commands

- **Extract all sheets:**
  ```powershell
  .\.venv\Scripts\python.exe tools/extract_glyphs.py --all
  ```
- **Inspect grid lattices:**
  ```powershell
  .\.venv\Scripts\python.exe tools/inspect_grid.py --all
  ```
- **Generate QA contact sheets:**
  ```powershell
  .\.venv\Scripts\python.exe tools/build_contact_sheet.py
  ```
- **Run CV method benchmarks:**
  ```powershell
  .\.venv\Scripts\python.exe tools/eval_methods.py
  ```
- **Run glyph unit tests:**
  ```powershell
  .\.venv\Scripts\python.exe -m pytest tests/test_glyph_extraction.py
  ```

---

## 10. Version History


| Version | Key Changes |
|--------------|-------------|
| v6 (current) | Hybrid tap/hold hotkey; auto-paste via SendInput; CUDA DLL fallback fix; VAD fallback for quiet speech; live history update fix; Clear history and Clear image buttons; single-instance mutex; pre-warmed worker on startup; live microphone dropdown in settings |
| v5 | Persistent worker process; history panel; reference image; settings overhaul; Windows startup |
| v4 | System tray; background mode; recording overlay with animation |
| v3 | Settings window; model/language/device selector; auto-copy |
| v2 | PySide6 UI; config file persistence; sounddevice recorder |
| v1/release | Initial Whisper integration; basic hotkey; push-to-talk |

---

## 11. Known Issues Fixed in v6

### Bug: Whisper stopped before returning a result
Root cause: poll_worker() ran every 100ms and called worker.is_alive(). When the worker process was freshly
spawned for pre-warming on startup, is_alive() returned False for a brief window during process startup,
triggering a false positive failure.
Fix: Added guard so handle_worker_failure only fires if pending_request_id is set (transcription in
progress) OR worker_state is READY (was already confirmed alive).

### Bug: History not updating after transcription
Root cause: refresh_config() called Config.load() which created a new Config object and stored it in
main_window.config, breaking the shared reference with app.config. Subsequent add_recent_transcription()
calls mutated app.config but the window displayed its own stale copy.
Fix: refresh_config() no longer reloads from disk. It calls _redisplay() which renders the existing
shared self.config object directly.

### Bug: Transcription silent failure on quick tap
Root cause: Hotkey was purely push-to-talk. A quick tap started and immediately stopped recording
before any audio was captured. Whisper returned empty string and the overlay disappeared without explanation.
Fix: Hybrid tap/hold logic with 350ms threshold. Short taps latch the recording ON.

### Bug: CUDA selected but crashes on first transcription
Root cause: CTranslate2 can create a CUDA model even when CUDA runtime DLLs (cublas64_12.dll) are missing.
The crash only happened on the first actual inference call.
Fix: Worker performs a test transcription of a silent array after model load when device is cuda.
If it throws, it reloads on CPU before sending ready.

### Bug: Auto-paste did not work
Root cause: auto_paste config key existed but was never read or acted upon in the transcription handler.
Fix: After transcription, if auto_paste is set, paste_text() simulates Ctrl+V using Windows SendInput API.

### Bug: Clear/Refresh buttons not working
Root cause: Buttons called refresh_config() which just reloaded config from disk without clearing anything.
Fix: Replaced with clear_history() and clear_image() methods that zero out data, save, then redisplay.

---

## 12. Dependencies

```text
sounddevice >= 0.5.1       Microphone capture via PortAudio
numpy >= 2.0.0             Audio array manipulation & CV matrix operations
faster-whisper >= 1.1.1    Whisper inference (CTranslate2 backend)
pyperclip >= 1.9.0         Cross-platform clipboard access
PySide6 >= 6.8.0           Qt6 GUI framework (Qt for Python)
pytest >= 8.0.0            Test runner
pyinstaller >= 6.11.0      Windows executable packaging
pymupdf >= 1.24.0          PDF rendering and digital text stream extraction
rapidocr-onnxruntime >= 1.2.0  Local ONNX OCR engine
pillow >= 10.0.0           Image processing and raster manipulation
python-docx >= 1.0.0       Word document paragraph/table parser
sentencepiece >= 0.2.0     Subword BPE tokenization for translation
ctranslate2 >= 4.5.0       Fast neural machine translation engine
langdetect >= 1.0.9        Offline language identification
huggingface-hub >= 0.20.0  Hugging Face model repository resolver
fonttools >= 4.66.0        TrueType/OpenType font table creation & CFF compilation
reportlab >= 5.0.0         Flowable document layout & TTF vector embedding
opencv-python >= 4.9.0     Computer vision contour vectorization & polygon reduction
```

System requirements:
- Windows 10/11 (64-bit)
- PortAudio (bundled inside sounddevice wheel as libportaudio64bit.dll)
- For CUDA: NVIDIA GPU + CUDA 12.x runtime (cublas64_12.dll on PATH)

---

## 13. Logs and Debugging


### Log File Location

| Mode | Path |
|-----------------|------|
| Frozen EXE | %LOCALAPPDATA%\VoiceInput\logs\voice-input.log |
| Development | project_root\logs\voice-input.log |

### Log Format

`
2026-10-01 20:42:50,762 INFO root: Voice Input ready: tap Ctrl+Space to toggle or hold to record
2026-10-01 20:42:50,780 INFO root: Starting background Whisper worker with model=base
2026-10-01 20:43:37,861 INFO app.hotkey: Ctrl+Space pressed (native hook)
2026-10-01 20:43:37,960 INFO app.hotkey: Ctrl+Space tap detected: latching ON
2026-10-01 20:43:38,176 INFO root: Recording started
2026-10-01 20:43:39,670 INFO app.hotkey: Ctrl+Space pressed again to unlatch (native hook)
2026-10-01 20:52:46,003 INFO root: Background Whisper worker is ready
`

### Common Log Messages

| Message | Meaning |
|---------|---------|
| Voice Input ready | App started successfully |
| Native Windows Ctrl+Space hook is active | Hotkey hook installed |
| Starting background Whisper worker | Worker process spawned |
| Background Whisper worker is ready | Model loaded, ready for audio |
| Ctrl+Space tap detected: latching ON | Toggle mode activated |
| Ctrl+Space pressed again to unlatch | Toggle mode deactivated |
| Captured N audio samples | Audio recorded (N divided by 16000 equals seconds) |
| Transcription failed | Worker returned error, see traceback in log |
| Whisper stopped before returning a result | Worker process died unexpectedly |

### Quick Diagnostic Checklist

1. App does not start: Check if another instance is running in the tray (single-instance mutex)
2. Ctrl+Space does nothing: Check log for denied the global keyboard hook, try running as administrator
3. Transcribing never finishes: Check log for worker timeout or crash, try changing model to tiny
4. Empty transcription: Check Captured 0 audio samples in log, check Settings Microphone selection
5. CUDA error: Switch device to auto or cpu in Settings

---

## 14. Personal Handwriting Font Generation (Step 3)

### Overview
Verbum Step 3 transforms the verified 966-glyph dataset into native installable TrueType (`.ttf`) and OpenType (`.otf`) fonts (`fonts/Verbum_Handwriting.ttf` and `fonts/Verbum_Handwriting.otf`).

### Vectorization Architecture (`app/font_generator.py`)
1. **Contour Extraction**: Uses OpenCV Teh-Chin border following algorithm (`cv2.findContours` with `RETR_CCOMP`) preserving inner holes (e.g. `O`, `P`, `0`, `B`, `e`).
2. **Polygon Simplification**: Applies Douglas-Peucker reduction with `epsilon = 0.7` to balance point density (~46 points per glyph) and stroke fidelity.
3. **TrueType Quadratic Spline Fitting**: Midpoints between polygon vertices serve as on-curve anchors; original polygon vertices serve as off-curve quadratic control points (`qCurveTo`).
4. **Winding Orientation**: Enforces clockwise outer contours and counter-clockwise inner hole contours via the Shoelace formula in font coordinate space ($Y$ pointing upward).
5. **Typographical Metric Space**:
   - `unitsPerEm` = 1000
   - Baseline $Y = 0$
   - Cap Height = 700
   - x-height = 490
   - Ascender = 720
   - Descender = -210
   - Sidebearings: LSB = 55, RSB = 55; Space advance = 320.
6. **OpenType & TrueType Tables Built**:
   - `head`: Font revision, units per em, bounding boxes.
   - `hhea` / `hmtx`: Horizontal header and per-glyph advance widths.
   - `maxp`: Maximum profiles.
   - `OS/2`: Typographic metrics, Panose, weight/width classes, CodePage ranges.
   - `name`: Family name, PostScript name, sub-family ("Regular"), unique IDs.
   - `cmap`: Format 4 Unicode BMP mapping table.
   - `glyf` / `loca`: TrueType quadratic outlines.
   - `CFF `: OpenType Compact Font Format table (for `.otf`).
   - `post`: PostScript table (format 3.0).

### Multiprocessing & UI Integration
- **Worker (`app/font_worker.py`)**: Subprocess execution prevents GUI freezes during raster vectorization. Supports real-time progress callbacks and cancel events.
- **UI (`CreateFontPage`)**: Dataset coverage status cards, live generation progress bar, specimen card rendering (`dataset/review/font_specimen_preview.png`), interactive live test input box rendered directly in the generated font via `QFontDatabase.addApplicationFont`, and TTF / OTF download export buttons.

---

## 15. Handwritten Document & Searchable PDF Generation (Step 4)

### Overview
Verbum Step 4 compiles arbitrary multi-page user text into standardized, high-fidelity PDF documents that visually reproduce the personal handwriting style while remaining 100% digital, searchable, and selectable.

### Document Engine Architecture (`app/pdf_generator.py`)
1. **True Vector Font Embedding**:
   - Registers `Verbum_Handwriting.ttf` with ReportLab's `pdfmetrics.registerFont(TTFont('VerbumHandwriting', ttf_path))`.
   - Generates TrueType font subset embedded directly into the PDF (`AAAAAA+VerbumHandwriting-Regular`).
   - Zero raster page screenshots: all text remains crisp vector paths at 1000% zoom and selectable in any PDF viewer (Acrobat, Edge, Chrome, Preview).
2. **Flowable Multi-Page Layout**:
   - `SimpleDocTemplate` with 0.75-inch standard margins.
   - Paragraph styling with proportional leading (28 pt font size, 36 pt leading).
   - Paragraph separation and page break support (`---` on an isolated line triggers explicit `PageBreak()`).
3. **Automated Validation & Preview Rendering**:
   - Programmatically validated using PyMuPDF (`validate_pdf_document`): verifies page count, ensures text streams contain target strings, and confirms embedded font descriptor exists.
   - Page preview rasterization using PyMuPDF Matrix rendering (`output/test_document_page_1_preview.png`) for live display in the UI.
4. **Unsupported Glyph Handling**:
   - Pre-scans content against the font's Unicode `cmap`.
   - Returns any unmapped characters to the user interface transparently without crashing.

### Multiprocessing & UI Integration
- **Worker (`app/pdf_worker.py`)**: Subprocess execution for PDF generation and preview rendering.
- **UI (`CreateFilesPage`)**: Document title field, multiline text editor, "Load sample text" preset button, page count badge, embedded page preview display, "Save PDF As..." file dialog, and "Open PDF" in the default Windows system reader.

