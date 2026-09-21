"""Nasluch Achai: slowo-klucz -> dyktowanie w Claude (tryb voice tap) -> slowo koncowe -> wyslanie.

Vosk rozpoznaje TYLKO slowa kluczowe (maly model, offline). Sam prompt
rozpoznaje wbudowane dyktowanie Claude Code. Klawisze sa wstrzykiwane
bezposrednio do konsoli Claude, wiec okno nie musi miec fokusu.

Uzycie:
  listener.py                 uruchamia nowa sesje Achai w nowym oknie i slucha
  listener.py --continue      jw., ale wznawia ostatnia rozmowe Achai
  listener.py --pid 1234      podpina sie pod juz dzialajace okno claude (PID claude.exe)
  listener.py --devices       wypisuje mikrofony
"""
import argparse
import difflib
import json
import os
import queue
import random
import shutil
import subprocess
import sys
import time
import winsound

from audio_out import request_stop
from common import (CREATE_NEW_CONSOLE, CREATE_NO_WINDOW, DETACHED_PROCESS, PYTHON, PYTHONW, ROOT,
                    SCRIPTS, STATE, clean_env, load_config, model_dir, pick_device, pid_alive, process_name, read_json,
                    single_instance, write_json)

IDLE, RECORDING = "czekam na 'Achaja'", "NAGRYWAM ('wykonaj' / 'anuluj' / 'nowa rozmowa')"


def log(msg):
    print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)


def inject(pid, *keys):
    result = subprocess.run([str(PYTHON), str(SCRIPTS / "inject.py"), str(pid), *keys],
                            creationflags=CREATE_NO_WINDOW, capture_output=True, text=True)
    if result.returncode != 0:
        log(f"BLAD wstrzykiwania klawiszy: {result.stderr.strip()[-300:]}")
    return result.returncode == 0


def say(text):
    subprocess.Popen([str(PYTHONW), str(SCRIPTS / "speak.py"), text], cwd=str(SCRIPTS),
                     creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW, close_fds=True)


def stop_speech():
    request_stop()  # speak.py sam zatrzymuje odtwarzanie (takze na glosniku Google Home)


def speaking():
    try:
        return pid_alive(int((STATE / "tts.pid").read_text()))
    except (OSError, ValueError):
        return False


def followup_ready(now):
    """Achaja zadala pytanie (hook Stop) i wlasnie skonczyla je czytac."""
    path = STATE / "followup.json"
    asked = read_json(path, None)
    if not asked:
        return False
    if now - asked["at"] > 300:
        path.unlink(missing_ok=True)
        return False
    done = read_json(STATE / "speech_done.json", {}).get("at", 0)
    if done > asked["at"] and not speaking():
        path.unlink(missing_ok=True)
        return True
    return False


def beep(cfg, freq, ms):
    if cfg["wake"].get("beep", True):
        winsound.Beep(freq, ms)


def launch_achaja(resume):
    claude = shutil.which("claude")
    if not claude:
        sys.exit("Nie znaleziono 'claude' w PATH.")
    cfg = load_config()
    args = [claude, "--permission-mode", cfg["agents"].get("permission_mode", "auto"), "-n", "Achaja"]
    if cfg.get("achaja", {}).get("model"):
        args += ["--model", cfg["achaja"]["model"]]
    if cfg.get("achaja", {}).get("effort"):
        args += ["--effort", cfg["achaja"]["effort"]]
    if resume:
        args.append("--continue")
    env = clean_env()
    env["ACHAJA_SESSION"] = "1"  # hooki rozpoznaja po tym sesje Achai (tryb rozmowy tylko dla niej)
    token_file = STATE / "ha_token.txt"
    if token_file.exists():  # token Home Assistant dla .mcp.json (${HA_TOKEN}) - tylko w sesji Achai
        env["HA_TOKEN"] = token_file.read_text(encoding="utf-8").strip()
    proc = subprocess.Popen(args, cwd=str(ROOT), creationflags=CREATE_NEW_CONSOLE, env=env)
    log(f"Uruchomiono Achaje w nowym oknie (PID {proc.pid}).")
    return proc.pid


def contains(text, phrases):
    padded = f" {text} "
    return any(f" {p} " in padded for p in phrases)



