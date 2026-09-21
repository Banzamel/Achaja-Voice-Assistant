"""Wspolne sciezki i konfiguracja Achai."""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / ".claude" / "scripts"
STATE = ROOT / "state"
AGENTS_STATE = STATE / "agents"
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
PYTHONW = ROOT / ".venv" / "Scripts" / "pythonw.exe"
MODEL_DIR = ROOT / "models" / "vosk-model-small-pl-0.22"

STATE.mkdir(exist_ok=True)
AGENTS_STATE.mkdir(exist_ok=True)

for stream in (sys.stdout, sys.stderr):
    if stream is not None and hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

CREATE_NEW_CONSOLE = 0x00000010
CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008


def load_config():
    with open(ROOT / "config.json", encoding="utf-8") as f:
        return json.load(f)


def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path, data):
    tmp = Path(str(path) + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def pid_alive(pid):
    import ctypes
    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))  # QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    code = ctypes.c_ulong()
    ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
    ctypes.windll.kernel32.CloseHandle(handle)
    return code.value == 259  # STILL_ACTIVE


def clean_env():
    """Srodowisko bez znacznikow sesji Claude, ktora nas uruchomila.

    Odziedziczone CLAUDE_CODE_CHILD_SESSION itp. wylaczaja zapis rozmowy
    w uruchamianym claude (a bez zapisu nie dziala --resume/--continue).
    """
    markers = ("CLAUDECODE", "CLAUDE_PID", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_ENTRYPOINT",
               "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_SESSION_ATTENDED", "CLAUDE_CODE_BRIDGE_SESSION_ID",
               "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN", "CLAUDE_CODE_SSE_PORT")
    return {k: v for k, v in os.environ.items() if k.upper() not in markers}


def process_name(pid):
    """Nazwa pliku exe procesu (np. 'claude.exe') albo None."""
    import ctypes
    from ctypes import wintypes
    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
    if not handle:
        return None
    buf = ctypes.create_unicode_buffer(1024)
    size = wintypes.DWORD(1024)
    ok = ctypes.windll.kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size))
    ctypes.windll.kernel32.CloseHandle(handle)
    return os.path.basename(buf.value).lower() if ok else None


def single_instance(name):
    """True, jesli to jedyna instancja (nazwany mutex zwalnia sie sam po smierci procesu)."""
    import ctypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    single_instance._handle = kernel32.CreateMutexW(None, False, name)
    return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS


def pick_device(sd, wanted, kind="input"):
    """Urzadzenie audio: numer albo fragment nazwy (np. "JBL"). None = domyslne systemowe / nie znaleziono."""
    if wanted in (None, ""):
        return None
    if str(wanted).isdigit():
        return int(wanted)
    channels = "max_input_channels" if kind == "input" else "max_output_channels"
    for i in sd.query_hostapis(0)["devices"]:  # MME - nazwy jak w ustawieniach Windows
        dev = sd.query_devices(i)
        if dev[channels] > 0 and str(wanted).lower() in dev["name"].lower():
            return i
    return None
