from __future__ import annotations
import pyperclip
import ctypes
import time
from ctypes import wintypes

# Virtual keys for paste
VK_CONTROL = 0x11
VK_V = 0x56
KEYEVENTF_KEYUP = 0x0002

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))
    ]

class INPUT(ctypes.Structure):
    class _INPUT(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", ctypes.c_ulong * 7), ("hi", ctypes.c_ulong * 4)]
    _anonymous_ = ("_input",)
    _fields_ = [("type", wintypes.DWORD), ("_input", _INPUT)]

def _send_key(vk: int, is_down: bool):
    flags = 0 if is_down else KEYEVENTF_KEYUP
    x = INPUT(type=1, ki=KEYBDINPUT(wVk=vk, dwFlags=flags))
    ctypes.windll.user32.SendInput(1, ctypes.byref(x), ctypes.sizeof(x))

def copy_text(text: str) -> None:
    pyperclip.copy(text)

def paste_text(text: str) -> None:
    pyperclip.copy(text)
    time.sleep(0.05) # Yield to ensure modifiers are physically released
    _send_key(VK_CONTROL, True)
    _send_key(VK_V, True)
    time.sleep(0.01)
    _send_key(VK_V, False)
    _send_key(VK_CONTROL, False)
