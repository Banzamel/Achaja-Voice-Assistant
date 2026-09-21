"""Czyta tekst na glos (edge-tts, polski glos neuronowy).

Uzycie: speak.py "tekst"   albo   speak.py --file plik.txt
Wyjscie (sluchawki / glosnik Google Home) wybiera output.py - patrz audio_out.py.
Kolejne wypowiedzi czekaja na zakonczenie poprzedniej (nie przerywaja sie).
Listener przerywa mowe flaga state/tts_stop.json (dziala tez dla glosnika).
"""
import asyncio
import hashlib
import os
import re
import shutil
import sys
import time

from audio_out import consume_once, play, stopped
from common import STATE, load_config, pid_alive, write_json

PID_FILE = STATE / "tts.pid"
CACHE = STATE / "tts_cache"


def clean(text, limit):
    text = re.sub(r"[`*_#>|]", "", text)
    text = re.sub(r"https?://\S+", "link", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def wait_turn():
    deadline = time.time() + 120
    while time.time() < deadline:
        try:
            other = int(PID_FILE.read_text())
        except (OSError, ValueError):
            break
        if other == os.getpid() or not pid_alive(other):
            break
        time.sleep(0.3)
    PID_FILE.write_text(str(os.getpid()))


async def synth(text, voice, rate, out):
    import edge_tts
    await edge_tts.Communicate(text, voice, rate=rate).save(str(out))


def synth_cached(text, voice, rate, out):
    """Krotkie, powtarzalne frazy ("Juz sprawdzam") z pamieci podrecznej - brzmia od razu."""
    if len(text) > 80:
        asyncio.run(synth(text, voice, rate, out))
        return
    key = hashlib.sha1(f"{voice}|{rate}|{text}".encode("utf-8")).hexdigest()[:16]
    cached = CACHE / f"{key}.mp3"
    if not cached.exists():
        CACHE.mkdir(exist_ok=True)
        asyncio.run(synth(text, voice, rate, cached))
    shutil.copyfile(cached, out)


def main():
    since = time.time()
    if len(sys.argv) >= 3 and sys.argv[1] == "--file":
        with open(sys.argv[2], encoding="utf-8") as f:
            text = f.read()
    else:
        text = " ".join(sys.argv[1:])
    cfg = load_config()["voice"]
    text = clean(text, cfg.get("max_chars", 4000))
    if not text:
        return
    out = STATE / f"tts-{os.getpid()}.mp3"
    try:
        synth_cached(text, cfg["tts_voice"], cfg.get("rate", "+0%"), out)
        wait_turn()
        if not stopped(since):
            play(out, since)
            consume_once()
        write_json(STATE / "speech_done.json", {"at": time.time()})
    finally:
        try:
            out.unlink()
        except OSError:
            pass
        try:
            if PID_FILE.read_text() == str(os.getpid()):
                PID_FILE.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    main()