def assign_claude_microphone(pid, mic):
    """Przypisuje mikrofon do claude.exe (Windows wymaga aktywnego nagrywania, wiec robimy to
    chwile po starcie pierwszego nagrania). Windows pamieta wybor na stale dla sciezki exe."""
    import threading
    flag = STATE / "claude_mic.json"
    if not mic or read_json(flag, {}).get("mic") == mic:
        return

    def work():
        time.sleep(1.5)
        result = subprocess.run([str(PYTHON), str(ROOT / "setup" / "set_app_audio.py"), str(pid), "input", mic],
                                creationflags=CREATE_NO_WINDOW, capture_output=True, text=True)
        if result.returncode == 0:
            write_json(flag, {"mic": mic})
            log(f"Przypisano mikrofon '{mic}' do claude.exe (na stale).")
        else:
            log(f"Nie udalo sie przypisac mikrofonu do claude.exe: {result.stderr.strip()[-200:]}")

    threading.Thread(target=work, daemon=True).start()


def pick_microphone(sd, wanted):
    device = pick_device(sd, wanted, "input")
    if wanted and device is None:
        log(f"Nie znaleziono mikrofonu '{wanted}' - uzywam domyslnego.")
    return device


def is_end_word(word, words, threshold):
    """Maly model przekreca "wykonaj" (wykonanie, wykonane, wygodniej) - dopasowanie rozmyte."""
    for w in words:
        ratio = difflib.SequenceMatcher(None, word, w).ratio()
        if ratio >= threshold or (word[:2] == w[:2] and ratio >= threshold - 0.1):
            return True
    return False


