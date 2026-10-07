"""Odczytuje widoczny tekst z konsoli innego procesu (bez fokusu okna).

Uzycie: screen.py <pid>  -> wypisuje widoczne linie okna konsoli

Jak inject.py: proces wolajacy nie moze byc podlaczony do tej samej konsoli co cel,
dlatego listener uruchamia ten skrypt jako osobny proces (bez okna).
"""
import ctypes
import sys
from ctypes import wintypes

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x1
FILE_SHARE_WRITE = 0x2
OPEN_EXISTING = 3
INVALID_HANDLE = wintypes.HANDLE(-1).value


class COORD(ctypes.Structure):
    _fields_ = [("X", wintypes.SHORT), ("Y", wintypes.SHORT)]


class SMALL_RECT(ctypes.Structure):
    _fields_ = [("Left", wintypes.SHORT), ("Top", wintypes.SHORT),
                ("Right", wintypes.SHORT), ("Bottom", wintypes.SHORT)]


class CONSOLE_SCREEN_BUFFER_INFO(ctypes.Structure):
    _fields_ = [("dwSize", COORD), ("dwCursorPosition", COORD), ("wAttributes", wintypes.WORD),
                ("srWindow", SMALL_RECT), ("dwMaximumWindowSize", COORD)]


def read_screen(pid):
    """Widoczne linie okna konsoli procesu pid."""
    kernel32.FreeConsole()
    if not kernel32.AttachConsole(wintypes.DWORD(pid)):
        raise OSError(f"AttachConsole({pid}) nieudane, blad {ctypes.get_last_error()}")
    try:
        handle = kernel32.CreateFileW("CONOUT$", GENERIC_READ | GENERIC_WRITE,
                                      FILE_SHARE_READ | FILE_SHARE_WRITE, None, OPEN_EXISTING, 0, None)
        if handle == INVALID_HANDLE:
            raise OSError(f"CONOUT$ nieudane, blad {ctypes.get_last_error()}")
        try:
            info = CONSOLE_SCREEN_BUFFER_INFO()
            if not kernel32.GetConsoleScreenBufferInfo(handle, ctypes.byref(info)):
                raise OSError(f"GetConsoleScreenBufferInfo nieudane, blad {ctypes.get_last_error()}")
            win = info.srWindow
            width = win.Right - win.Left + 1
            buf = ctypes.create_unicode_buffer(width)
            read = wintypes.DWORD(0)
            lines = []
            for y in range(win.Top, win.Bottom + 1):
                kernel32.ReadConsoleOutputCharacterW(handle, buf, width, COORD(win.Left, y), ctypes.byref(read))
                lines.append(buf.value[:read.value].rstrip())
            return lines
        finally:
            kernel32.CloseHandle(handle)
    finally:
        kernel32.FreeConsole()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("\n".join(read_screen(int(sys.argv[1]))))
