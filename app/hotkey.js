/**
 * Verbum Global Hotkey & Overlay Window Module
 * Handles Ctrl+Space trigger, floating status overlay, and background recording pipeline.
 */

const { globalShortcut, BrowserWindow, screen } = require('electron');

let overlayWindow = null;
let currentShortcut = 'CommandOrControl+Space';
let onTriggerCb = null;
let overlayHideTimeout = null;

// Bug 1 fix: track finished jobs so stale events cannot re-show the overlay.
const finishedJobIds = new Set();
// Bug 1 fix: track which job currently owns the overlay.
let overlayOwnerJobId = null;

function createOverlayWindow() {
  if (overlayWindow && !overlayWindow.isDestroyed()) return overlayWindow;

  const primaryDisplay = screen.getPrimaryDisplay();
  const { width: screenWidth, height: screenHeight } = primaryDisplay.workArea;

  const winWidth = 300;
  const winHeight = 56;
  const x = Math.round((screenWidth - winWidth) / 2);
  const y = screenHeight - winHeight - 30;

  overlayWindow = new BrowserWindow({
    width: winWidth,
    height: winHeight,
    x,
    y,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    skipTaskbar: true,
    resizable: false,
    focusable: false,  // Bug 1 fix: never steal keyboard focus
    show: false,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
    },
  });

  const overlayHtml = `
  <!DOCTYPE html>
  <html>
  <head>
    <meta charset="utf-8">
    <style>
      * { box-sizing: border-box; margin: 0; padding: 0; }
      body {
        background: transparent;
        font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
        display: flex;
        align-items: center;
        justify-content: center;
        height: 100vh;
        user-select: none;
        overflow: hidden;
      }
      .pill {
        display: flex;
        align-items: center;
        gap: 10px;
        background: rgba(22, 23, 21, 0.92);
        color: #ecebe6;
        padding: 10px 18px;
        border-radius: 999px;
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.35);
        border: 1px solid rgba(255, 255, 255, 0.1);
        font-size: 14px;
        font-weight: 500;
      }
      .dot {
        width: 10px;
        height: 10px;
        border-radius: 50%;
        background: #f2867f;
      }
      .dot.rec {
        animation: pulse 1s infinite alternate;
        background: #e53935;
      }
      .dot.spin {
        border: 2px solid #6fb39f;
        border-top-color: transparent;
        border-radius: 50%;
        background: transparent;
        animation: spin 0.8s linear infinite;
      }
      .dot.ok { background: #6fcf93; }
      .dot.warn { background: #e0a84a; }
      @keyframes pulse { from { opacity: 0.4; } to { opacity: 1; } }
      @keyframes spin { 100% { transform: rotate(360deg); } }
    </style>
  </head>
  <body>
    <div class="pill" id="pill">
      <span class="dot" id="dot"></span>
      <span id="text">Ready</span>
    </div>
    <script>
      window.addEventListener('message', (e) => {
        const { state, message } = e.data || {};
        const dot = document.getElementById('dot');
        const text = document.getElementById('text');
        text.textContent = message || '';
        dot.className = 'dot ' + (state || '');
      });
    </script>
  </body>
  </html>
  `;

  overlayWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(overlayHtml)}`);
  return overlayWindow;
}

function showOverlay(state, message, autoHideMs = 0, jobId = null) {
  // Bug 1 fix: ignore events from a job that has already finished.
  if (jobId && finishedJobIds.has(jobId)) {
    return;
  }

  clearTimeout(overlayHideTimeout);

  // Bug 1 fix: record which job now owns the overlay.
  if (jobId) {
    overlayOwnerJobId = jobId;
  }

  const win = createOverlayWindow();

  win.webContents.executeJavaScript(`
    window.postMessage(${JSON.stringify({ state, message })}, '*');
  `).catch(() => {});

  if (!win.isVisible()) {
    win.showInactive();  // Bug 1 fix: never steal focus
  }

  if (autoHideMs > 0) {
    // Normal auto-hide (e.g. 'ok' 2500ms, 'warn' 3000ms)
    overlayHideTimeout = setTimeout(() => {
      hideOverlay(jobId);
    }, autoHideMs);
  } else if (state === 'spin') {
    // Bug 1 fix: safety timeout — if transcription hangs or backend dies,
    // hide after 30 s so the overlay never gets permanently stuck.
    overlayHideTimeout = setTimeout(() => {
      hideOverlay(jobId);
    }, 30000);
  }
}

function hideOverlay(jobId = null) {
  clearTimeout(overlayHideTimeout);

  // Bug 1 fix: mark the job as finished so any late events for it are ignored.
  if (jobId) {
    finishedJobIds.add(jobId);
    // Prune set so it does not grow unboundedly across many jobs.
    if (finishedJobIds.size > 20) {
      finishedJobIds.delete(finishedJobIds.values().next().value);
    }
  }

  if (overlayWindow && !overlayWindow.isDestroyed() && overlayWindow.isVisible()) {
    overlayWindow.hide();
  }

  // Clear owner so future showOverlay calls can take ownership.
  if (!jobId || jobId === overlayOwnerJobId) {
    overlayOwnerJobId = null;
  }
}

function registerHotkey(shortcutString, onTrigger) {
  onTriggerCb = onTrigger;
  unregisterHotkey();

  const toRegister = shortcutString || currentShortcut;
  try {
    const success = globalShortcut.register(toRegister, () => {
      if (onTriggerCb) onTriggerCb();
    });
    if (success) {
      currentShortcut = toRegister;
      return { success: true, shortcut: toRegister };
    } else {
      return { success: false, error: `Failed to register shortcut ${toRegister}. Already in use.` };
    }
  } catch (err) {
    return { success: false, error: err.message };
  }
}

function unregisterHotkey() {
  if (currentShortcut) {
    globalShortcut.unregister(currentShortcut);
  }
}

module.exports = {
  createOverlayWindow,
  showOverlay,
  hideOverlay,
  registerHotkey,
  unregisterHotkey,
};
