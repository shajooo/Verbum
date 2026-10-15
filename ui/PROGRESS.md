# ui/ — Scope, Rules & Progress Log

Renderer source for the Electron main window (all screens, recorder logic, SSE client, IPC calls).
Routing and global rules: [`../MASTER.md`](../MASTER.md). **Read MASTER.md §0, §1 and §3 before editing anything here.**
Last reviewed: 2026-10-14

---

## 1. Scope — what this folder owns

| Area | Examples |
|---|---|
| Screens | Main, Settings panel, Editor view |
| Styling | CSS, layout, themes, animations |
| Renderer JS | Recorder UI logic, SSE client, job/overlay state handling, calls to the preload API |

### You MAY edit
- `ui/index.html` (and any new file created inside `ui/`)
- `ui/PROGRESS.md` (append only, see §6)

### You MUST NOT edit
- `app/` (including `app/ui/index.html`, `app/preload.js`, `app/main.js`, `app/settings.js`)
- `transcription/`
- `package.json`, `build.bat`, anything at project root
- `%APPDATA%\Verbum\` (read-only for everyone)

**UI task = UI folder only.** If a fix needs a change in `app/` or `transcription/`, don't make it. Write it under §7 "Handoff / open items" and tell the owner.

---

## 2. Files in this folder

| File | Purpose |
|---|---|
| `index.html` | Single-page renderer: all UI screens, renderer JS, styles |
| `PROGRESS.md` | This file |

---

## 3. The mirror: `ui/index.html` → `app/ui/index.html`

- `ui/index.html` is the **canonical source**. Edit only this one.
- Electron loads **`app/ui/index.html`** (set in `app/main.js`), so a change in `ui/` has **no visible effect until the file is copied over**.
- Both files were byte-identical on 2026-10-14.
- Agents must **not** edit `app/ui/index.html` (outside this folder).

**After every UI change, the agent tells the owner to sync with this exact command (owner runs it):**

```powershell
cd C:\Projects\Verbus
Copy-Item ui\index.html app\ui\index.html -Force
```

This overwrites one file and touches nothing else. If the owner has hand-edited `app/ui/index.html`, compare first and never overwrite blindly:

```powershell
fc.exe ui\index.html app\ui\index.html
```

---

## 4. Contracts this folder depends on (don't break, don't change here)

The renderer is on the receiving end of these. If one is missing or wrong, report it as a handoff item.

| Contract | Owned by | Notes |
|---|---|---|
| Preload API exposed to the renderer (IPC bridge) | `app/preload.js` | Renderer may only call what preload exposes. Never use Node/Electron APIs directly. |
| Backend job events (SSE) carrying `job_id` | `transcription/service.py` | Renderer must keep ignoring events whose `job_id` ≠ `currentJobId`. |
| Settings keys (e.g. `autoPasteInWindow`) | `app/settings.js` | Renderer must tolerate a missing key (treat `undefined` as the default). |

---

## 5. Invariants — logic that must survive any UI edit

These fixed the "overlay stays on screen" bug (Bug 1). Don't remove or reorder them when refactoring:

- `currentJobId` is assigned at the start of each transcription job.
- `handleJobEvent` ignores events where `ev.job_id !== currentJobId`.
- A `finally` block calls `hideOverlay(currentJobId)` when `!jobCompleted`, covering error, cancel and empty-result paths.
- `jobCompleted = true` is set **before** the `ok` / auto-hide call, so `finally` doesn't double-hide.

---

## 6. Session protocol for this folder

**Before:** read MASTER.md and this file; state "working in `ui/`, will change X".

**After:** append an entry using this template, then give the owner the sync command from §3 and test steps.

```
## YYYY-MM-DD — <short title>
- Task:
- Files changed (all inside ui/):
- Result: <fixed / partial / written — not tested>
- Needs user verification: <exact steps>
- Mirror sync needed: yes/no (owner runs the §3 command)
- Safety log: <commands run; nothing deleted; no banned commands; nothing edited outside ui/>
- Handoff / open items (other folders): <noticed, not fixed>
```

---

## 7. Handoff / open items (for the owner, not for the UI agent to fix)

| # | Folder | Item | Status |
|---|---|---|---|
| 1 | `app/` | `autoPasteInWindow` is read in `index.html` (~line 791) but missing from `DEFAULT_SETTINGS` in `app/settings.js`; it can be `undefined` if the user saves settings before setting it. Suggested fix: add `autoPasteInWindow: false` to `DEFAULT_SETTINGS`. | Open, needs owner approval |

---

## 8. History

### 2026-10-14 — Documentation only (earlier session)
- Task: audit renderer for Bug 1 (overlay stuck on screen).
- Finding: the renderer-side fix was already present in `ui/index.html` (see §5). The asar-bundled version did not have it, but the on-disk source did. The remaining gap was main-process side (`hotkey.js`, `preload.js`), fixed in `app/`.
- Files changed: none (this file was created).
- Safety log: nothing deleted, no banned commands.

### 2026-10-14 — PROGRESS.md rewritten to the MASTER.md rule format
- Files changed: `ui/PROGRESS.md` only.
- Safety log: nothing deleted, no code touched.

## 2026-10-15 — Fix Send-to-Editor Separation, Copy Button Feedback, Auto-Copy, and Auto-Paste
- Task: Ensure transcription does not automatically send to editor (only 'Send to editor' button does), copy button gives 'Copied ✓' feedback and writes to clipboard, auto-copy toggle setting is respected, and auto-paste works when toggle is ON.
- Files changed: `ui/index.html`, `ui/PROGRESS.md`
- Result: Fixed.
- Needs user verification: Run mirror sync (`Copy-Item ui\index.html app\ui\index.html -Force`), start `npm start`, test transcription completion (confirming it does not automatically add to editor pending list), test Copy button (confirming text is copied and button shows 'Copied ✓'), test auto-copy toggle ON/OFF, and test auto-paste with target input box.
- Mirror sync needed: yes (owner runs `Copy-Item ui\index.html app\ui\index.html -Force`)
- Safety log: Only `ui/index.html` and `ui/PROGRESS.md` modified. No banned commands, nothing deleted.
- Handoff / open items: none