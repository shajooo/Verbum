"""Register Voice Input to start when the current Windows user signs in."""

from __future__ import annotations

import sys
from pathlib import Path
import winreg


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "VoiceInput"


def launch_command() -> str:
    """Return the correctly quoted command Windows should run at sign-in."""
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable)}"'
    entry_point = Path(__file__).resolve().parent.parent / "main.py"
    return f'"{Path(sys.executable)}" "{entry_point}"'


def set_enabled(enabled: bool) -> None:
    """Create or remove this app's per-user Windows startup entry.

    HKCU does not require administrator rights and starts the app only after the
    user signs in, which is the appropriate time for tray and microphone apps.
    """
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, launch_command())
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass
