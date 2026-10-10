@echo off
setlocal

echo ========================================================
echo Building VoiceInput - Font Selector + Editor Font Reference Restore
echo ========================================================

:: Always build from this project root and keep all build caches/output local.
cd /d "%~dp0"
if errorlevel 1 (
    echo [ERROR] Could not enter project directory.
    exit /b 1
)

if not exist ".tmp\pyinstaller_config" mkdir ".tmp\pyinstaller_config"
if not exist ".tmp\temp" mkdir ".tmp\temp"
if not exist ".tmp\dist_create_files_font_editor" mkdir ".tmp\dist_create_files_font_editor"
if not exist ".tmp\work_create_files_font_editor" mkdir ".tmp\work_create_files_font_editor"

set "PYINSTALLER_CONFIG_DIR=%~dp0.tmp\pyinstaller_config"
set "TEMP=%~dp0.tmp\temp"
set "TMP=%~dp0.tmp\temp"
set "BUILD_DIST=.tmp\dist_create_files_font_editor"
set "BUILD_WORK=.tmp\work_create_files_font_editor"

:: Use the project's virtual environment so dependencies and PyInstaller are consistent.
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Project virtual environment missing: .venv\Scripts\python.exe
    echo Install the project's requirements before building.
    exit /b 1
)
set "PYTHON=%~dp0.venv\Scripts\python.exe"

"%PYTHON%" -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] PyInstaller is unavailable in the project virtual environment.
    echo Install it inside .venv before building.
    exit /b 1
)

echo.
echo Build profile: Font database selector + exact project/version/format restore in Editor
echo Spec file: VoiceInput.spec
echo Staged output: %BUILD_DIST%\VoiceInput\VoiceInput.exe
echo Work directory: %BUILD_WORK%
echo Existing dist\VoiceInput build will not be overwritten.
echo --------------------------------------------------------
"%PYTHON%" -m PyInstaller --noconfirm --clean --distpath "%BUILD_DIST%" --workpath "%BUILD_WORK%" VoiceInput.spec

if errorlevel 1 (
    echo.
    echo [ERROR] Build failed! Check the log output above.
    exit /b 1
)

if not exist "%BUILD_DIST%\VoiceInput\VoiceInput.exe" (
    echo.
    echo [ERROR] PyInstaller exited but the expected executable was not produced.
    exit /b 1
)

echo.
echo ========================================================
echo [SUCCESS] Build completed successfully!
echo Executable:
echo %BUILD_DIST%\VoiceInput\VoiceInput.exe
echo ========================================================
echo.
exit /b 0
