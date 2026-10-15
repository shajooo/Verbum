/**
 * Verbum Main Process Entry Point
 * Coordinates Electron window, tray, global shortcuts, backend supervisor, and auto-paste.
 */

const { app, BrowserWindow, ipcMain, dialog, clipboard } = require('electron');
const path = require('path');
const { startBackend, stopBackend, getBackendInfo } = require('./backend');
const { initTray, setTrayRecording, setTrayModel } = require('./tray');
const { registerHotkey, unregisterHotkey, showOverlay, hideOverlay } = require('./hotkey');
const { pasteToActiveWindow } = require('./paste');
const { loadSettings, saveSettings, loadPendingList, savePendingList } = require('./settings');

let mainWindow = null;
app.isQuitting = false;

// 1. Single Instance Lock
const gotSingleInstanceLock = app.requestSingleInstanceLock();
if (!gotSingleInstanceLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      if (!mainWindow.isVisible()) mainWindow.show();
      mainWindow.focus();
    }
  });
}

function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1060,
    height: 780,
    minWidth: 840,
    minHeight: 600,
    title: 'Verbum',
    backgroundColor: '#f6f5f1',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      backgroundThrottling: false, // Ensures audio worklet and hotkey processing continue when hidden
    },
  });

  mainWindow.loadFile(path.join(__dirname, 'ui', 'index.html'));

  mainWindow.on('close', (e) => {
    const settings = loadSettings();
    if (settings.keepInTrayOnClose && !app.isQuitting) {
      e.preventDefault();
      mainWindow.hide();
    }
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

app.whenReady().then(async () => {
  const settings = loadSettings();

  // 1. Start Python sidecar
  try {
    await startBackend();
  } catch (err) {
    console.error('Failed to launch backend sidecar:', err);
    dialog.showErrorBox(
      'Verbum Backend Error',
      `Failed to launch the local transcription service:\n${err.message}\nPlease verify Python 3.10-3.14 and faster-whisper are installed.`
    );
  }

  // 2. Create Window
  createMainWindow();

  // 3. Initialize Tray
  initTray({
    initialModel: settings.defaultModel || 'small',
    onOpenWindow: () => {
      if (mainWindow) {
        if (!mainWindow.isVisible()) mainWindow.show();
        mainWindow.focus();
      }
    },
    onToggleRecord: () => {
      if (mainWindow) {
        mainWindow.webContents.send('toggle-recording', { source: 'tray' });
      }
    },
  });

  // 4. Register Global Hotkey
  const regResult = registerHotkey(settings.recordingHotkey, () => {
    if (mainWindow) {
      mainWindow.webContents.send('toggle-recording', { source: 'hotkey' });
    }
  });
  if (!regResult.success) {
    console.warn(`Global hotkey conflict: ${regResult.error}`);
  }

  // 5. IPC Handlers
  ipcMain.handle('get-backend-info', () => getBackendInfo());

  ipcMain.handle('get-settings', () => loadSettings());
  ipcMain.handle('save-settings', (_e, newSettings) => {
    const saved = saveSettings(newSettings);
    if (newSettings.recordingHotkey) {
      registerHotkey(newSettings.recordingHotkey, () => {
        if (mainWindow) {
          mainWindow.webContents.send('toggle-recording', { source: 'hotkey' });
        }
      });
    }
    return saved;
  });

  ipcMain.handle('rebind-hotkey', (_e, shortcut) => {
    const res = registerHotkey(shortcut, () => {
      if (mainWindow) {
        mainWindow.webContents.send('toggle-recording', { source: 'hotkey' });
      }
    });
    if (res.success) {
      saveSettings({ recordingHotkey: shortcut });
    }
    return res;
  });

  ipcMain.handle('get-pending-list', () => loadPendingList());
  ipcMain.handle('save-pending-list', (_e, items) => savePendingList(items));

  ipcMain.handle('copy-to-clipboard', (_e, text) => {
    if (text) {
      clipboard.writeText(text);
      return true;
    }
    return false;
  });

  // Auto-paste: check window focus before pasting;
  // skip paste when result is empty or Verbum's own window would receive the keystroke.
  ipcMain.handle('trigger-auto-paste', async (_e, text) => {
    const settings = loadSettings();
    if (!settings.autoPaste) {
      return false;
    }
    if (!text || text.trim() === '') {
      return false;
    }
    // Do not paste into Verbum's own window.
    const verbumFocused = mainWindow && mainWindow.isFocused();
    if (verbumFocused) {
      return false;
    }
    await pasteToActiveWindow(150); // 150 ms delay — enough for hotkey keys to be released
    return true;
  });

  ipcMain.handle('hide-to-tray', () => {
    if (mainWindow) mainWindow.hide();
  });

  ipcMain.handle('is-window-visible', () => {
    return mainWindow ? mainWindow.isVisible() : false;
  });

  ipcMain.handle('update-overlay', (_e, { state, message, autoHideMs, jobId }) => {
    showOverlay(state, message, autoHideMs, jobId);
  });

  ipcMain.handle('hide-overlay', (_e, jobId) => {
    hideOverlay(jobId);
  });

  ipcMain.handle('update-tray-recording', (_e, isRecording) => {
    setTrayRecording(isRecording);
  });

  ipcMain.handle('update-tray-model', (_e, modelName) => {
    setTrayModel(modelName);
  });
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createMainWindow();
  }
});

app.on('will-quit', () => {
  unregisterHotkey();
  stopBackend();
});
