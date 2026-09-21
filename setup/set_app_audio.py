"""Przypisuje programowi (np. claude.exe) wlasny mikrofon/glosnik - bez zmiany domyslnych w systemie.

To samo, co Ustawienia -> Dzwiek -> Preferencje dotyczace glosnosci aplikacji i urzadzen.
Uzywa nieudokumentowanego IAudioPolicyConfigFactory (jak EarTrumpet/SoundVolumeView).
Windows zapamietuje wybor dla sciezki exe, wiec wystarczy jeden dzialajacy proces.

Uzycie:
  set_app_audio.py <pid> input  "<fragment nazwy>"    np. 1234 input "JBL"
  set_app_audio.py <pid> output "<fragment nazwy>"
  set_app_audio.py <pid> input  default              przywraca domyslny systemowy
  set_app_audio.py list                              urzadzenia audio z rejestru
"""
import ctypes
import sys
import uuid
import winreg
from ctypes import wintypes

MMDEV = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio"
PKEY_NAME = "{a45c254e-df1c-4efd-8020-67d146a850e0},2"        # np. "Zestaw sluchawkowy"
PKEY_IFACE = "{b3f8fa53-0004-438e-9003-51a46e139bfc},6"       # np. "JBL TUNE510BT Hands-Free"
TOKEN = "\\\\?\\SWD#MMDEVAPI#"
IFACE = {"output": "#{e6327cad-dcec-4949-ae8a-991e976a79d2}",
         "input": "#{2eef81be-33fa-4800-9670-1cd474972c3f}"}
FLOW = {"output": 0, "input": 1}  # eRender / eCapture

combase = ctypes.WinDLL("combase")
HRESULT = ctypes.c_long


class GUID(ctypes.Structure):
    _fields_ = [("d", ctypes.c_ubyte * 16)]


def guid(s):
    g = GUID()
    ctypes.memmove(g.d, uuid.UUID(s).bytes_le, 16)
    return g


def hstring(s):
    h = ctypes.c_void_p()
    combase.WindowsCreateString(ctypes.c_wchar_p(s), len(s), ctypes.byref(h))
    return h


def hstring_value(h):
    if not h:
        return ""
    combase.WindowsGetStringRawBuffer.restype = ctypes.c_wchar_p
    return combase.WindowsGetStringRawBuffer(h, None)


def devices(kind):
    """[(endpoint_id, opis)] aktywnych urzadzen z rejestru."""
    result = []
    base = MMDEV + ("\\Capture" if kind == "input" else "\\Render")
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as root:
        for i in range(winreg.QueryInfoKey(root)[0]):
            sub = winreg.EnumKey(root, i)
            try:
                with winreg.OpenKey(root, sub) as k:
                    if winreg.QueryValueEx(k, "DeviceState")[0] != 1:
                        continue
                with winreg.OpenKey(root, sub + "\\Properties") as p:
                    name = winreg.QueryValueEx(p, PKEY_NAME)[0]
                    iface = winreg.QueryValueEx(p, PKEY_IFACE)[0]
            except OSError:
                continue
            prefix = "{0.0.1.00000000}." if kind == "input" else "{0.0.0.00000000}."
            result.append((prefix + sub, f"{name} ({iface})"))
    return result


def factory():
    combase.RoInitialize(1)
    build = sys.getwindowsversion().build
    iid = "ab3d4648-e242-459f-b02f-541c70306324" if build >= 21390 else "2a59116d-6c4f-45e0-a74f-707e3fef9258"
    ptr = ctypes.c_void_p()
    hr = combase.RoGetActivationFactory(hstring("Windows.Media.Internal.AudioPolicyConfig"),
                                        ctypes.byref(guid(iid)), ctypes.byref(ptr))
    if hr != 0:
        raise OSError(f"RoGetActivationFactory: 0x{hr & 0xFFFFFFFF:08x}")
    return ptr


def method(obj, index, *argtypes):
    vtable = ctypes.cast(ctypes.cast(obj, ctypes.POINTER(ctypes.c_void_p))[0],
                         ctypes.POINTER(ctypes.c_void_p))
    return ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, *argtypes)(vtable[index])


# IInspectable (6) + 19 metod "incomplete" -> Set=25, Get=26
def set_endpoint(obj, pid, kind, device_id):
    fn = method(obj, 25, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_void_p)
    h = hstring(device_id) if device_id else ctypes.c_void_p()
    for role in (0, 1):  # eConsole, eMultimedia
        hr = fn(obj, pid, FLOW[kind], role, h)
        if hr != 0:
            raise OSError(f"SetPersistedDefaultAudioEndpoint: 0x{hr & 0xFFFFFFFF:08x}")


def get_endpoint(obj, pid, kind):
    fn = method(obj, 26, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))
    h = ctypes.c_void_p()
    fn(obj, pid, FLOW[kind], 1, ctypes.byref(h))
    return hstring_value(h)


def main():
    if sys.argv[1] == "list":
        for kind in ("input", "output"):
            print(f"[{kind}]")
            for eid, desc in devices(kind):
                print(f"  {desc}")
        return
    pid, kind, wanted = int(sys.argv[1]), sys.argv[2], sys.argv[3]
    obj = factory()
    if wanted == "default":
        set_endpoint(obj, pid, kind, None)
        print("Przywrocono urzadzenie domyslne.")
        return
    matches = [(e, d) for e, d in devices(kind) if wanted.lower() in d.lower()]
    if not matches:
        sys.exit(f"Nie znaleziono urzadzenia '{wanted}'. Uzyj: set_app_audio.py list")
    eid, desc = matches[0]
    set_endpoint(obj, pid, kind, TOKEN + eid + IFACE[kind])
    print(f"Ustawiono: {desc}")
    print(f"Odczyt kontrolny: {get_endpoint(obj, pid, kind) or '(pusty)'}")


if __name__ == "__main__":
    main()
