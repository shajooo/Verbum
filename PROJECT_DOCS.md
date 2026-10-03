# Voice Input — Complete Project Documentation

> **Current Version: v6** | **Platform: Windows 10/11 (64-bit)** | **Language: Python 3.14**

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Feature List v6 Current](#2-feature-list-v6--current)
3. [Architecture and How It Works](#3-architecture--how-it-works)
4. [File and Folder Structure](#4-file--folder-structure)
5. [Module Reference](#5-module-reference)
6. [Configuration Reference](#6-configuration-reference)
7. [UI Reference](#7-ui-reference)
8. [How to Build](#8-how-to-build-development--executable)
9. [Version History](#9-version-history)
10. [Known Issues Fixed in v6](#10-known-issues-fixed-in-v6)
11. [Dependencies](#11-dependencies)
12. [Logs and Debugging](#12-logs--debugging)

---

## 1. Project Overview

Voice Input is a fully private, local, offline voice transcription tool for Windows.
It lives in the system tray and lets you dictate text anywhere on your computer using Ctrl + Space.
All transcription is done locally using OpenAI Whisper via the faster-whisper library. No audio ever leaves your machine.

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

## 2. Feature List (v6 — Current)

### Transcription
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

### UI
- Main window: Status card, hotkey instructions, reference image panel, recent transcription history
- System tray: always-accessible icon with status tooltip, Open, Settings, About, Exit menu
- Recording overlay: floating frameless widget at bottom of screen; animates a red pulsing dot while recording
- Settings window: full settings form with live microphone list, model/device/language dropdowns, copy/paste toggles
- Clear history button (dark red): wipes the last 5 transcriptions from config
- Clear image button (dark red): removes the reference image

### System
- Single-instance mutex: Only one copy of VoiceInput.exe can run at a time (CreateMutexW)
- Windows startup: optional registry entry under HKCU Software Microsoft Windows CurrentVersion Run
- Pre-warmed worker: Whisper model begins loading as soon as the app starts
- Background tray mode: closing the main window hides it to the tray

---

## 3. Architecture and How It Works

### Process Layout

VoiceInput.exe (main process) contains:
- Qt Event Loop (main thread) with VoiceInputApp controller, MainWindow, RecordingOverlay, SettingsWindow, Tray
- VoiceInputHotkey (daemon thread) with Windows message loop and WH_KEYBOARD_LL hook
- Whisper Worker (separate OS process, daemon) with faster-whisper WhisperModel loaded in RAM

### Data Flow

1. Keyboard Hook Thread: Ctrl+Space down fires on_press signal via HotkeyBridge
2. Qt Main Thread start_recording: Recorder.start() opens sounddevice InputStream at 16kHz float32 mono
3. Keyboard Hook Thread: Ctrl+Space up or second tap fires on_release signal
4. Qt Main Thread stop_recording: Recorder.stop() concatenates numpy chunks, sends to worker via Queue
5. Worker Process _run: WhisperModel.transcribe with vad_filter=True, retry without VAD if empty, put result on results Queue
6. Qt Main Thread poll_worker QTimer 100ms: reads result, updates config, updates UI, pastes or copies

### Worker Lifecycle

On app start: ensure_worker() called immediately for pre-warming.
start_worker() spawns multiprocessing.Process running _run().
_run() loads the model, tests CUDA if needed, sends ( ready, ) on results queue.
poll_worker sees ready message and sets worker_state = READY.
On Ctrl+Space: ensure_worker() is noop if alive, audio put on command_queue.
Worker loop: blocking commands.get(), transcribe, put result.
On app exit: finish_worker() sends None command for graceful exit, then terminates if needed.

### HotkeyBridge

The keyboard hook lives on a non-Qt thread. Direct Qt UI calls from non-Qt threads crash the app.
HotkeyBridge is a QObject with two Signal() pressed and released.
The hook callbacks call signal.emit() which Qt safely marshals to the main thread via QueuedConnection.

---

## 4. File and Folder Structure

`
c:/Projects/Transcriber/
├── main.py Entry point, calls app.main.run()
├── requirements.txt Python dependencies
├── VoiceInput.spec PyInstaller build spec
├── config.json User config (auto-created, JSON)
├── PROJECT_DOCS.md This file
│
├── app/
│ ├── main.py VoiceInputApp controller + run()
│ ├── config.py Config dataclass + load/save
│ ├── hotkey.py Native WH_KEYBOARD_LL hook
│ ├── recorder.py 16kHz sounddevice microphone recorder
│ ├── transcriber.py Whisper model loader + transcribe logic
│ ├── worker.py Multiprocessing worker process
│ ├── clipboard.py copy_text() + paste_text() via SendInput
│ ├── autostart.py Windows registry startup entry
│ └── ui/
│ ├── main_window.py Main app window
│ ├── settings_window.py Settings form
│ ├── recording_overlay.py Floating recording indicator widget
│ └── tray.py System tray icon and menu
│
├── tests/ pytest test suite
│
├── release-v6/ CURRENT RELEASE
│ └── VoiceInput/
│ └── VoiceInput.exe The compiled executable
│
├── release-v5/
├── release-v4/
├── release-v3/
├── release-v2/
└── release/
`

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

### app/config.py — Persistent Settings

Config dataclass fields:
  hotkey          list[str]   [ctrl,space]   Fixed, not user-changeable
  model           str         small            Whisper model size
  language        str         auto             Transcription language
  device          str         auto             Inference device
  compute_type    str         auto             CTranslate2 quantization
  microphone      str         default          Input device name
  auto_copy       bool        True               Copy transcript to clipboard
  auto_paste      bool        False              Also paste at cursor
  sound_feedback  bool        False              Reserved, not yet used
  start_with_windows bool     False              Registry startup entry
  image_path      str          Reference image path
 recent_transcriptions list [] Last 5 transcripts

Config file location:
 Frozen EXE: %LOCALAPPDATA%\VoiceInput\config.json
 Development: project_root\config.json

add_recent_transcription(text): prepends text, keeps last 5, saves immediately.

---

### app/autostart.py — Windows Startup

Writes/removes registry key at:
HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run\VoiceInput
Value is the full path to the executable. Uses HKCU so no admin rights are needed.

---

### app/ui/main_window.py — Main Window

ImageDropZone(QLabel)
 Accepts file drag-and-drop for png, jpg, jpeg, bmp, gif, webp.
 Shows scaled preview (300x170 max) or placeholder text.

MainWindow(QMainWindow) contains:
 - Status card (state title and detail message, color-coded by state)
 - Instruction card (hotkey explanation)
 - Image group (drop zone + Clear image + Browse image)
 - History group (last 5 transcriptions + Clear history)
 - Config summary bar (model | device | language)
 
 Key methods:
 - update_status(state, detail): updates status card colors
 - refresh_config() -> _redisplay(): re-renders current in-memory config (no disk read)
 - _redisplay(): updates history label, image drop zone, config summary
 - clear_history(): sets recent_transcriptions = [], saves, redraws
 - clear_image(): sets image_path = , saves, redraws

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

Config is stored as plain JSON. You can edit it manually while the app is closed.

Default config.json:
{
  hotkey: [ctrl, space],
  model: small,
  language: auto,
  device: auto,
  compute_type: auto,
  microphone: default,
  auto_copy: true,
  auto_paste: false,
  sound_feedback: false,
  start_with_windows: false,
  image_path: ,
 recent_transcriptions: []
}

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

- Python 3.14 (any 3.10+ works)
- Windows 10 or 11

### Setup First Time

`powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
`

### Run in Development Mode

`powershell
.\.venv\Scripts\python.exe main.py
`

### Run Tests

`powershell
.\.venv\Scripts\pytest.exe tests/
`

### Build the Executable

`powershell
.\.venv\Scripts\pyinstaller.exe --noconfirm --clean --windowed --name VoiceInput --collect-all faster_whisper main.py
`

Build flags:
 --noconfirm Overwrite previous dist without prompting
 --clean Delete PyInstaller cache before build
 --windowed No console window (GUI app)
 --name VoiceInput Output exe name
 --collect-all Bundle all faster_whisper data/binaries

Output location: dist\VoiceInput\VoiceInput.exe

### Deploy to Release Folder

`powershell
robocopy dist\VoiceInput release-v6\VoiceInput /E /PURGE /IS /IT
`

### Important Build Notes

- mp.freeze_support() must be the very first call in run() for multiprocessing to work in frozen exe
- The single-instance mutex check comes immediately after freeze_support() so duplicate launches exit instantly
- faster_whisper must use --collect-all because it has binary DLLs and tokenizer data files
- The worker process inherits the frozen executable module path via PyInstaller pyi_rth_multiprocessing hook

---

## 9. Version History

| Version | Key Changes |
|--------------|-------------|
| v6 (current) | Hybrid tap/hold hotkey; auto-paste via SendInput; CUDA DLL fallback fix; VAD fallback for quiet speech; live history update fix; Clear history and Clear image buttons; single-instance mutex; pre-warmed worker on startup; live microphone dropdown in settings |
| v5 | Persistent worker process; history panel; reference image; settings overhaul; Windows startup |
| v4 | System tray; background mode; recording overlay with animation |
| v3 | Settings window; model/language/device selector; auto-copy |
| v2 | PySide6 UI; config file persistence; sounddevice recorder |
| v1/release | Initial Whisper integration; basic hotkey; push-to-talk |

---

## 10. Known Issues Fixed in v6

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

## 11. Dependencies

`
sounddevice >= 0.5.1 Microphone capture via PortAudio
numpy >= 2.0.0 Audio array manipulation
faster-whisper >= 1.1.1 Whisper inference (CTranslate2 backend)
pyperclip >= 1.9.0 Cross-platform clipboard access
PySide6 >= 6.8.0 Qt6 GUI framework (Qt for Python)
pytest >= 8.0.0 Test runner
pyinstaller >= 6.11.0 Windows executable packaging
`

faster-whisper internally depends on:
 - ctranslate2: optimized inference engine (CPU int8 / CUDA float16)
 - huggingface_hub: model download/caching
 - tokenizers: Whisper tokenizer

System requirements:
 - Windows 10/11 (64-bit)
 - PortAudio (bundled inside sounddevice wheel as libportaudio64bit.dll)
 - For CUDA: NVIDIA GPU + CUDA 12.x runtime (cublas64_12.dll on PATH)

---

## 12. Logs and Debugging

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
