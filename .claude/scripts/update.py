"""Aktualizacje Achai z wydan na GitHubie (AchajaSetup-<wersja>.exe).

Uzycie:
  update.py check      czy jest nowsza wersja (wypisuje JSON)
  update.py download   pobiera instalator nowej wersji do %TEMP%/Achaja-updates
  update.py install    pobiera (jesli trzeba) i uruchamia instalator w tle; Achaja uruchomi sie ponownie sama

Instalator dziala bez okien (/SILENT), zachowuje moduly, ustawienia i dane, zamyka dzialajaca
Achaje przed podmiana plikow i na koncu uruchamia ja ponownie (/relaunch=1).
Aktualizacje dzialaja w instalacji z AchajaSetup.exe; w kopii z gita: git pull.
"""
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from common import CREATE_NO_WINDOW, DETACHED_PROCESS, ROOT, __version__, read_json, write_json

REPO = "Banzamel/Achaja-Voice-Assistant"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES = f"https://github.com/{REPO}/releases"
# poza folderem programu: instalator zamyka wszystkie procesy uruchomione z folderu Achai, takze siebie
UPDATES = Path(tempfile.gettempdir()) / "Achaja-updates"
ASSET = re.compile(r"^AchajaSetup-[\w.\-]+\.exe$")


def version_key(text):
    """'v0.10.2' -> (0, 10, 2); przyrostki (-dev, -rc1) sa pomijane."""
    m = re.match(r"v?(\d+(?:\.\d+)*)", str(text or "").strip())
    return tuple(int(x) for x in m.group(1).split(".")) if m else (0,)


def installed():
    """Instalacja z AchajaSetup.exe (ma deinstalator Inno Setup) - tylko taka aktualizuje sie sama."""
    return any(ROOT.glob("unins*.exe"))


def check(timeout=15):
    """Najnowsze wydanie, jesli jest nowsze od tej wersji: {version, url, size, digest, page, notes}; inaczej None."""
    req = urllib.request.Request(API, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": f"Achaja/{__version__}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)
    if data.get("draft") or data.get("prerelease"):
        return None
    version = str(data.get("tag_name", "")).lstrip("v")
    if version_key(version) <= version_key(__version__):
        return None
    asset = next((a for a in data.get("assets", []) if ASSET.match(a.get("name", ""))), None)
    return {
        "version": version,
        "url": asset and asset.get("browser_download_url"),
        "name": asset and asset.get("name"),
        "size": asset and asset.get("size"),
        "digest": asset and asset.get("digest"),  # "sha256:..." (GitHub podaje dla nowych plikow)
        "page": data.get("html_url") or RELEASES,
        "notes": (data.get("body") or "")[:2000],
    }


def downloaded(info):
    """Sciezka pobranego i sprawdzonego instalatora tej wersji albo None."""
    meta = read_json(UPDATES / "ready.json", {})
    path = UPDATES / (info.get("name") or "")
    if meta.get("version") == info.get("version") and path.is_file() and path.stat().st_size == info.get("size"):
        return path
    return None


def download(info, progress=None):
    """Pobiera instalator do UPDATES i sprawdza rozmiar oraz sume SHA-256. Zwraca sciezke."""
    if not info.get("url"):
        raise RuntimeError("Wydanie nie ma pliku AchajaSetup-*.exe.")
    ready = downloaded(info)
    if ready:
        return ready
    UPDATES.mkdir(exist_ok=True)
    for old in UPDATES.glob("AchajaSetup-*"):
        old.unlink(missing_ok=True)
    path = UPDATES / info["name"]
    part = path.with_suffix(".part")
    sha = hashlib.sha256()
    req = urllib.request.Request(info["url"], headers={"User-Agent": f"Achaja/{__version__}"})
    done = 0
    with urllib.request.urlopen(req, timeout=60) as resp, open(part, "wb") as f:
        while True:
            chunk = resp.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)
            sha.update(chunk)
            done += len(chunk)
            if progress and info.get("size"):
                progress(done / info["size"])
    if info.get("size") and done != info["size"]:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"Pobrano {done} z {info['size']} bajtow.")
    digest = info.get("digest") or ""
    if digest.startswith("sha256:") and digest[7:].lower() != sha.hexdigest():
        part.unlink(missing_ok=True)
        raise RuntimeError("Suma kontrolna instalatora sie nie zgadza.")
    part.replace(path)
    write_json(UPDATES / "ready.json", {"version": info["version"], "name": info["name"]})
    return path


def run_installer(path, relaunch=True):
    """Uruchamia instalator i nie czeka. Instalator sam zamyka dzialajaca Achaje przed podmiana plikow.
    relaunch: maly pasek postepu i ponowny start Achai; bez tego instalacja calkiem niewidoczna (przy zamknieciu)."""
    args = [str(path), "/SILENT" if relaunch else "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/noconfigure=1",
            f"/relaunch={1 if relaunch else 0}"]
    subprocess.Popen(args, cwd=str(UPDATES), creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW, close_fds=True)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    info = check()
    if cmd == "check":
        print(json.dumps({"current": __version__, "available": info, "self_update": installed()},
                         ensure_ascii=False, indent=2))
        return
    if not info:
        print(f"Achaja {__version__} jest aktualna.")
        return
    if not installed():
        print(f"Nowa wersja {info['version']}: {info['page']} (kopia z gita - zaktualizuj przez git pull).")
        return
    path = download(info)
    print(f"Pobrano wersje {info['version']}: {path}")
    if cmd == "install":
        run_installer(path)
        print("Instalator dziala w tle; Achaja zamknie sie i uruchomi ponownie w nowej wersji.")


if __name__ == "__main__":
    main()
