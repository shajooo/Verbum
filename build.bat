@echo off
setlocal

echo ========================================================
echo Building VoiceInput Executable with PyInstaller
echo ========================================================

:: Change directory to project root
cd /d "%~dp0"

:: Check for virtual environment and activate it if present
if not exist ".venv\Scripts\activate.bat" goto no_venv
echo Activating virtual environment...
call .venv\Scripts\activate.bat
goto venv_done

:no_venv
echo Warning: .venv not found. Using system Python...

:venv_done

:: Ensure PyInstaller is available
python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo PyInstaller not found. Installing pyinstaller...
    python -m pip install pyinstaller
)

echo.
echo Running PyInstaller with VoiceInput.spec...
echo --------------------------------------------------------
python -m PyInstaller --noconfirm --clean VoiceInput.spec

if errorlevel 1 (
    echo.
    echo [ERROR] Build failed! Check the log output above.
    pause
    exit /b 1
)

echo.
echo ========================================================
echo [SUCCESS] Build completed successfully!
echo The output executable is located at:
echo dist\VoiceInput\VoiceInput.exe
echo ========================================================
echo.
pause
