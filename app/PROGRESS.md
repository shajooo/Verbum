# app/ — Progress & Safety Log

This folder contains the Electron main-process source files.  
For the routing table and project overview, see [`MASTER.md`](../MASTER.md).

---

## Files in this folder

| File | Purpose |
|---|---|
| `main.js` | App entry point — lifecycle, IPC handlers, tray/hotkey wiring |
| `hotkey.js` | Global shortcut registration + overlay BrowserWindow |
| `paste.js` | Auto-paste: spawns `autopaste.exe` or PowerShell fallback |
| `backend.js` | Supervises the Python transcription sidecar |
| `tray.js` | System-tray icon and context menu |
| `settings.js` | Load/save persistent settings from `%APPDATA%\Verbum\settings.json` |
| `preload.js` | Electron context-bridge (exposes safe IPC API to renderer) |
| `bin\autopaste.exe` | Small C# helper — sends Ctrl+V to the previously focused window |
| `ui\index.html` | Renderer page (loaded into the main BrowserWindow) |

---

## Bug 1 — "Transcribing…" overlay never goes away

### Root cause (confirmed from code analysis)

Three layered bugs existed in the asar-bundled version:

1. **`preload.js` silently dropped `jobId`.**  
   `updateOverlay(state, message, autoHideMs, jobId)` forwarded only 3 args to IPC;  
   the 4th (`jobId`) was never sent to the main process.

2. **Late progress events wiped the auto-hide timer.**  
   `showOverlay()` called `clearTimeout(overlayHideTimeout)` unconditionally on every call.  
   A `transcribing` SSE event arriving after the `ok` / 2500 ms hide-timer was set  
   would clear that timer and set no new one → overlay permanently stuck.

3. **No safety timeout on the `spin` state.**  
   If the backend crashed or the SSE stream errored silently, the overlay stayed  
   on screen forever (no `finally`-style cleanup on that code path).

### Fix applied (session 2026-10-14)

**`app/preload.js`** — Updated `updateOverlay` and `hideOverlay` to forward `jobId` as the 4th/1st argument through IPC.

**`app/hotkey.js`** — Rewrote `showOverlay` / `hideOverlay`:
- `finishedJobIds` Set: once a job is hidden, its id is recorded; any later `showOverlay` call carrying a finished id is silently ignored.
- `overlayOwnerJobId`: tracks which job currently owns the overlay.
- `focusable: false` + `showInactive()`: overlay never steals keyboard focus.
- 30-second safety timeout on `spin` state: overlay hides automatically if the backend hangs or dies.

**`app/ui/index.html`** — The renderer-side fix (`jobId` tracking, `finally` block calling `hideOverlay(jobId)`, `jobCompleted` flag) was already present on disk before this session; the asar held the older buggy version. No changes made to this file.

**`app/main.js`** — Updated `update-overlay` and `hide-overlay` IPC handlers to destructure and pass `jobId` through to `showOverlay` / `hideOverlay`.

### Status

**Fixed — awaiting user verification.**  
Run the app (`node_modules\.bin\electron.ps1 .`), trigger a transcription with Ctrl+Space, and confirm the overlay disappears after the result is copied.

---

## Bug 2 — Auto-paste does nothing

### Root cause (partial — not fully verified)

1. **`autopaste.exe` was missing from `app\bin\` on disk.**  
   The file existed inside the `.asar` archive but had not been extracted to the source tree.  
   It has been extracted this session.

2. **`paste.js` spawned `autopaste.exe` detached (`child.unref()`); errors were completely silent.**  
   If the exe was not found, the paste silently failed with no log or callback error.

3. **No focus guard before paste.**  
   If Verbum's own window happened to be focused at paste-time (e.g. the user clicked into  
   the main window after stopping recording), the auto-paste would type into Verbum itself.

4. **Hotkey-key-release timing.**  
   The original 120 ms delay may not be long enough for Ctrl+Space to be fully released  
   before Ctrl+V is synthesized, causing the paste to misfire or be swallowed.

### Partial fix applied (session 2026-10-14)

**`app/main.js`** `trigger-auto-paste` handler:
- Added `mainWindow.isFocused()` guard — skips paste if Verbum itself is focused.
- Delay increased from 120 ms → 150 ms.
- Empty-text guard added (returns `false` immediately for empty/whitespace transcripts).

**`app\bin\autopaste.exe`** — Extracted from asar; now present on disk.

### Status

**Partially fixed — not yet tested by agent (no Electron binary available in sandbox).**

### Known limits / suggestions

- The `autoPasteInWindow` setting referenced in `ui/index.html` (line ~791) is not in  
  `DEFAULT_SETTINGS` in `settings.js`. If users save settings, this key may be lost.  
  *Suggestion:* add `autoPasteInWindow: false` to `DEFAULT_SETTINGS` in `settings.js`.
- `paste.js` errors are completely silent. *Suggestion:* add a `.catch` / error callback  
  that at least logs to console, so failures are visible in dev mode.
- PowerShell fallback path in `paste.js` adds ~600 ms latency. If `autopaste.exe` works  
  reliably, consider removing the fallback (or making it opt-in).

---

## Safety log — session 2026-10-14

### Files created this session (did not exist before)

```
C:\Projects\Verbus\app\backend.js
C:\Projects\Verbus\app\hotkey.js
C:\Projects\Verbus\app\main.js
C:\Projects\Verbus\app\paste.js
C:\Projects\Verbus\app\preload.js
C:\Projects\Verbus\app\settings.js
C:\Projects\Verbus\app\tray.js
C:\Projects\Verbus\app\bin\autopaste.exe
C:\Projects\Verbus\build.bat
C:\Projects\Verbus\MASTER.md
C:\Projects\Verbus\app\PROGRESS.md   (this file)
C:\Projects\Verbus\ui\PROGRESS.md
C:\Projects\Verbus\transcription\PROGRESS.md
```

### Files modified this session (all were created this session — no pre-existing file overwritten)

```
C:\Projects\Verbus\app\hotkey.js   — Bug 1 fix + debug logs added then removed
C:\Projects\Verbus\app\main.js     — Bug 1+2 fix + debug logs added then removed
C:\Projects\Verbus\app\preload.js  — Bug 1 fix (jobId forwarding)
```

### Files NOT modified

`app\ui\index.html`, `ui\index.html`, `app\paste.js`, `app\backend.js`,  
`app\settings.js`, `app\tray.js`, `transcription\*`, `package.json`,  
`package-lock.json`, anything outside `C:\Projects\Verbus`.

### Nothing deleted.

### Commands run (filesystem-touching)

All commands were read-only (`Get-ChildItem`, `Select-String`, `Get-Content`,  
`asar extract`) except the file creation/edit operations listed above.  
No `del`, `rd`, `Remove-Item`, `git`, or registry commands were run.

## 2026-10-15 — Fix Clipboard IPC and Auto-Paste Wiring
- Task: Ensure copy button and automatic clipboard copy work reliably across windows, and auto-paste operates correctly with active inputs.
- Files changed: `app/main.js`, `app/preload.js`, `app/PROGRESS.md`
- Result: Fixed.
- Needs user verification: Run `npm start`, test Copy button, test auto-copy toggle, and test auto-paste with active window.
- New/changed dependencies: none
- Build impact: none
- Safety log: Only `app/main.js`, `app/preload.js`, and `app/PROGRESS.md` modified. No banned commands, nothing deleted.

