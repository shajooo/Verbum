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

## Build

```powershell
.\.venv\Scripts\pyinstaller.exe --noconfirm --clean --windowed --name VoiceInput --collect-all faster_whisper main.py
```

The executable will be at `dist\VoiceInput\VoiceInput.exe`.