def ends_with(text, words, threshold):
    parts = text.split()
    return bool(parts) and is_end_word(parts[-1], words, threshold)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int)
    ap.add_argument("--continue", dest="resume", action="store_true")
    ap.add_argument("--devices", action="store_true")
    ap.add_argument("--device", help="nazwa lub numer mikrofonu (domyslnie systemowy)")
    args = ap.parse_args()

    import sounddevice as sd
    import vosk

    if args.devices:
        print(sd.query_devices())
        return

    if not single_instance("AchajaListener"):
        print("Achaja juz dziala (nasluch jest uruchomiony) - nie uruchamiam drugiej kopii.")
        return

    cfg = load_config()
    wake, end, cancel = cfg["wake"]["phrases"], cfg["wake"]["end"], cfg["wake"]["cancel"]
    clear = cfg["wake"].get("clear", [])

    vosk.SetLogLevel(-1)
    model = vosk.Model(str(model_dir()))
    # wybudzenie: gramatyka ograniczona (model nie zna slowa "achaja"), szybkie wyniki czastkowe
    wake_rec = vosk.KaldiRecognizer(model, 16000, json.dumps(wake + ["[unk]"], ensure_ascii=False))
    # w trakcie nagrywania: pelny slownik i tylko zakonczone wypowiedzi - mniej falszywych trafien
    free_rec = vosk.KaldiRecognizer(model, 16000)

    (STATE / "followup.json").unlink(missing_ok=True)
    pid = args.pid
    previous = read_json(STATE / "listener.json", {}).get("claude_pid")
    if not pid and previous and process_name(previous) == "claude.exe":
        pid = previous
        log(f"Okno Achai juz jest otwarte (PID {pid}) - podpinam sie do niego.")
    if not pid:
        pid = launch_achaja(args.resume)
    write_json(STATE / "listener.json", {"listener_pid": os.getpid(), "claude_pid": pid})

    audio = queue.Queue()
    device = pick_microphone(sd, args.device or cfg["wake"].get("microphone"))

    def on_audio(data, frames, t, status):
        audio.put(bytes(data))

    state, started, last_speech = IDLE, 0.0, 0.0
    max_rec = cfg["wake"].get("max_recording_seconds", 110)
    silence_stop = cfg["wake"].get("silence_stop_seconds", 17)
    followup = cfg["wake"].get("auto_listen_after_question", True)
    end_match = cfg["wake"].get("end_match", 0.7)
    end_stable = cfg["wake"].get("end_stable_seconds", 0.6)
    partial_text, partial_since = "", 0.0
    remind_after = cfg["voice"].get("working_reminder_after_seconds", 30)
    remind_every = cfg["voice"].get("working_reminder_every_seconds", 60)
    remind_max = cfg["voice"].get("working_reminder_max_seconds", 900)
    last_reminder = 0.0

    def start_recording(reason):
        nonlocal state, started, last_speech, partial_text
        free_rec.Reset()
        beep(cfg, 880, 120)
        # ctrl+u czysci pole (tap startuje nagrywanie tylko przy pustym polu)
        partial_text = ""
        if inject(pid, "ctrl+u", "space"):
            state, started, last_speech = RECORDING, time.time(), time.time()
            log(f"{reason} Stan: {state}")
            assign_claude_microphone(pid, cfg["wake"].get("microphone"))

    def to_idle(msg):
        nonlocal state
        wake_rec.Reset()
        state = IDLE
        log(f"{msg} Stan: {state}")

    with sd.RawInputStream(samplerate=16000, blocksize=4000, dtype="int16", channels=1,
                           device=device, callback=on_audio):
        log(f"Mikrofon: {sd.query_devices(device, 'input')['name']}")
        log(f"Stan: {state}")
        while True:
            try:
                chunk = audio.get(timeout=1)
            except queue.Empty:
                chunk = None
            if not pid_alive(pid):
                log("Okno Achai zostalo zamkniete - koncze nasluch.")
                return
            now = time.time()
            if state == RECORDING and (now - started > max_rec
                                       or now - max(started, last_speech) > silence_stop):
                to_idle("Cisza lub limit czasu - Claude sam zakonczyl nagrywanie.")
            if state == IDLE and followup and followup_ready(now):
                start_recording("Achaja zadala pytanie - slucham odpowiedzi.")
            if state == IDLE and remind_after:
                work = read_json(STATE / "achaja_state.json", {})
                busy_for = now - work.get("since", now)
                if (work.get("state") == "busy" and remind_after <= busy_for < remind_max
                        and (last_reminder < work["since"] or now - last_reminder >= remind_every)
                        and not speaking()):
                    last_reminder = now
                    say(random.choice(cfg["voice"].get("working_phrases") or ["Nadal pracuję."]))
                    log(f"Achaja pracuje od {int(busy_for)} s - przypomnienie glosowe.")
            if chunk is None:
                continue

            if state == IDLE:
                if wake_rec.AcceptWaveform(chunk):
                    text = json.loads(wake_rec.Result()).get("text", "")
                    if text and cfg["wake"].get("debug", True):
                        # "[unk]" = slyszy mowe, ale nie rozpoznal frazy wybudzenia
                        log(f"  czuwanie: {text}")
                else:
                    text = json.loads(wake_rec.PartialResult()).get("partial", "")
                if contains(text, wake):
                    stop_speech()
                    (STATE / "followup.json").unlink(missing_ok=True)
                    start_recording("Uslyszalem Achaje.")
                continue

            # RECORDING
            if not free_rec.AcceptWaveform(chunk):
                partial = json.loads(free_rec.PartialResult()).get("partial", "").strip()
                if partial != partial_text:
                    partial_text, partial_since = partial, now
                if partial:
                    last_speech = now
                # szybka sciezka: slowo koncowe na koncu i nic nowego przez end_stable sekund
                if not (partial and now - partial_since >= end_stable and ends_with(partial, end, end_match)):
                    continue
                text = partial
                free_rec.Reset()
            else:
                text = json.loads(free_rec.Result()).get("text", "").strip()
            partial_text = ""
            if not text:
                continue
            last_speech = time.time()
            log(f"  slysze: {text}")
            if ends_with(text, end, end_match):
                inject(pid, "space")
                beep(cfg, 1175, 120)
                to_idle("Wyslano prompt.")
            elif text in cancel:
                inject(pid, "esc")
                time.sleep(0.4)
                inject(pid, "ctrl+u")
                beep(cfg, 440, 300)
                to_idle("Anulowano.")
            elif text in clear:
                inject(pid, "esc")
                time.sleep(0.4)
                inject(pid, "ctrl+u", "text:/clear", "enter")
                beep(cfg, 660, 120)
                beep(cfg, 880, 120)
                to_idle("Nowa rozmowa (/clear).")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass