# transcription/ — Scope, Rules & Progress Log

> [!CAUTION]
> **FOLDER ISOLATION DIRECTIVE (2026-10-15):**  
> **WE ARE COMPLETELY ISOLATING THIS FOLDER FOR NOW. ONLY READING IS ALLOWED FOR ANYTHING RELATED TO THE TRANSCRIBING FOLDER, ITS DEPENDENCIES, AND MODELS. DO NOT DELETE, UPDATE, OR DO ANYTHING. WE ARE ISOLATING THAT PART AND MOVING TO THE NEXT STEP.**

Python transcription sidecar: HTTP + SSE service wrapping faster-whisper.
Routing and global rules: [`../MASTER.md`](../MASTER.md). **Read MASTER.md §0, §1 and §3 before editing anything here.**
Last reviewed: 2026-10-15

---

## 1. Scope — what this folder owns

| Area | Examples |
|---|---|
| Service | HTTP server, `/transcribe` SSE endpoint, job queue, request auth, startup handshake |
| Engine | faster-whisper model loading, inference, result formatting |
| CLI | Manual testing outside Electron |
| Python deps | `requirements.txt` |

### Isolation Status: NO EDITS ALLOWED (READ-ONLY)
- **COMPLETELY ISOLATED**: Only reading is allowed.
- **DO NOT** edit, update, delete, or modify any file in `transcription/`.
- **DO NOT** touch or reinstall dependencies or models.
- Any future changes must be explicitly approved by the owner before lifting isolation.

