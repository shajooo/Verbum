using System;
using System.Runtime.InteropServices;
using System.Diagnostics;
using System.Threading;

class Program {
    [DllImport("user32.dll")]
    static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, UIntPtr dwExtraInfo);

    [DllImport("user32.dll")]
    static extern bool SetForegroundWindow(IntPtr hWnd);

    [DllImport("user32.dll")]
    static extern IntPtr GetForegroundWindow();

    const byte VK_CONTROL = 0x11;
    const byte VK_V = 0x56;
    const uint KEYEVENTF_KEYUP = 0x0002;

    static void Main(string[] args) {
        // Parse delay arg
        int delay = 150;
        int customDelay;
        if (args.Length > 0 && int.TryParse(args[0], out customDelay)) {
            delay = customDelay;
        }

        Thread.Sleep(delay);

        // Send Ctrl+V to the currently active window
        keybd_event(VK_CONTROL, 0, 0, UIntPtr.Zero);
        keybd_event(VK_V, 0, 0, UIntPtr.Zero);
        Thread.Sleep(20); // Small gap between down and up
        keybd_event(VK_V, 0, KEYEVENTF_KEYUP, UIntPtr.Zero);
        keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, UIntPtr.Zero);
    }
}
