"""Achaja jako zwykly program okienkowy: jedno okno z rozmowa, agentami i dziennikiem.

Uruchamiaj przez pythonw (bez okna konsoli):
  .venv\\Scripts\\pythonw.exe .claude\\scripts\\app.py              nowa rozmowa
  .venv\\Scripts\\pythonw.exe .claude\\scripts\\app.py --continue   wznawia ostatnia rozmowe
  ... app.py --minimized                                         start w zasobniku (autostart)

Nasluch (listener.run) dziala w watku tej aplikacji, a sesja Claude Code w ukrytej konsoli -
nie widac zadnych okien terminala. Konsole mozna pokazac z menu (np. przy pytaniu o zgode
pokazuje sie sama). Rozmowe wypelniaja hooki sesji (state/chat.jsonl), agentow - state/agents/.
"""
import argparse
import ctypes
import json
import os
import queue
import re
import subprocess
import threading
import time

import listener
from common import (AGENTS_STATE, CHAT_LOG, CREATE_NO_WINDOW, DETACHED_PROCESS, PYTHON, PYTHONW, ROOT, SCRIPTS,
                    STATE, load_config, pid_alive, read_json, single_instance, write_json)

MARKER = re.compile(r"^\s*\[(?:G[ŁL]OS|VOICE)\]\s*:?\s*", re.IGNORECASE | re.MULTILINE)
SHOW_FLAG = STATE / "app_show.json"  # druga kopia programu prosi pierwsza o pokazanie okna
WINDOW_FILE = STATE / "app_window.json"
ICON = ROOT / "setup" / "assets" / "achaja.ico"
ACCENT = "#6c4cd4"

TEXT = {
    "pl": {
        "chat": "Rozmowa", "agents": "Agenci", "log": "Dziennik", "send": "Wyślij", "talk": "Mów",
        "send_rec": "Wyślij nagranie", "cancel": "Anuluj", "pause": "Wstrzymaj nasłuch", "resume": "Wznów nasłuch",
        "menu": "Achaja", "new": "Nowa rozmowa", "repeat": "Powtórz ostatnią odpowiedź",
        "console": "Pokaż / ukryj konsolę Claude", "settings": "Ustawienia…", "restart": "Uruchom nasłuch ponownie",
        "quit": "Zakończ", "show": "Pokaż okno", "you": "Ty", "achaja": "Achaja",
        "st_idle": "Czuwam — powiedz słowo wybudzenia", "st_rec": "Nagrywam… zakończ słowem końcowym",
        "st_busy": "Pracuję…", "st_wait": "Czekam na Twoją zgodę w konsoli Claude", "st_speak": "Mówię…",
        "st_paused": "Nasłuch wstrzymany", "st_start": "Uruchamiam…", "st_closed": "Sesja Claude została zamknięta",
        "st_error": "Błąd nasłuchu — zobacz Dziennik",
        "placeholder": "Napisz do Achai (Enter wysyła, Shift+Enter nowa linia)",
        "wait_note": "Claude pyta o zgodę — otworzyłam konsolę, odpowiedz tam.",
        "stop_agent": "Przerwij agenta", "working": "pracuje {} min", "no_agents": "Brak agentów.",
        "quit_ask": "Zakończyć Achaję? Nasłuch i ukryta sesja Claude zostaną zamknięte.",
        "already": "Achaja już działa w oknie konsoli (start-achaja.cmd).",
    },
    "en": {
        "chat": "Conversation", "agents": "Agents", "log": "Log", "send": "Send", "talk": "Talk",
        "send_rec": "Send recording", "cancel": "Cancel", "pause": "Pause listening", "resume": "Resume listening",
        "menu": "Achaja", "new": "New conversation", "repeat": "Repeat the last answer",
        "console": "Show / hide the Claude console", "settings": "Settings…", "restart": "Restart the listener",
        "quit": "Quit", "show": "Show window", "you": "You", "achaja": "Achaja",
        "st_idle": "Listening for the wake word", "st_rec": "Recording… finish with the end word",
        "st_busy": "Working…", "st_wait": "Waiting for your approval in the Claude console", "st_speak": "Speaking…",
        "st_paused": "Listening paused", "st_start": "Starting…", "st_closed": "The Claude session was closed",
        "st_error": "Listener error — see the Log",
        "placeholder": "Write to Achaja (Enter sends, Shift+Enter adds a line)",
        "wait_note": "Claude is asking for approval — I opened the console, answer there.",
        "stop_agent": "Stop agent", "working": "working {} min", "no_agents": "No agents.",
        "quit_ask": "Quit Achaja? The listener and the hidden Claude session will be closed.",
        "already": "Achaja is already running in a console window (start-achaja.cmd).",
    },
}
COLORS = {"idle": "#2e9b57", "rec": "#d93a3a", "busy": "#d98c1a", "wait": "#d98c1a", "speak": ACCENT,
          "paused": "#888888", "start": "#888888", "closed": "#888888", "error": "#d93a3a"}


class Bridge:
    """Stan dzielony z watkiem nasluchu (listener.run)."""

    def __init__(self, hidden):
        self.stop = threading.Event()
        self.requests = queue.Queue()
        self.paused = False
        self.hidden = hidden
        self.state = "start"
        self.pid = None

    def on_state(self, state, pid):
        self.state, self.pid = state, pid


def split_voice(text):
    """Odpowiedz Achai -> (tresc, sekcja [GŁOS])."""
    matches = list(MARKER.finditer(text or ""))
    if not matches:
        return text.strip(), ""
    m = matches[-1]
    return text[:m.start()].strip(), text[m.end():].strip()


def trim_chat(keep=400):
    try:
        lines = CHAT_LOG.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    if len(lines) > keep * 2:
        CHAT_LOG.write_text("\n".join(lines[-keep:]) + "\n", encoding="utf-8")


class App:
    def __init__(self, args):
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.ttk = tk, ttk
        self.args = args
        self.cfg = load_config()
        self.opts = self.cfg.get("app", {})
        lang = self.cfg.get("language", "pl")
        self.t = TEXT[lang if lang in TEXT else "en"]
        self.bridge = None
        self.thread = None
        self.logs = queue.Queue()
        self.calls = queue.Queue()  # wywolania z watku ikony w zasobniku
        self.chat_pos = 0
        self.auto_shown = False
        self.hidden_once = None
        self.tray = None
        self.quitting = False
        self.ticks = 0
        self.last_start = 0.0
        listener.LOG_SINKS.append(self.logs.put)

        self.root = root = tk.Tk()
        root.title("Achaja")
        geo = read_json(WINDOW_FILE, {}).get("geometry")
        root.geometry(geo or "760x620")
        root.minsize(520, 420)
        if ICON.exists():
            root.iconbitmap(default=str(ICON))
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Status.TLabel", font=("Segoe UI", 11))
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.build_menu()
        self.build_header()
        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.build_chat(nb)
        self.build_agents(nb)
        self.build_log(nb)

        self.start_tray()
        if args.minimized:
            root.after(0, self.hide_window)
        self.start_listener(args.resume)
        root.after(200, self.poll)

    # --- budowa okna ---
    def build_menu(self):
        tk, t = self.tk, self.t
        bar = tk.Menu(self.root)
        m = tk.Menu(bar, tearoff=False)
        m.add_command(label=t["new"], command=lambda: self.request("clear"))
        m.add_command(label=t["repeat"], command=self.repeat)
        m.add_separator()
        m.add_command(label=t["console"], command=self.toggle_console)
        m.add_command(label=t["restart"], command=self.restart_listener)
        m.add_command(label=t["settings"], command=self.open_settings)
        m.add_separator()
        m.add_command(label=t["quit"], command=self.quit)
        bar.add_cascade(label=t["menu"], menu=m)
        self.root.config(menu=bar)

    def build_header(self):
        ttk, t = self.ttk, self.t
        head = ttk.Frame(self.root, padding=(12, 10))
        head.pack(fill="x")
        self.dot = self.tk.Canvas(head, width=14, height=14, highlightthickness=0)
        self.dot_id = self.dot.create_oval(2, 2, 13, 13, fill=COLORS["start"], outline="")
        self.dot.pack(side="left", padx=(0, 8))
        self.status = ttk.Label(head, text=t["st_start"], style="Status.TLabel")
        self.status.pack(side="left")
        self.pause_btn = ttk.Button(head, text=t["pause"], command=self.toggle_pause)
        self.pause_btn.pack(side="right")
        self.cancel_btn = ttk.Button(head, text=t["cancel"], command=lambda: self.request("cancel"))
        self.talk_btn = ttk.Button(head, text=t["talk"], command=self.talk)
        self.talk_btn.pack(side="right", padx=(0, 6))

    def build_chat(self, nb):
        tk, ttk, t = self.tk, self.ttk, self.t
        frame = ttk.Frame(nb, padding=6)
        nb.add(frame, text=t["chat"])
        box = ttk.Frame(frame)
        box.pack(fill="both", expand=True)
        self.chat = tk.Text(box, wrap="word", state="disabled", relief="flat", padx=10, pady=8,
                            font=("Segoe UI", 10), background="#fbfaff")
        sb = ttk.Scrollbar(box, command=self.chat.yview)
        self.chat.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.chat.pack(side="left", fill="both", expand=True)
        self.chat.tag_configure("who_user", foreground="#1f6feb", font=("Segoe UI", 9, "bold"), spacing1=10)
        self.chat.tag_configure("who_ai", foreground=ACCENT, font=("Segoe UI", 9, "bold"), spacing1=10)
        self.chat.tag_configure("time", foreground="#999", font=("Segoe UI", 8))
        self.chat.tag_configure("body", lmargin1=4, lmargin2=4, spacing3=2)
        self.chat.tag_configure("voice", foreground="#555", font=("Segoe UI", 10, "italic"), lmargin1=4, lmargin2=4)
        self.chat.tag_configure("note", foreground="#b06000", font=("Segoe UI", 9, "italic"), spacing1=8)

        bottom = ttk.Frame(frame)
        bottom.pack(fill="x", pady=(6, 0))
        self.entry = tk.Text(bottom, height=3, wrap="word", font=("Segoe UI", 10), relief="solid", borderwidth=1)
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Return>", self.on_enter)
        self.entry.bind("<FocusIn>", lambda e: self.placeholder(False))
        self.entry.bind("<FocusOut>", lambda e: self.placeholder(True))
        self.entry.tag_configure("ph", foreground="#999")
        self.placeholder(True)
        ttk.Button(bottom, text=t["send"], command=self.send_text).pack(side="left", padx=(6, 0), fill="y")

        trim_chat()
        try:
            lines = CHAT_LOG.read_text(encoding="utf-8").splitlines()
            self.chat_pos = CHAT_LOG.stat().st_size
        except OSError:
            lines = []
        for line in lines[-60:]:
            self.add_chat_line(line)

    def build_agents(self, nb):
        tk, ttk, t = self.tk, self.ttk, self.t
        frame = ttk.Frame(nb, padding=6)
        nb.add(frame, text=t["agents"])
        left = ttk.Frame(frame)
        left.pack(side="left", fill="y")
        self.agent_list = tk.Listbox(left, width=28, activestyle="none", exportselection=False,
                                     relief="solid", borderwidth=1, font=("Segoe UI", 10))
        self.agent_list.pack(fill="y", expand=True)
        self.agent_list.bind("<<ListboxSelect>>", lambda e: self.show_agent(force=True))
        ttk.Button(left, text=t["stop_agent"], command=self.stop_agent).pack(fill="x", pady=(6, 0))
        self.agent_text = tk.Text(frame, wrap="word", state="disabled", relief="flat", padx=8, pady=6,
                                  font=("Consolas", 9))
        sb = ttk.Scrollbar(frame, command=self.agent_text.yview)
        self.agent_text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.agent_text.pack(side="left", fill="both", expand=True, padx=(6, 0))
        self.agent_names, self.agent_shown = [], (None, 0)

    def build_log(self, nb):
        tk, ttk = self.tk, self.ttk
        frame = ttk.Frame(nb, padding=6)
        nb.add(frame, text=self.t["log"])
        self.log_text = tk.Text(frame, wrap="word", state="disabled", relief="flat", font=("Consolas", 9))
        sb = ttk.Scrollbar(frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log_text.pack(side="left", fill="both", expand=True)

    # --- rozmowa ---
    def placeholder(self, on):
        has_ph = bool(self.entry.tag_ranges("ph"))
        if on and not self.entry.get("1.0", "end").strip():
            self.entry.insert("1.0", self.t["placeholder"], "ph")
        elif not on and has_ph:
            self.entry.delete("1.0", "end")

    def on_enter(self, event):
        if event.state & 0x1:  # Shift+Enter - nowa linia
            return None
        self.send_text()
        return "break"

    def send_text(self):
        if self.entry.tag_ranges("ph"):
            return
        text = self.entry.get("1.0", "end").strip()
        if not text:
            return
        self.entry.delete("1.0", "end")
        self.request(("type", text))

    def add_chat_line(self, line):
        try:
            item = json.loads(line)
        except ValueError:
            return
        when = time.strftime("%H:%M", time.localtime(item.get("at", time.time())))
        self.chat.configure(state="normal")
        if item.get("role") == "user":
            self.chat.insert("end", f"{self.t['you']}  ", "who_user")
            self.chat.insert("end", when + "\n", "time")
            self.chat.insert("end", item.get("text", "") + "\n", "body")
        else:
            body, voice = split_voice(item.get("text", ""))
            self.chat.insert("end", f"{self.t['achaja']}  ", "who_ai")
            self.chat.insert("end", when + "\n", "time")
            if body:
                self.chat.insert("end", body + "\n", "body")
            if voice:
                self.chat.insert("end", "♪ " + voice + "\n", "voice")
        self.chat.configure(state="disabled")
        self.chat.see("end")

    def add_note(self, text):
        self.chat.configure(state="normal")
        self.chat.insert("end", text + "\n", "note")
        self.chat.configure(state="disabled")
        self.chat.see("end")

    def read_new_chat(self):
        try:
            size = CHAT_LOG.stat().st_size
        except OSError:
            return
        if size < self.chat_pos:  # plik przyciety
            self.chat_pos = 0
        if size == self.chat_pos:
            return
        with open(CHAT_LOG, "rb") as f:
            f.seek(self.chat_pos)
            data = f.read()
        end = data.rfind(b"\n") + 1  # tylko pelne linie
        self.chat_pos += end
        for line in data[:end].decode("utf-8", errors="replace").splitlines():
            self.add_chat_line(line)

    # --- agenci ---
    def refresh_agents(self):
        running = {n: r for n, r in read_json(AGENTS_STATE / "running.json", {}).items() if pid_alive(r["pid"])}
        logs = sorted(AGENTS_STATE.glob("*.log"), key=os.path.getmtime, reverse=True)
        names = list(running) + [p.stem for p in logs if p.stem not in running]
        labels = []
        for n in names:
            if n in running:
                labels.append(f"● {n} — " + self.t["working"].format(round((time.time() - running[n]["started"]) / 60)))
            else:
                labels.append(f"   {n}")
        if labels != list(self.agent_list.get(0, "end")):
            selected = self.selected_agent()
            self.agent_list.delete(0, "end")
            for label in labels:
                self.agent_list.insert("end", label)
            self.agent_names = names
            if selected in names:
                self.agent_list.selection_set(names.index(selected))
            elif names:
                self.agent_list.selection_set(0)
        self.show_agent()

    def selected_agent(self):
        sel = self.agent_list.curselection()
        return self.agent_names[sel[0]] if sel and sel[0] < len(self.agent_names) else None

    def show_agent(self, force=False):
        name = self.selected_agent()
        path = AGENTS_STATE / f"{name}.log" if name else None
        try:
            mtime = path.stat().st_mtime if path else 0
        except OSError:
            mtime = 0
        if not force and (name, mtime) == self.agent_shown:
            return
        self.agent_shown = (name, mtime)
        text = path.read_text(encoding="utf-8", errors="replace") if mtime else self.t["no_agents"]
        at_end = self.agent_text.yview()[1] > 0.98
        self.agent_text.configure(state="normal")
        self.agent_text.delete("1.0", "end")
        self.agent_text.insert("end", text)
        self.agent_text.configure(state="disabled")
        if at_end or force:
            self.agent_text.see("end")

    def stop_agent(self):
        name = self.selected_agent()
        if name:
            threading.Thread(target=subprocess.run, daemon=True, kwargs={
                "args": [str(PYTHON), str(SCRIPTS / "agent.py"), "stop", name],
                "creationflags": CREATE_NO_WINDOW, "capture_output": True}).start()

    # --- nasluch ---
    def start_listener(self, resume):
        paused = self.bridge.paused if self.bridge else False
        self.bridge = Bridge(hidden=self.opts.get("hide_console", True))
        self.bridge.paused = paused
        self.last_start = time.time()
        self.hidden_once = None
        args = listener.parse_args(["--continue"] if resume else [])
        bridge = self.bridge

        def work():
            try:
                if listener.run(args, bridge) == "closed":
                    bridge.state = "closed"
            except BaseException as exc:  # SystemExit z launch_achaja tez
                self.logs.put(f"{time.strftime('%H:%M:%S')} BLAD: {exc!r}")
                bridge.state = "error"

        self.thread = threading.Thread(target=work, daemon=True)
        self.thread.start()

    def restart_listener(self):
        if self.bridge:
            self.bridge.stop.set()
        if self.thread:
            self.thread.join(timeout=3)
        self.start_listener(resume=True)  # podpina sie do tej samej sesji Claude, jesli dziala

    def request(self, req):
        if self.bridge:
            self.bridge.requests.put(req)

    def talk(self):
        self.request("send" if self.bridge and self.bridge.state == "recording" else "record")

    def toggle_pause(self):
        if self.bridge:
            self.bridge.paused = not self.bridge.paused

    def repeat(self):
        path = STATE / "last_voice.txt"
        if path.exists():
            subprocess.Popen([str(PYTHONW), str(SCRIPTS / "speak.py"), "--file", str(path)], cwd=str(SCRIPTS),
                             creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW, close_fds=True)

    def open_settings(self):
        subprocess.Popen([str(PYTHONW), str(ROOT / "setup" / "configure.py")], cwd=str(ROOT),
                         creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW, close_fds=True)

    def claude_pid(self):
        pid = self.bridge.pid if self.bridge else None
        return pid if pid and pid_alive(pid) else None

    def toggle_console(self):
        import console
        pid = self.claude_pid()
        if pid:
            console.set_visible(pid, not console.is_visible(pid))
            self.auto_shown = False

    # --- petla okna ---
    def poll(self):
        try:
            self.tick()
        except Exception as exc:
            self.logs.put(f"{time.strftime('%H:%M:%S')} BLAD okna: {exc!r}")
        self.root.after(300, self.poll)

    def tick(self):
        import console
        while not self.calls.empty():
            self.calls.get_nowait()()
        lines = []
        while not self.logs.empty():
            lines.append(self.logs.get_nowait())
        if lines:
            at_end = self.log_text.yview()[1] > 0.98
            self.log_text.configure(state="normal")
            self.log_text.insert("end", "\n".join(lines) + "\n")
            if int(self.log_text.index("end-1c").split(".")[0]) > 3000:
                self.log_text.delete("1.0", "1000.0")
            self.log_text.configure(state="disabled")
            if at_end:
                self.log_text.see("end")

        if SHOW_FLAG.exists():
            SHOW_FLAG.unlink(missing_ok=True)
            self.show_window()
        self.read_new_chat()
        self.ticks += 1
        if self.ticks % 3 == 1:  # agenci mniej wiecej co sekunde
            self.refresh_agents()

        b = self.bridge
        pid = self.claude_pid()
        # sesja Claude z poprzedniego uruchomienia mogla byc widoczna - chowamy ja raz po podpieciu
        if pid and b.hidden and self.hidden_once != pid:
            self.hidden_once = pid
            console.set_visible(pid, False)
        work = read_json(STATE / "achaja_state.json", {})
        waiting = work.get("state") == "waiting" and work.get("kind") == "permission_prompt"
        if pid and waiting and not self.auto_shown and self.opts.get("show_console_on_prompt", True):
            if not console.is_visible(pid):
                console.set_visible(pid, True)
                self.auto_shown = True
                self.add_note(self.t["wait_note"])
        elif self.auto_shown and not waiting and pid and b.hidden:
            console.set_visible(pid, False)
            self.auto_shown = False

        if b.state in ("closed", "error", "start"):
            key = b.state
        elif b.state == "recording":
            key = "rec"
        elif waiting:
            key = "wait"
        elif listener.speaking():
            key = "speak"
        elif work.get("state") == "busy":
            key = "busy"
        elif b.paused:
            key = "paused"
        else:
            key = "idle"
        self.status.configure(text=self.t["st_" + key])
        self.dot.itemconfigure(self.dot_id, fill=COLORS[key])
        self.pause_btn.configure(text=self.t["resume"] if b.paused else self.t["pause"])
        if key == "rec":
            self.talk_btn.configure(text=self.t["send_rec"])
            if not self.cancel_btn.winfo_ismapped():
                self.cancel_btn.pack(side="right", padx=(0, 6), before=self.talk_btn)
        else:
            self.talk_btn.configure(text=self.t["talk"])
            if self.cancel_btn.winfo_ismapped():
                self.cancel_btn.pack_forget()
        # zamknieta / zabita sesja Claude wraca sama (z ta sama rozmowa), ale nie czesciej niz co 30 s
        if (key == "closed" and self.opts.get("restart_closed_session", True) and not self.quitting
                and time.time() - self.last_start > 30):
            self.add_note(self.t["st_closed"])
            self.start_listener(resume=True)

    # --- okno, zasobnik, koniec ---
    def start_tray(self):
        if not self.opts.get("tray", True):
            return
        try:
            import pystray
            from PIL import Image
        except ImportError:
            return  # bez pystray okno po prostu minimalizuje sie na pasek zadan
        t = self.t
        image = Image.open(str(ICON)) if ICON.exists() else Image.new("RGB", (64, 64), ACCENT)

        def call(fn):
            return lambda icon, item: self.calls.put(fn)

        menu = pystray.Menu(
            pystray.MenuItem(t["show"], call(self.show_window), default=True),
            pystray.MenuItem(t["talk"], call(self.talk)),
            pystray.MenuItem(lambda item: t["resume"] if self.bridge and self.bridge.paused else t["pause"],
                             call(self.toggle_pause)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(t["quit"], call(lambda: self.quit(ask=False))),
        )
        self.tray = pystray.Icon("Achaja", image, "Achaja", menu)
        self.tray.run_detached()

    def show_window(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def hide_window(self):
        if self.tray:
            self.root.withdraw()
        else:
            self.root.iconify()

    def on_close(self):
        if self.tray and self.opts.get("close_to_tray", True):
            self.hide_window()
        else:
            self.quit()

    def quit(self, ask=True):
        from tkinter import messagebox
        if ask and not messagebox.askyesno("Achaja", self.t["quit_ask"], parent=self.root):
            return
        self.quitting = True
        write_json(WINDOW_FILE, {"geometry": self.root.geometry()})
        pid = self.claude_pid()
        if self.bridge:
            self.bridge.stop.set()
        if pid and self.bridge and self.bridge.hidden:
            import console
            if not console.is_visible(pid):  # ukryta sesja bez okna zostalaby w tle na zawsze
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                               creationflags=CREATE_NO_WINDOW)
        if self.tray:
            self.tray.stop()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--continue", dest="resume", action="store_true")
    ap.add_argument("--minimized", action="store_true")
    args = ap.parse_args()

    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Banzamel.Achaja")  # wlasna ikona na pasku
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass

    if not single_instance("AchajaListener"):
        if pid_alive(read_json(STATE / "app.json", {}).get("pid", 0)):
            write_json(SHOW_FLAG, {"at": time.time()})  # pierwsza kopia sama pokaze swoje okno
        else:
            from tkinter import Tk, messagebox
            root = Tk()
            root.withdraw()
            messagebox.showinfo("Achaja", TEXT.get(load_config().get("language"), TEXT["en"])["already"])
        return
    write_json(STATE / "app.json", {"pid": os.getpid()})
    App(args).run()


if __name__ == "__main__":
    main()
