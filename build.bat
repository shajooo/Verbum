@echo off
setlocal enabledelayedexpansion
:: =============================================================================
:: Verbum build script (Audited against MASTER.md §6.1)
:: Run from the project root:  build.bat
:: Produces:  dist\Verbum Setup *.exe  (NSIS installer)
::
:: SAFETY: This script only deletes the "dist\" folder inside the project.
::         It never touches anything outside the project root.
:: =============================================================================

:: ── 0. Locate project root (the folder containing this script) ──────────────
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
echo [build] Project root: %ROOT%

if "%ROOT%"=="" (
  echo [build] BUILD FAILED: Could not determine project root. Aborting.
  exit /b 1
)
echo %ROOT%| findstr /r "^[A-Za-z]:$" >nul 2>&1 && (
  echo [build] BUILD FAILED: ROOT resolved to a drive root. Aborting.
  exit /b 1
)
echo %ROOT%| findstr /r "^[A-Za-z]:\\$" >nul 2>&1 && (
  echo [build] BUILD FAILED: ROOT resolved to a drive root. Aborting.
  exit /b 1
)

:: ── 1. Preflight and fail loudly: Node, npm, and Python ─────────────────────
where node >nul 2>&1
if errorlevel 1 (
  echo [build] BUILD FAILED: node.exe not found on PATH. Install Node.js 18+ and retry.
  exit /b 1
)
for /f "tokens=*" %%v in ('node --version') do echo [build] Node version: %%v

where npm >nul 2>&1
if errorlevel 1 (
  echo [build] BUILD FAILED: npm not found on PATH.
  exit /b 1
)

:: Python interpreter configuration (MASTER.md §6.1 step 1)
set "PYTHON_EXE=C:\Python314\python.exe"
set "VENV_PY=%ROOT%\transcription\.venv\Scripts\python.exe"
if exist "%VENV_PY%" (
  set "PYTHON=%VENV_PY%"
  echo [build] Using venv Python: %VENV_PY%
) else if exist "%PYTHON_EXE%" (
  set "PYTHON=%PYTHON_EXE%"
  echo [build] Using configured Python: %PYTHON_EXE%
) else (
  where python >nul 2>&1
  if errorlevel 1 (
    echo [build] BUILD FAILED: No suitable Python interpreter found. Aborting.
    exit /b 1
  )
  for /f "tokens=*" %%p in ('where python') do (
    if not defined PYTHON set "PYTHON=%%p"
  )
  echo [build] Using system Python: !PYTHON!
)

:: ── 2. Install only what is missing (Node & Python deps) ───────────────────
echo [build] Checking Node dependencies...
cd /d "%ROOT%"
if not exist "%ROOT%\node_modules" (
  echo [build] Installing missing node_modules...
  call npm.cmd install
  if errorlevel 1 (
    echo [build] BUILD FAILED: npm install failed.
    exit /b 1
  )
)

echo [build] Installing missing Python requirements...
"%PYTHON%" -m pip install -r "%ROOT%\transcription\requirements.txt"
if errorlevel 1 (
  echo [build] BUILD FAILED: Python pip requirements install failed.
  exit /b 1
)

:: ── 3. Verify sidecar imports with chosen Python ────────────────────────────
echo [build] Verifying sidecar imports...
"%PYTHON%" -c "import fastapi, uvicorn, faster_whisper, ctranslate2, multipart; print('[build] Sidecar imports OK')"
if errorlevel 1 (
  echo [build] BUILD FAILED: Required Python sidecar modules failed to import. Aborting.
  exit /b 1
)

:: ── 4. Sync the UI mirror (MASTER.md §3.3 & §6.1 step 4) ────────────────────
echo [build] Syncing UI mirror: ui\index.html -^> app\ui\index.html...
if not exist "%ROOT%\app\ui" mkdir "%ROOT%\app\ui"
copy /Y "%ROOT%\ui\index.html" "%ROOT%\app\ui\index.html" >nul
if errorlevel 1 (
  echo [build] BUILD FAILED: Failed to sync UI mirror.
  exit /b 1
)

:: ── 5. Build Python sidecar with PyInstaller ────────────────────────────────
echo [build] Checking for PyInstaller...
"%PYTHON%" -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
  echo [build] PyInstaller not found. Installing pyinstaller into %PYTHON%...
  "%PYTHON%" -m pip install pyinstaller
  if errorlevel 1 (
    echo [build] BUILD FAILED: Failed to install PyInstaller.
    exit /b 1
  )
)

echo [build] Building Python sidecar (transcription\service.py -^> app\bin\service.exe)...
if not exist "%ROOT%\app\bin" mkdir "%ROOT%\app\bin"

"%PYTHON%" -m PyInstaller ^
  --onefile ^
  --distpath "%ROOT%\app\bin" ^
  --workpath "%ROOT%\build\pyinstaller-work" ^
  --specpath "%ROOT%\build\pyinstaller-spec" ^
  --hidden-import=engine ^
  --hidden-import=multipart ^
  --hidden-import=uvicorn.logging ^
  --hidden-import=uvicorn.loops ^
  --hidden-import=uvicorn.loops.auto ^
  --hidden-import=uvicorn.protocols ^
  --hidden-import=uvicorn.protocols.http ^
  --hidden-import=uvicorn.protocols.http.auto ^
  --hidden-import=uvicorn.protocols.websockets ^
  --hidden-import=uvicorn.protocols.websockets.auto ^
  --hidden-import=uvicorn.lifespans ^
  --hidden-import=uvicorn.lifespans.on ^
  --name service ^
  "%ROOT%\transcription\service.py"
if errorlevel 1 (
  echo [build] BUILD FAILED: PyInstaller build failed.
  exit /b 1
)

:: ── 6. Verify bundled files before packaging ────────────────────────────────
echo [build] Verifying required bundled files...
if not exist "%ROOT%\app\bin\autopaste.exe" (
  echo [build] BUILD FAILED: Missing app\bin\autopaste.exe
  exit /b 1
)
if not exist "%ROOT%\app\bin\service.exe" (
  echo [build] BUILD FAILED: Missing app\bin\service.exe
  exit /b 1
)
if not exist "%ROOT%\app\ui\index.html" (
  echo [build] BUILD FAILED: Missing app\ui\index.html
  exit /b 1
)

:: ── 7. Clean previous Electron build output (dist\ only) ────────────────────
set "DIST_DIR=%ROOT%\dist"
echo [build] Cleaning previous build output: %DIST_DIR%

echo %DIST_DIR%| findstr /i /b "%ROOT%" >nul 2>&1
if errorlevel 1 (
  echo [build] BUILD FAILED: DIST_DIR does not appear to be inside project root. Aborting.
  exit /b 1
)

if exist "%DIST_DIR%" (
  echo [build] Removing: %DIST_DIR%
  rd /s /q "%DIST_DIR%"
  if errorlevel 1 (
    echo [build] BUILD FAILED: Failed to remove %DIST_DIR% (files may be locked by a running instance).
    exit /b 1
  )
)

:: ── 8. Run electron-builder and verify output ───────────────────────────────
echo [build] Running electron-builder (NSIS installer)...
cd /d "%ROOT%"
call node_modules\.bin\electron-builder.cmd --win nsis
if errorlevel 1 (
  echo [build] BUILD FAILED: electron-builder failed.
  exit /b 1
)

echo.
echo [build] ============================================================
echo [build]  BUILD SUCCESS: Installer is in:  %DIST_DIR%\
echo [build] ============================================================
endlocal
