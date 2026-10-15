/**
 * Verbum Settings and Pending Approval Storage Manager
 * Persists configuration to %APPDATA%/Verbum/settings.json and pending.json.
 */

const fs = require('fs');
const path = require('path');
const os = require('os');

function getAppDataDir() {
  const base = process.env.APPDATA || (process.platform === 'darwin' ? path.join(os.homedir(), 'Library', 'Application Support') : path.join(os.homedir(), '.config'));
  const dir = path.join(base, 'Verbum');
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
  return dir;
}

const DEFAULT_SETTINGS = {
  defaultModel: 'small',
  language: 'auto',
  vad: true,
  prompt: '',
  microphoneDevice: 'default',
  maxRecordingLengthSec: 600,
  copyAutomatically: true,
  autoPaste: false,
  keepInTrayOnClose: true,
  startWithWindows: false,
  recordingHotkey: 'CommandOrControl+Space',
  loadModelAtStartup: false,
  playSound: false,
  deleteTempAudio: true,
};

function getSettingsPath() {
  return path.join(getAppDataDir(), 'settings.json');
}

function getPendingPath() {
  return path.join(getAppDataDir(), 'pending.json');
}

function loadSettings() {
  const p = getSettingsPath();
  try {
    if (fs.existsSync(p)) {
      const data = JSON.parse(fs.readFileSync(p, 'utf8'));
      return { ...DEFAULT_SETTINGS, ...data };
    }
  } catch (e) {
    console.error('Failed to load settings:', e);
  }
  return { ...DEFAULT_SETTINGS };
}

function saveSettings(newSettings) {
  const p = getSettingsPath();
  try {
    const merged = { ...loadSettings(), ...newSettings };
    fs.writeFileSync(p, JSON.stringify(merged, null, 2), 'utf8');
    return merged;
  } catch (e) {
    console.error('Failed to save settings:', e);
    return loadSettings();
  }
}

function loadPendingList() {
  const p = getPendingPath();
  try {
    if (fs.existsSync(p)) {
      const data = JSON.parse(fs.readFileSync(p, 'utf8'));
      if (Array.isArray(data)) return data;
    }
  } catch (e) {
    console.error('Failed to load pending items:', e);
  }
  return [];
}

function savePendingList(items) {
  const p = getPendingPath();
  try {
    fs.writeFileSync(p, JSON.stringify(items, null, 2), 'utf8');
    return items;
  } catch (e) {
    console.error('Failed to save pending items:', e);
    return [];
  }
}

module.exports = {
  loadSettings,
  saveSettings,
  loadPendingList,
  savePendingList,
  getAppDataDir,
  DEFAULT_SETTINGS,
};
