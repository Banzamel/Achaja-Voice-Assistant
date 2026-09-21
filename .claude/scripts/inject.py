"""Wstrzykuje nacisniecia klawiszy do konsoli innego procesu (bez fokusu okna).

Uzycie: inject.py <pid> <klawisz> [<klawisz> ...]
Klawisze: space, enter, esc, ctrl+u, backspace, albo text:<dowolny tekst>

Proces wolajacy nie moze byc podlaczony do tej samej konsoli co cel,
dlatego listener uruchamia ten skrypt jako osobny proces (bez okna).
"""
import ctypes
import sys
from ctypes import wintypes

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

KEY_EVENT = 0x0001
LEFT_CTRL_PRESSED = 0x0008
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x1
FILE_SHARE_WRITE = 0x2
OPEN_EXISTING = 3


class KEY_EVENT_RECORD(ctypes.Structure):
    _fields_ = [
        ("bKeyDown", wintypes.BOOL),
        ("wRepeatCount", wintypes.WORD),
        ("wVirtualKeyCode", wintypes.WORD),
        ("wVirtualScanCode", wintypes.WORD),
        ("uChar", wintypes.WCHAR),
        ("dwControlKeyState", wintypes.DWORD),
    ]


class _EVENT(ctypes.Union):
    _fields_ = [("KeyEvent", KEY_EVENT_RECORD), ("_pad", ctypes.c_byte * 16)]


class INPUT_RECORD(ctypes.Structure):
    _fields_ = [("EventType", wintypes.WORD), ("Event", _EVENT)]


# nazwa -> (virtual key, scan code, znak, stan ctrl)
KEYS = {
    "space": (0x20, 0x39, " ", 0),
    "enter": (0x0D, 0x1C, "\r", 0),
    "esc": (0x1B, 0x01, "\x1b", 0),
    "backspace": (0x08, 0x0E, "\x08", 0),
    "ctrl+u": (0x55, 0x16, "\x15", LEFT_CTRL_PRESSED),
}


def _record(vk, scan, char, ctrl, down):
    rec = INPUT_RECORD()
    rec.EventType = KEY_EVENT
    k = rec.Event.KeyEvent
    k.bKeyDown = down
    k.wRepeatCount = 1
    k.wVirtualKeyCode = vk
    k.wVirtualScanCode = scan
    k.uChar = char
    k.dwControlKeyState = ctrl
    return rec


def build_records(keys):
    records = []
    for key in keys:
        if key.startswith("text:"):
            for ch in key[5:]:
                records.append(_record(0, 0, ch, 0, True))
                records.append(_record(0, 0, ch, 0, False))
            continue
        vk, scan, char, ctrl = KEYS[key]
        records.append(_record(vk, scan, char, ctrl, True))
        records.append(_record(vk, scan, char, ctrl, False))
    return records


def inject(pid, keys):
    kernel32.FreeConsole()
    if not kernel32.AttachConsole(wintypes.DWORD(pid)):
        raise OSError(f"AttachConsole({pid}) nieudane, blad {ctypes.get_last_error()}")
    try:
        handle = kernel32.CreateFileW(
            "CONIN$", GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE,
            None, OPEN_EXISTING, 0, None,
        )
        records = build_records(keys)
        arr = (INPUT_RECORD * len(records))(*records)
        written = wintypes.DWORD(0)
        if not kernel32.WriteConsoleInputW(handle, arr, len(records), ctypes.byref(written)):
            raise OSError(f"WriteConsoleInputW nieudane, blad {ctypes.get_last_error()}")
        kernel32.CloseHandle(handle)
    finally:
        kernel32.FreeConsole()


if __name__ == "__main__":
    inject(int(sys.argv[1]), sys.argv[2:])
