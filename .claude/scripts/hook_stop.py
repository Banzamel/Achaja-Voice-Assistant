"""Hook Stop: wyciaga sekcje [GŁOS] z odpowiedzi Achai i czyta ja na glos.

Jesli sekcji brak, czyta pierwsze zdania odpowiedzi (awaryjnie).
Mowa startuje w osobnym procesie, zeby hook nie blokowal sesji.
"""
import json
import os
import re
import subprocess
import sys
import time

from common import (CREATE_NO_WINDOW, DETACHED_PROCESS, PYTHONW, SCRIPTS, STATE,
                    write_json)

MARKER = re.compile(r"^\s*\[(?:G[ŁL]OS|VOICE)\]\s*:?\s*", re.IGNORECASE | re.MULTILINE)


def voice_text(message):
    matches = list(MARKER.finditer(message or ""))
    if matches:
        return message[matches[-1].end():].strip()
    sentences = re.split(r"(?<=[.!?])\s+", (message or "").strip())
    return " ".join(sentences[:2])


def main():
    data = json.loads(sys.stdin.buffer.read().decode("utf-8-sig") or "{}")
    if os.environ.get("ACHAJA_SESSION"):
        write_json(STATE / "achaja_state.json", {"state": "idle", "since": time.time()})
    text = voice_text(data.get("last_assistant_message", ""))
    if text:
        (STATE / "last_voice.txt").write_text(text, encoding="utf-8")
        if "?" in text and os.environ.get("ACHAJA_SESSION"):
            # tryb rozmowy: listener wlaczy nagrywanie, gdy Achaja skonczy mowic
            write_json(STATE / "followup.json", {"at": time.time()})
        subprocess.Popen(
            [str(PYTHONW), str(SCRIPTS / "speak.py"), text],
            cwd=str(SCRIPTS), creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW, close_fds=True,
        )


if __name__ == "__main__":
    main()
