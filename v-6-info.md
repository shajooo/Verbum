# Voice Input v6 Release Info

## Changes & Fixes

1. **Hybrid Hotkey System**:
   - **Hold (Push-To-Talk)**: Holding `Ctrl + Space` for more than 350ms will behave as standard push-to-talk. It starts recording on press and transcribes exactly when you let go.
   - **Tap (Toggle)**: Tapping `Ctrl + Space` quickly (under 350ms) latches the recording ON. The microphone stays active so you don't need to hold the keys. Tapping `Ctrl + Space` again will stop recording and transcribe. This completely fixes the issue where a short tap recorded no audio, causing transcription to silently fail.

2. **Auto-Paste Implementation**:
   - Transcribed text is now **actually pasted** directly into the active application where your cursor is (using simulated `Ctrl + V` input strokes) when the new `Paste transcript` option is enabled in Settings.

3. **Overlay Feedback Improvements**:
   - The on-screen recording overlay now updates to show you what actually happened.
   - On success, it temporarily flashes `✓ Pasted` or `✓ Copied`, and shows a snippet of the text transcribed.
   - On empty audio/silence, it clearly shows `No speech detected` instead of leaving you confused.

4. **CUDA Fallback Fix**:
   - In previous builds, if a user selected `cuda` or `auto`, the background worker incorrectly assumed it was ready even if NVIDIA CUDA runtime DLLs (like `cublas64_12.dll`) were missing. It would crash on the first transcription.
   - The worker now explicitly executes a small test transcription during model load. If CUDA DLLs are missing, it falls back to the CPU immediately before confirming it's ready.

5. **Silent VAD Fallback**:
   - If the microphone gain is low, the aggressive VAD filter (`vad_filter=True`) would often strip out quiet speech entirely, leaving an empty transcription.
   - Now, if VAD filters out the entire clip, the transcriber automatically does a second pass without VAD as a fallback to catch any quiet speech.

6. **Microphone Selection**:
   - The `Settings` window now properly lists all available microphone inputs on your system in a dropdown, instead of statically reading what was in the config file.

7. **Single-Instance Mutex**:
   - Multiple instances of `VoiceInput.exe` running simultaneously were conflicting over the `Ctrl + Space` hook. 
   - v6 includes a single-instance check. If you attempt to open the app while it's already running in the background/tray, the new instance will simply exit, ensuring no keyboard hook conflicts.

8. **Faster Initial Transcriptions**:
   - The Whisper worker is now pre-warmed as soon as you open the app, instead of waiting for your first `Ctrl + Space` press to begin downloading/loading the model.

## Installation / Run

The compiled executable is located at `release-v6\VoiceInput\VoiceInput.exe`.
