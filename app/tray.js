/**
 * Verbum System Tray Module
 * Manages tray icon, context menu, and background lifecycle.
 */

const { Tray, Menu, nativeImage, app } = require('electron');

let tray = null;
let isRecordingState = false;
let currentModelName = 'small';
let onOpenWindowCb = null;
let onToggleRecordCb = null;

function createIcon(isRecording = false) {
  // Generate 16x16 RGBA buffer
  const size = 16;
  const buffer = Buffer.alloc(size * size * 4);
  const center = 7.5;
  const radius = isRecording ? 6.0 : 5.0;

  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const idx = (y * size + x) * 4;
      const dist = Math.sqrt((x - center) ** 2 + (y - center) ** 2);

      if (dist <= radius) {
        if (isRecording) {
          // Bright red circle
          buffer[idx] = 220;     // R
          buffer[idx + 1] = 30;  // G
          buffer[idx + 2] = 30;  // B
          buffer[idx + 3] = 255; // A
        } else {
          // Verbum Teal / Slate circle
          buffer[idx] = 47;      // R
          buffer[idx + 1] = 93;  // G
          buffer[idx + 2] = 80;  // B
          buffer[idx + 3] = 255; // A
        }
      } else {
        buffer[idx + 3] = 0; // Transparent
      }
    }
  }

  return nativeImage.createFromBitmap(buffer, { width: size, height: size });
}

function updateTrayMenu() {
  if (!tray) return;

  const contextMenu = Menu.buildFromTemplate([
    {
      label: 'Open Verbum',
      click: () => {
        if (onOpenWindowCb) onOpenWindowCb();
      },
    },
    {
      label: isRecordingState ? '■ Stop Recording' : '● Start Recording',
      click: () => {
        if (onToggleRecordCb) onToggleRecordCb();
      },
    },
    { type: 'separator' },
    {
      label: `Model: ${currentModelName}`,
      enabled: false,
    },
    { type: 'separator' },
    {
      label: 'Quit',
      click: () => {
        app.isQuitting = true;
        app.quit();
      },
    },
  ]);

  tray.setContextMenu(contextMenu);
  tray.setToolTip(`Verbum - Speech-to-Text (${isRecordingState ? 'RECORDING' : 'Idle'})`);
  tray.setImage(createIcon(isRecordingState));
}

function initTray({ onOpenWindow, onToggleRecord, initialModel = 'small' }) {
  onOpenWindowCb = onOpenWindow;
  onToggleRecordCb = onToggleRecord;
  currentModelName = initialModel;

  tray = new Tray(createIcon(false));
  tray.on('double-click', () => {
    if (onOpenWindowCb) onOpenWindowCb();
  });

  updateTrayMenu();
  return tray;
}

function setTrayRecording(recording) {
  isRecordingState = !!recording;
  updateTrayMenu();
}

function setTrayModel(modelName) {
  currentModelName = modelName;
  updateTrayMenu();
}

module.exports = {
  initTray,
  setTrayRecording,
  setTrayModel,
};
