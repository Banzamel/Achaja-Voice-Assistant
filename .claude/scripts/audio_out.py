"""Wyjscia glosu Achai: lokalne urzadzenie (sluchawki) albo glosnik Google Cast (Google Home).

Przerywanie: listener zapisuje state/tts_stop.json {"at": czas}; odtwarzanie sprawdza,
czy flaga jest nowsza niz start tej wypowiedzi, i zatrzymuje sie (takze na glosniku Cast).
"""
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from common import STATE, load_config, pick_device, read_json, write_json

STOP_FILE = STATE / "tts_stop.json"
OUTPUT_FILE = STATE / "voice_output.json"


def request_stop():
    write_json(STOP_FILE, {"at": time.time()})


def stopped(since):
    return read_json(STOP_FILE, {}).get("at", 0) > since


def outputs(cfg=None):
    voice = (cfg or load_config())["voice"]
    outs = voice.get("outputs") or {"słuchawki": {"type": "local", "device": voice.get("output_device", "")}}
    return outs, voice.get("default_output", next(iter(outs)))


def current_output():
    """Nazwa wybranego wyjscia (state/voice_output.json albo domyslne z config.json)."""
    outs, default = outputs()
    chosen = read_json(OUTPUT_FILE, {}).get("output", default)
    return chosen if chosen in outs else default


def consume_once():
    """Po wypowiedzi jednorazowej (--once) wraca do domyslnego wyjscia."""
    state = read_json(OUTPUT_FILE, {})
    if state.get("once"):
        OUTPUT_FILE.unlink(missing_ok=True)


def play_local(path, device, since):
    import sounddevice as sd
    import soundfile as sf
    data, rate = sf.read(str(path), dtype="float32")
    sd.play(data, rate, device=pick_device(sd, device, "output"))
    end = time.time() + len(data) / rate + 1
    while time.time() < end and sd.get_stream().active:
        if stopped(since):
            sd.stop()
            return
        time.sleep(0.1)
    sd.wait()


def _local_ip(target):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect((target, 8009))
        return s.getsockname()[0]


def play_cast(path, out, since):
    import pychromecast
    import soundfile as sf

    data = path.read_bytes()
    duration = sf.info(str(path)).duration

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    ip = _local_ip(out["host"])
    server = ThreadingHTTPServer((ip, 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    casts, browser = pychromecast.get_listed_chromecasts(
        friendly_names=[out["name"]], known_hosts=[out["host"]], discovery_timeout=5)
    try:
        if not casts:
            raise RuntimeError(f"Nie znaleziono glosnika {out['name']} ({out['host']})")
        cast = casts[0]
        cast.wait(timeout=10)
        mc = cast.media_controller
        mc.play_media(f"http://{ip}:{server.server_address[1]}/achaja.mp3", "audio/mpeg")
        mc.block_until_active(timeout=10)
        started, deadline = False, time.time() + duration + 20
        while time.time() < deadline:
            if stopped(since):
                mc.stop()
                break
            player = mc.status.player_state if mc.status else None
            if player in ("PLAYING", "BUFFERING"):
                started = True
            elif started and player == "IDLE":
                break
            time.sleep(0.2)
        cast.disconnect(timeout=3)
    finally:
        browser.stop_discovery()
        server.shutdown()


def play(path, since, name=None):
    outs, default = outputs()
    name = name or current_output()
    out = outs.get(name) or outs[default]
    if out.get("type") == "cast":
        try:
            play_cast(path, out, since)
            return
        except Exception as exc:  # glosnik niedostepny - mow w sluchawkach, zeby nic nie przepadlo
            (STATE / "speak_error.txt").write_text(f"{time.ctime()}: {exc}", encoding="utf-8")
            local = next((o for o in outs.values() if o.get("type") == "local"), {"device": ""})
            play_local(path, local.get("device"), since)
            return
    play_local(path, out.get("device"), since)
