/**
 * Verbum Python Backend Supervisor
 * Launches, monitors, and terminates the FastAPI transcription sidecar.
 */

const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

let backendProcess = null;
let backendInfo = {
  port: null,
  token: null,
  baseUrl: null,
};
let isIntentionalQuit = false;
let restartCount = 0;
const MAX_RESTARTS = 3;

function getPythonPath() {
  // Check development venv first
  const projectRoot = path.resolve(__dirname, '..');
  const venvPython = path.join(projectRoot, 'transcription', '.venv', 'Scripts', 'python.exe');
  if (fs.existsSync(venvPython)) {
    return venvPython;
  }
  // Check system python
  return 'python';
}

function getServiceScriptPath() {
  const projectRoot = path.resolve(__dirname, '..');
  return path.join(projectRoot, 'transcription', 'service.py');
}

const http = require('http');

function waitForHealth(baseUrl, token, maxRetries = 40) {
  return new Promise((resolve, reject) => {
    let retries = 0;
    const check = () => {
      const req = http.get(
        `${baseUrl}/health`,
        { headers: { Authorization: `Bearer ${token}` } },
        (res) => {
          if (res.statusCode === 200) {
            resolve();
          } else {
            retry();
          }
        }
      );
      req.on('error', () => retry());
      req.setTimeout(500, () => {
        req.destroy();
        retry();
      });
    };

    const retry = () => {
      retries++;
      if (retries >= maxRetries) {
        return reject(new Error('Backend health check timed out after launch'));
      }
      setTimeout(check, 80);
    };

    check();
  });
}

function startBackend() {
  return new Promise((resolve, reject) => {
    const pythonExe = getPythonPath();
    const serviceScript = getServiceScriptPath();

    if (!fs.existsSync(serviceScript)) {
      return reject(new Error(`Transcription service script not found: ${serviceScript}`));
    }

    console.log(`[Backend] Starting Python sidecar with ${pythonExe}...`);

    backendProcess = spawn(pythonExe, [serviceScript, '--port', '0'], {
      cwd: path.dirname(serviceScript),
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    });

    let isResolved = false;

    backendProcess.stdout.on('data', (data) => {
      const text = data.toString();
      console.log(`[Backend stdout] ${text.trim()}`);

      const match = text.match(/VERBUM_BACKEND_READY\s+port=(\d+)\s+token=([a-f0-9]+)/);
      if (match && !isResolved) {
        backendInfo.port = parseInt(match[1], 10);
        backendInfo.token = match[2];
        backendInfo.baseUrl = `http://127.0.0.1:${backendInfo.port}`;
        isResolved = true;
        restartCount = 0;

        waitForHealth(backendInfo.baseUrl, backendInfo.token)
          .then(() => {
            console.log(`[Backend] Verified ready on ${backendInfo.baseUrl}`);
            resolve(backendInfo);
          })
          .catch((err) => {
            console.error('[Backend] Health verification failed:', err);
            reject(err);
          });
      }
    });

    backendProcess.stderr.on('data', (data) => {
      console.error(`[Backend stderr] ${data.toString().trim()}`);
    });

    backendProcess.on('exit', (code, signal) => {
      console.warn(`[Backend] Exited with code ${code}, signal ${signal}`);
      backendProcess = null;

      if (!isIntentionalQuit && restartCount < MAX_RESTARTS) {
        restartCount++;
        console.log(`[Backend] Attempting restart ${restartCount}/${MAX_RESTARTS}...`);
        setTimeout(() => {
          startBackend().catch((err) => console.error('[Backend] Restart failed:', err));
        }, 1000);
      }
    });

    // Timeout after 15 seconds if handshake is not seen
    setTimeout(() => {
      if (!isResolved) {
        reject(new Error('Timed out waiting for Python backend handshake'));
      }
    }, 15000);
  });
}

function stopBackend() {
  isIntentionalQuit = true;
  if (backendProcess) {
    console.log('[Backend] Stopping Python sidecar...');
    backendProcess.kill();
    backendProcess = null;
  }
}

function getBackendInfo() {
  return backendInfo;
}

module.exports = {
  startBackend,
  stopBackend,
  getBackendInfo,
};
