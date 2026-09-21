"""Hooki UserPromptSubmit i Notification (dzialaja tylko w sesji Achai - ACHAJA_SESSION).

UserPromptSubmit: stan "busy" + krotkie potwierdzenie glosem ("Juz sprawdzam"),
  zeby bylo wiadomo, ze prompt dotarl i Achaja pracuje.
Notification: gdy Claude czeka na zgode przy komputerze - mowi o tym na glos
  i ustawia stan "waiting" (listener nie mowi wtedy "nadal pracuje").
"""
import json
import os
import random
import subprocess
import sys
import time

from common import CREATE_NO_WINDOW, DETACHED_PROCESS, PYTHONW, SCRIPTS, STATE, load_config, write_json

# bez slowa "Achaja" - glosnik + mikrofon biurkowy moglyby wybudzic nasluch
MESSAGES = {
    "permission_prompt": "Czekam na Twoją zgodę przy komputerze.",
    "elicitation_dialog": "Zadałam pytanie z wyborem, odpowiedz przy komputerze.",
}


def say(text):
    subprocess.Popen([str(PYTHONW), str(SCRIPTS / "speak.py"), text], cwd=str(SCRIPTS),
                     creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW, close_fds=True)


def main():
    data = json.loads(sys.stdin.buffer.read().decode("utf-8-sig") or "{}")
    if not os.environ.get("ACHAJA_SESSION"):
        return
    event = data.get("hook_event_name")
    if event == "UserPromptSubmit":
        write_json(STATE / "achaja_state.json", {"state": "busy", "since": time.time()})
        phrases = load_config()["voice"].get("ack_phrases") or []
        if phrases:
            say(random.choice(phrases))
    elif event == "Notification":
        text = MESSAGES.get(data.get("notification_type"))
        if text:
            write_json(STATE / "achaja_state.json", {"state": "waiting", "since": time.time()})
            say(text)


if __name__ == "__main__":
    main()
