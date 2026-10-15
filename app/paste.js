/**
 * Verbum Auto-Paste Module
 * Injects Ctrl+V into the previously active application window.
 */

const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

function pasteToActiveWindow(delayMs = 120) {
  return new Promise((resolve) => {
    // 1. Try precompiled native autopaste.exe
    const exePath = path.join(__dirname, 'bin', 'autopaste.exe');
    if (fs.existsSync(exePath)) {
      const child = spawn(exePath, [delayMs.toString()], {
        detached: true,
        stdio: 'ignore',
        windowsHide: true,
      });
      child.unref();
      setTimeout(resolve, delayMs + 50);
      return;
    }

    // 2. Fallback to PowerShell SendWait
    const psCommand = `Start-Sleep -Milliseconds ${delayMs}; Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.SendKeys]::SendWait('^v')`;
    const ps = spawn('powershell', ['-WindowStyle', 'Hidden', '-Command', psCommand], {
      detached: true,
      stdio: 'ignore',
      windowsHide: true,
    });
    ps.unref();
    setTimeout(resolve, delayMs + 100);
  });
}

module.exports = { pasteToActiveWindow };
