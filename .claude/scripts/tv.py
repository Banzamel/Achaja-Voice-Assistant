"""Sterowanie telewizorem z Androidem przez ADB (siec lokalna).

Uzycie:
  tv.py connect                  polaczenie (pierwszy raz: zatwierdz pytanie na ekranie TV)
  tv.py status                   polaczenie, zasilanie, aktualna aplikacja
  tv.py on | off                 wlacz (budzenie / Wake-on-LAN) | usypianie
  tv.py apps                     zainstalowane aplikacje
  tv.py app <nazwa>              uruchom aplikacje (netflix, youtube, spotify, ... lub fragment pakietu)
  tv.py netflix <id_tytulu>      otworz tytul Netflix (id z adresu netflix.com/title/<id>)
  tv.py youtube <zapytanie>      wyszukaj na YouTube
  tv.py key <klawisz> [...]      klawisze pilota: ok up down left right back home play pause
                                 playpause stop next prev ff rew volup voldown mute power
  tv.py volume <up|down> [n]     glosnosc n krokow
  tv.py text "<tekst>"           wpisz tekst w aktywne pole (np. wyszukiwarka)
  tv.py screen                   zrzut ekranu TV -> state/tv_screen.png (Achaja moze go obejrzec)
"""
import re
import socket
import subprocess
import sys
import time
import urllib.parse

from common import CREATE_NO_WINDOW, ROOT, STATE, load_config, read_json, write_json

ADB = ROOT / "tools" / "platform-tools" / "adb.exe"
TV_STATE = STATE / "tv.json"

KEYS = {
    "ok": 23, "enter": 66, "up": 19, "down": 20, "left": 21, "right": 22, "back": 4, "home": 3,
    "play": 126, "pause": 127, "playpause": 85, "stop": 86, "next": 87, "prev": 88,
    "ff": 90, "rew": 89, "volup": 24, "voldown": 25, "mute": 164, "power": 26,
    "wakeup": 224, "sleep": 223, "menu": 82, "search": 84, "info": 165,
}

APPS = {
    "netflix": "com.netflix.ninja",
    "youtube": "com.google.android.youtube.tv",
    "spotify": "com.spotify.tv.android",
    "disney": "com.disney.disneyplus",
    "prime": "com.amazon.amazonvideo.livingroom",
    "max": "com.wbd.stream",
}


def cfg():
    return load_config().get("tv", {})


def serial():
    c = cfg()
    return f"{c['host']}:{c.get('port', 5555)}"


def adb(*args, timeout=15, check=False):
    r = subprocess.run([str(ADB), "-s", serial(), *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout, creationflags=CREATE_NO_WINDOW)
    if check and r.returncode != 0:
        sys.exit(f"ADB: {(r.stderr or r.stdout).strip()}")
    return r.stdout.strip()


def shell(cmd, timeout=15):
    return adb("shell", cmd, timeout=timeout)


def connected():
    r = subprocess.run([str(ADB), "devices"], capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
    return any(line.startswith(serial()) and line.endswith("device") for line in r.stdout.splitlines())


def connect(quiet=False):
    if connected():
        return True
    r = subprocess.run([str(ADB), "connect", serial()], capture_output=True, text=True, timeout=15,
                       creationflags=CREATE_NO_WINDOW)
    out = (r.stdout + r.stderr).strip()
    for _ in range(10):  # po pierwszym polaczeniu TV pyta o zgode - czekamy chwile
        if connected():
            remember_mac()
            return True
        if "unauthorized" in subprocess.run([str(ADB), "devices"], capture_output=True, text=True,
                                            creationflags=CREATE_NO_WINDOW).stdout:
            if not quiet:
                print("Zatwierdz na ekranie telewizora: 'Zezwolic na debugowanie?' (zaznacz 'Zawsze zezwalaj').")
        time.sleep(1.5)
    if not quiet:
        print(f"Brak polaczenia z TV ({serial()}): {out}")
    return False


def remember_mac():
    """MAC telewizora do Wake-on-LAN (z tabeli ARP)."""
    arp = subprocess.run(["arp", "-a", cfg()["host"]], capture_output=True, text=True,
                         creationflags=CREATE_NO_WINDOW).stdout
    m = re.search(r"([0-9a-f]{2}(?:-[0-9a-f]{2}){5})", arp, re.I)
    if m:
        write_json(TV_STATE, {**read_json(TV_STATE, {}), "mac": m.group(1)})


def wake_on_lan():
    mac = read_json(TV_STATE, {}).get("mac") or cfg().get("mac")
    if not mac:
        return False
    raw = bytes.fromhex(mac.replace("-", "").replace(":", ""))
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for _ in range(3):
            s.sendto(b"\xff" * 6 + raw * 16, ("255.255.255.255", 9))
    return True


def awake():
    return "mWakefulness=Awake" in shell("dumpsys power | grep mWakefulness")


def current_app():
    out = shell("dumpsys window | grep -E 'mCurrentFocus|mFocusedApp'")
    m = re.search(r"([a-zA-Z0-9_.]+)/[a-zA-Z0-9_.$]+", out)
    return m.group(1) if m else "?"


def require():
    if not connect():
        sys.exit(1)


def key(*names):
    codes = []
    for n in names:
        n = n.lower()
        if n not in KEYS:
            sys.exit(f"Nieznany klawisz '{n}'. Dostepne: {', '.join(KEYS)}")
        codes.append(str(KEYS[n]))
    for code in codes:
        shell(f"input keyevent {code}")
        time.sleep(0.15)


def resolve_app(name):
    name = name.lower()
    if name in APPS:
        return APPS[name]
    packages = [line.replace("package:", "") for line in shell("pm list packages").splitlines()]
    hits = [p for p in packages if name in p.lower()]
    if not hits:
        sys.exit(f"Nie znaleziono aplikacji '{name}'. Uzyj: tv.py apps")
    return min(hits, key=len)


def launch(package):
    shell(f"monkey -p {package} -c android.intent.category.LEANBACK_LAUNCHER 1")


def view(url, package):
    shell(f'am start -a android.intent.action.VIEW -d "{url}" {package}')


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd, args = sys.argv[1], sys.argv[2:]

    if cmd == "connect":
        print("Polaczono z TV." if connect() else "")
    elif cmd == "status":
        if not connect(quiet=True):
            print("TV niedostepny przez ADB (wylaczony albo debugowanie sieciowe nieaktywne).")
            return
        print(f"Polaczono | ekran: {'wlaczony' if awake() else 'uspiony'} | aplikacja: {current_app()}")
    elif cmd == "on":
        if not connect(quiet=True):
            if wake_on_lan():
                print("Wyslano Wake-on-LAN, czekam na TV...")
                for _ in range(10):
                    time.sleep(3)
                    if connect(quiet=True):
                        break
            if not connected():
                sys.exit("Nie udalo sie obudzic TV (wlacz w TV: 'Wlaczanie przez Wi-Fi/siec').")
        key("wakeup")
        print("TV wlaczony.")
    elif cmd == "off":
        require()
        key("sleep")
        print("TV uspiony.")
    elif cmd == "apps":
        require()
        for line in sorted(shell("pm list packages -3").splitlines()):
            print(line.replace("package:", ""))
    elif cmd == "app":
        require()
        key("wakeup")
        pkg = resolve_app(" ".join(args))
        launch(pkg)
        print(f"Uruchomiono {pkg}.")
    elif cmd == "netflix":
        require()
        key("wakeup")
        title = re.sub(r"\D", "", " ".join(args))
        shell(f'am start -c android.intent.category.LEANBACK_LAUNCHER -a android.intent.action.VIEW '
              f'-d "https://www.netflix.com/title/{title}" -f 0x10808000 -e source 30 '
              f'com.netflix.ninja/.MainActivity')
        print(f"Otwarto tytul Netflix {title}.")
    elif cmd == "youtube":
        require()
        key("wakeup")
        view("https://www.youtube.com/results?search_query=" + urllib.parse.quote(" ".join(args)), APPS["youtube"])
        print("Wyszukano na YouTube.")
    elif cmd == "key":
        require()
        key(*args)
        print("OK")
    elif cmd == "volume":
        require()
        steps = int(args[1]) if len(args) > 1 else 3
        key(*(["volup" if args[0] == "up" else "voldown"] * steps))
        print("OK")
    elif cmd == "text":
        require()
        shell("input text " + "'" + " ".join(args).replace(" ", "%s").replace("'", "") + "'")
        print("OK")
    elif cmd == "screen":
        require()
        out = STATE / "tv_screen.png"
        data = subprocess.run([str(ADB), "-s", serial(), "exec-out", "screencap", "-p"], capture_output=True,
                              timeout=20, creationflags=CREATE_NO_WINDOW).stdout
        out.write_bytes(data)
        print(f"Zrzut ekranu: {out}")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
