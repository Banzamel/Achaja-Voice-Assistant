"""Diagnostyka: wypisuje tekst widoczny w oknie konsoli innego procesu (tylko odczyt).

Uzycie: console_dump.py <pid> [ostatnie_linie]
"""
import ctypes
import sys
from ctypes import wintypes

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class COORD(ctypes.Structure):
    _fields_ = [("X", wintypes.SHORT), ("Y", wintypes.SHORT)]


class SMALL_RECT(ctypes.Structure):
    _fields_ = [("Left", wintypes.SHORT), ("Top", wintypes.SHORT),
                ("Right", wintypes.SHORT), ("Bottom", wintypes.SHORT)]


class CSBI(ctypes.Structure):
    _fields_ = [("dwSize", COORD), ("dwCursorPosition", COORD), ("wAttributes", wintypes.WORD),
                ("srWindow", SMALL_RECT), ("dwMaximumWindowSize", COORD)]


def dump(pid, last):
    kernel32.FreeConsole()
    if not kernel32.AttachConsole(wintypes.DWORD(pid)):
        raise OSError(f"AttachConsole({pid}) nieudane, blad {ctypes.get_last_error()}")
    try:
        h = kernel32.CreateFileW("CONOUT$", 0xC0000000, 3, None, 3, 0, None)
        info = CSBI()
        kernel32.GetConsoleScreenBufferInfo(h, ctypes.byref(info))
        width, bottom = info.dwSize.X, info.dwCursorPosition.Y
        bottom = max(bottom, info.srWindow.Bottom)
        lines = []
        for y in range(max(0, bottom - last + 1), bottom + 1):
            buf = ctypes.create_unicode_buffer(width)
            read = wintypes.DWORD()
            kernel32.ReadConsoleOutputCharacterW(h, buf, width, COORD(0, y), ctypes.byref(read))
            lines.append(buf.value[:read.value].rstrip())
        kernel32.CloseHandle(h)
    finally:
        kernel32.FreeConsole()
    return "\n".join(lines)


if __name__ == "__main__":
    text = dump(int(sys.argv[1]), int(sys.argv[2]) if len(sys.argv) > 2 else 60)
    with open(sys.argv[3] if len(sys.argv) > 3 else "CON", "w", encoding="utf-8") as f:
        f.write(text)
