"""Dostep do konsoli innego procesu (okna Claude Code) bez fokusu: klawisze, odczyt ekranu, ukrywanie okna.

Proces moze byc podlaczony tylko do jednej konsoli naraz. Gdy proces nie ma wlasnej
konsoli (aplikacja okienkowa pythonw), robi to w sobie - szybko, bez startu nowego Pythona.
Nasluch w oknie konsoli (start-achaja.cmd) wola inject.py / screen.py jako osobne procesy.
"""
import ctypes
import threading
from ctypes import wintypes

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32.GetConsoleWindow.restype = wintypes.HWND
kernel32.CreateFileW.restype = wintypes.HANDLE

KEY_EVENT = 0x0001
LEFT_CTRL_PRESSED = 0x0008
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x1
FILE_SHARE_WRITE = 0x2
OPEN_EXISTING = 3
INVALID_HANDLE = wintypes.HANDLE(-1).value
SW_HIDE, SW_SHOW, SW_RESTORE = 0, 5, 9

_lock = threading.Lock()


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


class COORD(ctypes.Structure):
    _fields_ = [("X", wintypes.SHORT), ("Y", wintypes.SHORT)]


class SMALL_RECT(ctypes.Structure):
    _fields_ = [("Left", wintypes.SHORT), ("Top", wintypes.SHORT),
                ("Right", wintypes.SHORT), ("Bottom", wintypes.SHORT)]


class CONSOLE_SCREEN_BUFFER_INFO(ctypes.Structure):
    _fields_ = [("dwSize", COORD), ("dwCursorPosition", COORD), ("wAttributes", wintypes.WORD),
                ("srWindow", SMALL_RECT), ("dwMaximumWindowSize", COORD)]


# nazwa -> (virtual key, scan code, znak, stan ctrl)
KEYS = {
    "space": (0x20, 0x39, " ", 0),
    "enter": (0x0D, 0x1C, "\r", 0),
    "esc": (0x1B, 0x01, "\x1b", 0),
    "backspace": (0x08, 0x0E, "\x08", 0),
    "ctrl+u": (0x55, 0x16, "\x15", LEFT_CTRL_PRESSED),
}


def has_own_console():
    return bool(kernel32.GetConsoleWindow())


class attached:
    """with attached(pid): ... - na czas bloku proces jest podlaczony do konsoli pid."""

    def __init__(self, pid):
        self.pid = pid

    def __enter__(self):
        _lock.acquire()
        kernel32.FreeConsole()
        if not kernel32.AttachConsole(wintypes.DWORD(self.pid)):
            err = ctypes.get_last_error()
            _lock.release()
            raise OSError(f"AttachConsole({self.pid}) nieudane, blad {err}")
        kernel32.SetConsoleCtrlHandler(None, True)  # ctrl+c w oknie Claude nie zabija tego procesu
        return self

    def __exit__(self, *exc):
        kernel32.FreeConsole()
        _lock.release()
        return False


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


def _open(name):
    handle = kernel32.CreateFileW(name, GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE,
                                  None, OPEN_EXISTING, 0, None)
    if handle in (None, INVALID_HANDLE):
        raise OSError(f"{name} nieudane, blad {ctypes.get_last_error()}")
    return handle


def write_keys(pid, keys):
    """Wpisuje klawisze do pola wejscia konsoli pid (space, enter, esc, ctrl+u, backspace, text:...)."""
    with attached(pid):
        handle = _open("CONIN$")
        try:
            records = build_records(keys)
            arr = (INPUT_RECORD * len(records))(*records)
            written = wintypes.DWORD(0)
            if not kernel32.WriteConsoleInputW(handle, arr, len(records), ctypes.byref(written)):
                raise OSError(f"WriteConsoleInputW nieudane, blad {ctypes.get_last_error()}")
        finally:
            kernel32.CloseHandle(handle)


def read_screen(pid):
    """Widoczne linie okna konsoli procesu pid."""
    with attached(pid):
        handle = _open("CONOUT$")
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


def console_window(pid):
    """Uchwyt okna konsoli procesu pid (None, gdy brak - np. proces juz nie zyje)."""
    try:
        with attached(pid):
            return kernel32.GetConsoleWindow() or None
    except OSError:
        return None


def set_visible(pid, visible):
    """Pokazuje / ukrywa okno konsoli Claude. W Windows Terminal (zamiast conhost) moze nie zadzialac."""
    hwnd = console_window(pid)
    if not hwnd:
        return False
    if visible:
        user32.ShowWindow(hwnd, SW_RESTORE if user32.IsIconic(hwnd) else SW_SHOW)
        user32.SetForegroundWindow(hwnd)
    else:
        user32.ShowWindow(hwnd, SW_HIDE)
    return True


def is_visible(pid):
    hwnd = console_window(pid)
    return bool(hwnd and user32.IsWindowVisible(hwnd))
