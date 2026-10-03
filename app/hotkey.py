from __future__ import annotations

"""Native, non-blocking Windows global Ctrl+Space listener."""

import ctypes
from ctypes import wintypes
import logging
import threading
from typing import Callable

LOG = logging.getLogger(__name__)

WH_KEYBOARD_LL = 13
HC_ACTION = 0
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_APP_STOP = 0x8001
VK_CONTROL = 0x11
VK_LCONTROL = 0xA2
VK_RCONTROL = 0xA3
VK_SPACE = 0x20


class _KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class PushToTalkHotkey:
    """Observe Ctrl+Space globally and emit one press and one release.

    The actual keyboard hook lives on a dedicated Windows message-loop thread.
    Callers must marshal UI work to their UI event loop.
    """

    def __init__(self, on_press: Callable[[], None], on_release: Callable[[], None]) -> None:
        self.on_press = on_press
        self.on_release = on_release
        self._ctrl = False
        self._space = False
        self._active = False
        self._press_time = 0.0
        self._latched = False
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._ready = threading.Event()
        self._hook = None
        self._proc = None  # Keep the ctypes callback alive for the hook lifetime.
        self.startup_error: str | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._ready.clear()
        self.startup_error = None
        self._thread = threading.Thread(target=self._run, name="VoiceInputHotkey", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=3):
            self.startup_error = "The Windows keyboard hook did not start within 3 seconds."
            LOG.error(self.startup_error)
        elif self.startup_error:
            LOG.error("Global hotkey unavailable: %s", self.startup_error)
        else:
            LOG.info("Native Windows Ctrl+Space hook is active")

    def stop(self) -> None:
        thread = self._thread
        if not thread:
            return
        if self._thread_id:
            _user32.PostThreadMessageW(self._thread_id, WM_APP_STOP, 0, 0)
        thread.join(timeout=2)
        self._thread = None

    def _run(self) -> None:
        self._thread_id = _kernel32.GetCurrentThreadId()
        self._proc = _HOOKPROC(self._callback)
        module = _kernel32.GetModuleHandleW(None)
        self._hook = _user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, module, 0)
        if not self._hook:
            self.startup_error = f"Windows denied the global keyboard hook: {ctypes.WinError(ctypes.get_last_error())}"
            self._ready.set()
            return
        self._ready.set()
        message = wintypes.MSG()
        try:
            while True:
                result = _user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result <= 0 or message.message == WM_APP_STOP:
                    break
                _user32.TranslateMessage(ctypes.byref(message))
                _user32.DispatchMessageW(ctypes.byref(message))
        finally:
            if self._hook:
                _user32.UnhookWindowsHookEx(self._hook)
                self._hook = None
            self._thread_id = 0
            LOG.info("Native Windows keyboard hook stopped")

    def _callback(self, code: int, message: int, data: int) -> int:
        try:
            if code == HC_ACTION:
                event = ctypes.cast(data, ctypes.POINTER(_KBDLLHOOKSTRUCT)).contents
                # Ctrl+Space is also used by Windows and some applications for
                # input-language actions.  Do not pass its Space key through,
                # otherwise those actions can open while Voice Input records.
                suppress = event.vkCode == VK_SPACE and (self._ctrl or self._space)
                if message in (WM_KEYDOWN, WM_SYSKEYDOWN):
                    self._handle_key_event(event.vkCode, True)
                elif message in (WM_KEYUP, WM_SYSKEYUP):
                    self._handle_key_event(event.vkCode, False)
                if suppress:
                    return 1
        except Exception:
            # An exception must never escape a Windows callback or the hook can
            # be removed without any visible error.
            LOG.exception("Unhandled error in native keyboard callback")
        return _user32.CallNextHookEx(self._hook, code, message, data)

    def _handle_key_event(self, virtual_key: int, is_down: bool) -> None:
        if virtual_key in (VK_CONTROL, VK_LCONTROL, VK_RCONTROL):
            self._ctrl = is_down
        elif virtual_key == VK_SPACE:
            self._space = is_down
        else:
            return
        if self._ctrl and self._space and not self._active:
            self._active = True
            self._latched = False
            self._press_time = _kernel32.GetTickCount64() / 1000.0
            LOG.info("Ctrl+Space pressed (native hook)")
            self._invoke(self.on_press, "press")
        elif self._active and not (self._ctrl and self._space) and not self._latched:
            duration = (_kernel32.GetTickCount64() / 1000.0) - self._press_time
            if duration < 0.35:
                # Short tap: latch it on
                self._latched = True
                LOG.info("Ctrl+Space tap detected: latching ON")
            else:
                self._active = False
                LOG.info("Ctrl+Space released (native hook)")
                self._invoke(self.on_release, "release")
        elif self._active and self._latched and self._ctrl and self._space:
            # It was latched, and they pressed it again to turn it off
            self._active = False
            self._latched = False
            LOG.info("Ctrl+Space pressed again to unlatch (native hook)")
            self._invoke(self.on_release, "release")

    @staticmethod
    def _invoke(callback: Callable[[], None], event_name: str) -> None:
        try:
            callback()
        except Exception:
            LOG.exception("Hotkey %s callback failed", event_name)


_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_LRESULT = ctypes.c_ssize_t
_HOOKPROC = ctypes.WINFUNCTYPE(_LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

_kernel32.GetCurrentThreadId.restype = wintypes.DWORD
_kernel32.GetTickCount64.restype = ctypes.c_uint64
_kernel32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
_kernel32.GetModuleHandleW.restype = wintypes.HMODULE
_user32.SetWindowsHookExW.argtypes = (ctypes.c_int, _HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD)
_user32.SetWindowsHookExW.restype = wintypes.HANDLE
_user32.CallNextHookEx.argtypes = (wintypes.HANDLE, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
_user32.CallNextHookEx.restype = _LRESULT
_user32.UnhookWindowsHookEx.argtypes = (wintypes.HANDLE,)
_user32.UnhookWindowsHookEx.restype = wintypes.BOOL
_user32.GetMessageW.argtypes = (ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT)
_user32.GetMessageW.restype = ctypes.c_int
_user32.TranslateMessage.argtypes = (ctypes.POINTER(wintypes.MSG),)
_user32.DispatchMessageW.argtypes = (ctypes.POINTER(wintypes.MSG),)
_user32.PostThreadMessageW.argtypes = (wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
_user32.PostThreadMessageW.restype = wintypes.BOOL
