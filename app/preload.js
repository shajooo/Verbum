/**
 * Verbum Preload Script
 * Exposes a strictly whitelisted, secure API to the renderer process.
 */

const { contextBridge, ipcRenderer, clipboard } = require('electron');

contextBridge.exposeInMainWorld('verbumApi', {
  // Backend connection details
  getBackendInfo: () => ipcRenderer.invoke('get-backend-info'),

  // Settings persistence
  getSettings: () => ipcRenderer.invoke('get-settings'),
  saveSettings: (settings) => ipcRenderer.invoke('save-settings', settings),
  rebindHotkey: (shortcut) => ipcRenderer.invoke('rebind-hotkey', shortcut),

  // Pending queue for Send to Editor
  getPendingList: () => ipcRenderer.invoke('get-pending-list'),
  savePendingList: (items) => ipcRenderer.invoke('save-pending-list', items),

  // Clipboard & Auto-paste
  copyToClipboard: (text) => {
    if (text) {
      if (clipboard && typeof clipboard.writeText === 'function') {
        try { clipboard.writeText(text); } catch (e) {}
      }
      ipcRenderer.invoke('copy-to-clipboard', text);
      return true;
    }
    return false;
  },
  triggerAutoPaste: (text) => ipcRenderer.invoke('trigger-auto-paste', text),

  // Window control
  hideToTray: () => ipcRenderer.invoke('hide-to-tray'),
  isWindowVisible: () => ipcRenderer.invoke('is-window-visible'),

  // Hotkey & background recording events
  onGlobalRecordToggle: (callback) => {
    ipcRenderer.on('toggle-recording', (_event, data) => callback(data));
  },

  // Main process notifications & overlay updates
  // Bug 1 fix: pass jobId through IPC so main process can guard against stale events.
  updateOverlay: (state, message, autoHideMs, jobId) => {
    ipcRenderer.invoke('update-overlay', { state, message, autoHideMs, jobId });
  },
  hideOverlay: (jobId) => {
    ipcRenderer.invoke('hide-overlay', jobId);
  },
  updateTrayRecording: (isRecording) => {
    ipcRenderer.invoke('update-tray-recording', isRecording);
  },
  updateTrayModel: (modelName) => {
    ipcRenderer.invoke('update-tray-model', modelName);
  },
});