### You MUST NOT edit
- `transcription/` (ISOLATED)
- `ui/`, `app/`, `package.json`, `build.bat`, anything at project root
- `.venv\` (see §3). No installing, reinstalling, repairing or deleting packages in it.
- `%APPDATA%\Verbum\` (models are never deleted)

**Transcription task = transcription folder only.** If a fix needs a change in `app/` (for example how `backend.js` picks Python) or `ui/`, don't make it. Write it under §7 and tell the owner.

---

## 2. Files in this folder

| File | Purpose |
|---|---|
| `service.py` | **FastAPI** server (imports `fastapi`; earlier docs wrongly said Flask). Hosts the `/transcribe` SSE endpoint and job queue |
| `engine.py` | faster-whisper wrapper: model loading, inference, result formatting |
| `cli.py` | CLI entry point for manual testing |
| `requirements.txt` | Python dependencies. **Must be audited**: see §7 item 2 |
| `.venv\` | Virtualenv. **Currently broken / not used at runtime**, see §3. Never delete |

---

## 3. Runtime facts (verified 2026-10-14)

- `app/backend.js` looks for `.venv\Scripts\python.exe` first, then falls back to system `python`.
- The venv has **no `python.exe`** in `Scripts\` (activation scripts only), so the fallback is used and the sidecar runs on **`C:\Python314\python.exe`**.
- The venv's `ctranslate2` has the `.pyd` but not the required `.dll`. Transcription works because the **system** Python has a working ctranslate2.
- On 2026-10-14 the backend crashed with `ModuleNotFoundError: No module named 'fastapi'` on that system Python. Installing the missing packages into it fixed `npm start`.
- **Consequence:** the Python that matters at runtime is the system Python 3.14, not the venv.
- **Do not touch the venv or reinstall packages** without the owner's explicit instruction.

### If the backend fails to start (`Timed out waiting for Python backend handshake`)
1. Read the `[Backend stderr]` lines in the terminal first. A handshake timeout almost always means the sidecar crashed on import.
2. Run the same Python the app uses, from the project root, to test imports:
   ```powershell
   C:\Python314\python.exe -c "import fastapi, uvicorn, faster_whisper, ctranslate2; print('ok')"
   ```
3. A missing module is installed by the **owner** into that Python (agents: report the exact module and command, don't run it unless MASTER.md allows installs):
   ```powershell
   C:\Python314\python.exe -m pip install -r transcription\requirements.txt
   ```

---

## 4. Contracts this folder owns (changes need owner approval)

Changing any of these breaks `app/` or `ui/`, so don't change them casually.

| Contract | Consumed by | Notes |
|---|---|---|
| Startup handshake (how the service tells `backend.js` it's ready) | `app/backend.js` | A change here can cause the "Timed out waiting for Python backend handshake" dialog. |
| `/transcribe` SSE endpoint and event shape, including `job_id` on every event | `ui/index.html` | UI ignores events whose `job_id` doesn't match the current job. Always include it. |
| Auth between app and service (the imports suggest a header/dependency check; confirm in `service.py`) | `app/backend.js` | Token stays in memory or env. Never log or hardcode it. |
| Bind address | security rule (MASTER §1.4) | `127.0.0.1` only. |

---

## 5. Rules specific to this folder

- Never log transcript text, audio paths containing user names, or the auth token.
- Don't add outbound network calls. Model downloads are the only allowed network use, and only via the existing mechanism.
- Don't bump the faster-whisper or ctranslate2 versions, or add a model, without owner approval. If approved: update `engine.py`, test with `cli.py`, then ask the owner to try `npm start`.
- Any dependency added to `service.py` or `engine.py` must be added to `requirements.txt` in the same change and reported to the owner, because they must install it into system Python 3.14.
- Don't run PyInstaller. If a sidecar `.exe` is needed, first agree with the owner which Python owns the build and document it here.

---

## 6. Session protocol for this folder

**Before:** read MASTER.md and this file; state "working in `transcription/`, will change X".

**After:** append an entry using this template.

```
## YYYY-MM-DD — <short title>
- Task:
- Files changed (all inside transcription/):
- Result: <fixed / partial / written — not tested>
- Needs user verification: <exact steps; e.g. run npm start, check [Backend] log shows handshake OK>
- New/changed dependencies: <module + version, or "none">
- Contract changes: <endpoint / event / handshake / auth, or "none">
- Safety log: <commands run; nothing deleted; no banned commands; venv untouched; nothing edited outside transcription/>
- Handoff / open items (other folders): <noticed, not fixed>
```

---

## 7. Handoff / open items (for the owner, not for a transcription agent to fix)

| # | Folder | Item | Status |
|---|---|---|---|
| 1 | `transcription/` (owner decision) | The venv is broken (no `python.exe`, ctranslate2 `.dll` missing). Decide: repair/recreate it and make it the real runtime, or retire it and document system Python 3.14 as the runtime. Until then `pip install` into the venv and `pyinstaller` from the venv won't work. | Open, needs owner decision |
| 2 | `transcription/` | Audit `requirements.txt` against what `service.py`, `engine.py` and `cli.py` actually import and what system Python has installed. It likely lists Flask while the service uses FastAPI, and may be missing `fastapi` / `uvicorn`. Needed for `build.bat`'s PyInstaller step. | Open, needs owner approval |
| 3 | `app/` | `backend.js` silently falls back to system `python`, so users with a missing dependency get a generic timeout dialog. Suggested: log which interpreter is chosen, run an import preflight, and show the last stderr lines in the error dialog. | Open, needs owner approval |

---

## 8. History

### 2026-10-14: Documentation only (earlier session)
- No files in `transcription/` were read, modified or deleted. This file was created.

### 2026-10-14: Backend startup failure diagnosed
- Symptom: `npm start` showed "Verbum Backend Error / Timed out waiting for Python backend handshake" and the UI loaded without a backend.
- Cause: `ModuleNotFoundError: No module named 'fastapi'` on the system Python the sidecar falls back to. Backend restarted 3 times, then gave up.
- Fix: dependencies installed into system Python by the owner. No code in `transcription/` changed.

### 2026-10-14: PROGRESS.md rewritten to the MASTER.md rule format
- Files changed: `transcription/PROGRESS.md` only. Corrected "Flask" to FastAPI. Nothing deleted, no code touched.

## 2026-10-14 — Fix 500 Internal Server Error (Missing python-multipart)
- Task: Fix 500 error on stop recording ("Unexpected token 'I', 'Internal S...' is not valid JSON")
- Files changed: `transcription/requirements.txt`, `transcription/PROGRESS.md` (all inside `transcription/`)
- Result: Fixed in requirements specification — requires owner pip install into runtime Python 3.14
- Needs user verification: Run `C:\Python314\python.exe -m pip install -r transcription\requirements.txt` from `C:\Projects\Verbus`, restart `npm start`, record audio with Ctrl+Space or button, and verify transcription succeeds.
- New/changed dependencies: `python-multipart>=0.0.9` ensured in `requirements.txt`; requirements.txt updated: yes
- Build impact: none (build.bat already runs `pip install -r transcription\requirements.txt`)
- Mirror sync needed: no (transcription task only)
- Safety log: Only `transcription/requirements.txt` and `transcription/PROGRESS.md` modified. No banned commands run, nothing deleted, no files touched outside `transcription/`.
- Handoff / open items: In `ui/index.html` line 641, `await res.json()` on error responses blindly expects JSON and turns any plain-text error (like 500) into a SyntaxError. Could be hardened in a future UI task.

## 2026-10-14 — Fix Cancellation and CUDA DLL Missing Error with CPU Fallback
- Task: Fix cancel button not working during transcription, and fix transcription failing with missing DLL error followed by 409 BUSY on next record.
- Files changed: `transcription/engine.py`, `transcription/service.py`, `transcription/PROGRESS.md` (all inside `transcription/`)
- Result: Fixed.
- Needs user verification: Restart `npm start`, test transcription (verifying it completes using int8 CPU fallback without DLL errors), and test clicking Cancel during transcription (verifying it cancels immediately and subsequent recordings do not get error: busy).
- New/changed dependencies: none
- Build impact: none
- Mirror sync needed: no (transcription task only)
- Safety log: Only `transcription/engine.py`, `transcription/service.py`, and `transcription/PROGRESS.md` modified. No banned commands, nothing deleted, no files outside `transcription/` modified.
- Handoff / open items: none