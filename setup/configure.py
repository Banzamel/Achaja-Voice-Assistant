"""Ustawienia Achai: okienkowy kreator krok po kroku (instalator uruchamia go na koncu, pozniej menu Start).

Uzycie:
  configure.py                                  wszystkie moduly
  configure.py --modules voice,agents,mail,ha   tylko wybrane (instalator podaje wybrane skladniki)

Kroki: ogolne, glos, agenci, poczta (konta i zasady), Home Assistant, podsumowanie.
Zapisuje: config.json, state/ha_token.txt, .mcp.json i .claude/settings.local.json (Home Assistant).
Hasla i token nie sa wyswietlane - puste pole przy zapisie oznacza "bez zmian".
"""
import argparse
import json
import shutil
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".claude" / "scripts"))
import common  # noqa: E402  (tworzy state/, ustawia UTF-8)
import mail  # noqa: E402

CONFIG = ROOT / "config.json"
EXAMPLE = ROOT / "config.example.json"
HA_TOKEN = common.STATE / "ha_token.txt"
MCP = ROOT / ".mcp.json"
MCP_EXAMPLE = ROOT / ".mcp.example.json"
SETTINGS_LOCAL = ROOT / ".claude" / "settings.local.json"
MODULES = ("voice", "agents", "mail", "ha")
OUTPUT_NAMES = {"pl": ("słuchawki", "głośnik"), "en": ("headphones", "speaker")}
MAIL_KEYS = ("important_hint", "quiet_hours", "delete_after_days")


def load_raw():
    if not CONFIG.exists():
        shutil.copyfile(EXAMPLE, CONFIG)
    with open(CONFIG, encoding="utf-8-sig") as f:
        return json.load(f)


def save_raw(cfg):
    tmp = CONFIG.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(CONFIG)


def audio_devices():
    try:
        import sounddevice as sd
        names = {"input": [], "output": []}
        for i in sd.query_hostapis(0)["devices"]:  # MME - nazwy jak w ustawieniach Windows
            dev = sd.query_devices(i)
            if dev["max_input_channels"] > 0:
                names["input"].append(dev["name"])
            if dev["max_output_channels"] > 0:
                names["output"].append(dev["name"])
        return {k: sorted(set(v)) for k, v in names.items()}
    except Exception:
        return {"input": [], "output": []}


def first_output(outputs, kind):
    for name, out in outputs.items():
        if out.get("type") == kind:
            return name, out
    return None, None


def state_for_form(modules):
    cfg = load_raw()
    lang = cfg.get("language", "pl")
    voice = cfg.get("voice", {})
    outputs = voice.get("outputs", {})
    local_name, local = first_output(outputs, "local")
    cast_name, cast = first_output(outputs, "cast")
    m = cfg.get("mail", {})
    return {
        "modules": modules,
        "language": lang,
        "achaja": cfg.get("achaja", {}),
        "voice": {
            "microphone": cfg.get("wake", {}).get("microphone", ""),
            "local_device": (local or {}).get("device", ""),
            "cast": {"enabled": bool(cast), "name": (cast or {}).get("name", ""), "host": (cast or {}).get("host", "")},
            "default": "cast" if cast_name and voice.get("default_output") == cast_name else "local",
            "rate": voice.get("rate", "+15%"),
        },
        "agents": {"project_roots": cfg.get("agents", {}).get("project_roots", [])},
        "ha": {"enabled": MCP.exists(), "url": cfg.get("home_assistant", {}).get("url", ""),
               "has_token": HA_TOKEN.exists() and bool(HA_TOKEN.read_text(encoding="utf-8").strip())},
        "mail": {
            "enabled": bool(m.get("enabled")),
            **{k: m.get(k, mail.DEFAULTS.get(k, "")) for k in MAIL_KEYS},
            "important_senders": ", ".join(m.get("important_senders", [])),
            "ignored_senders": ", ".join(m.get("ignored_senders", [])),
            "digest_at": ", ".join(m.get("digest_at", [])),
            "announce": m.get("announce", mail.DEFAULTS["announce"]),
            "accounts": [{
                "key": f"{a.get('user', '')}@{a.get('host', '')}",
                **{k: a.get(k, "") for k in ("name", "user", "host", "display_name", "signature")},
                "port": a.get("port", 993), "security": a.get("security", "ssl"),
                "has_password": bool(a.get("password")),
            } for a in m.get("accounts", []) if not str(a.get("host", "")).endswith("example.com")],
        },
        "devices": audio_devices(),
    }


def split_list(value):
    return [x.strip() for x in str(value or "").replace("\n", ",").split(",") if x.strip()]


def apply_form(data, modules):
    cfg = load_raw()
    lang = data.get("language") or cfg.get("language", "pl")
    cfg["language"] = lang
    if data.get("achaja"):
        cfg.setdefault("achaja", {}).update({k: v for k, v in data["achaja"].items() if v})

    if "voice" in modules:
        v = data["voice"]
        cfg.setdefault("wake", {})["microphone"] = v.get("microphone", "")
        voice = cfg.setdefault("voice", {})
        voice["rate"] = v.get("rate") or voice.get("rate", "+15%")
        outputs = voice.setdefault("outputs", {})
        local_default, cast_default = OUTPUT_NAMES.get(lang, OUTPUT_NAMES["en"])
        local_name, local = first_output(outputs, "local")
        if not local_name:
            local_name, local = local_default, {"type": "local", "aliases": []}
            outputs[local_name] = local
        local["device"] = v.get("local_device", "")
        cast_name, cast = first_output(outputs, "cast")
        c = v.get("cast", {})
        if c.get("enabled") and c.get("host"):
            if not cast_name:
                cast_name, cast = cast_default, {"type": "cast", "aliases": []}
                outputs[cast_name] = cast
            cast.update(name=c.get("name", ""), host=c["host"])
        elif cast_name:
            outputs.pop(cast_name)
            cast_name = None
        voice["default_output"] = cast_name if v.get("default") == "cast" and cast_name else local_name

    if "agents" in modules:
        cfg.setdefault("agents", {})["project_roots"] = split_list(data["agents"].get("project_roots"))

    if "ha" in modules and data["ha"].get("enabled"):
        url = data["ha"].get("url", "").rstrip("/")
        cfg.setdefault("home_assistant", {})["url"] = url
        if data["ha"].get("token"):
            HA_TOKEN.write_text(data["ha"]["token"].strip(), encoding="utf-8")
        with open(MCP_EXAMPLE, encoding="utf-8") as f:
            mcp = json.load(f)
        mcp.pop("_comment", None)
        mcp["mcpServers"]["home-assistant"]["url"] = f"{url}/api/mcp"
        MCP.write_text(json.dumps(mcp, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        local = common.read_json(SETTINGS_LOCAL, {})
        servers = set(local.get("enabledMcpjsonServers", [])) | {"home-assistant"}
        local["enabledMcpjsonServers"] = sorted(servers)
        SETTINGS_LOCAL.write_text(json.dumps(local, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    m = cfg.setdefault("mail", {})
    if "mail" in modules:
        f = data["mail"]
        old = {f"{a.get('user', '')}@{a.get('host', '')}": a for a in m.get("accounts", [])}
        accounts = []
        for row in f.get("accounts", []):
            if not row.get("user") or not row.get("host"):
                continue
            prev = old.get(row.get("key") or "", {})
            acct = {**prev}  # zachowuje pola spoza formularza (smtp_*, handling konta...)
            acct.update({k: row.get(k, "") for k in ("name", "host", "user", "display_name", "signature")})
            acct.update(port=int(row.get("port") or 993), security=row.get("security") or "ssl",
                        password=row.get("password") or prev.get("password", ""))
            for k in ("display_name", "signature"):
                if not acct[k]:
                    acct.pop(k)
            accounts.append(acct)
        m.update({
            "enabled": bool(f.get("enabled")) and bool(accounts),
            "important_hint": f.get("important_hint", ""),
            "quiet_hours": f.get("quiet_hours", ""),
            "delete_after_days": int(f.get("delete_after_days") or 0),
            "important_senders": split_list(f.get("important_senders")),
            "ignored_senders": split_list(f.get("ignored_senders")),
            "digest_at": split_list(f.get("digest_at")),
            "announce": [c for c in f.get("announce", []) if c in mail.CATEGORIES],
            "accounts": accounts,
        })
    else:
        m["enabled"] = False
    save_raw(cfg)
    return cfg


def test_mail(row):
    prev = {f"{a.get('user', '')}@{a.get('host', '')}": a for a in load_raw().get("mail", {}).get("accounts", [])}
    raw = {k: row.get(k) for k in ("name", "host", "user", "security")}
    raw.update(port=int(row.get("port") or 993),
               password=row.get("password") or prev.get(row.get("key") or "", {}).get("password", ""))
    acct = {**prev.get(row.get("key") or "", {}), **raw}
    acct = mail.accounts({"language": load_raw().get("language", "pl"), "mail": {"accounts": [acct]}})
    if not acct:
        return [(False, "Podaj serwer i login.")]
    return mail.test_account(acct[0])


def test_ha(url, token):
    token = token or (HA_TOKEN.read_text(encoding="utf-8").strip() if HA_TOKEN.exists() else "")
    try:
        req = urllib.request.Request(url.rstrip("/") + "/api/", headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=8) as r:
            return [(r.status == 200, f"Home Assistant odpowiada ({r.status})")]
    except Exception as exc:
        return [(False, f"{type(exc).__name__}: {exc}")]


def discover_cast():
    try:
        import pychromecast
        casts, browser = pychromecast.get_chromecasts(timeout=6)
        browser.stop_discovery()
        return [{"name": c.cast_info.friendly_name, "host": c.cast_info.host, "model": c.cast_info.model_name}
                for c in casts]
    except Exception:
        return []


def restart_mail(cfg):
    if not common.PYTHON.exists():
        return
    if (cfg.get("mail") or {}).get("enabled"):
        subprocess.run([str(common.PYTHON), str(common.SCRIPTS / "mail.py"), "restart"],
                       capture_output=True, creationflags=common.CREATE_NO_WINDOW)
    elif mail.watcher_pid():
        subprocess.run([str(common.PYTHON), str(common.SCRIPTS / "mail.py"), "stop"],
                       capture_output=True, creationflags=common.CREATE_NO_WINDOW)


# ---------- okna ----------

TEXT = {
    "pl": {
        "title": "Achaja — ustawienia", "back": "< Wstecz", "next": "Dalej >", "save": "Zapisz", "cancel": "Anuluj",
        "step": "Krok {} z {}",
        "general": "Ogólne", "general_sub": "Język asystentki oraz model, na którym pracuje Achaja.",
        "language": "Język", "model": "Model Achai", "effort": "Wysiłek (szybkość / dokładność)",
        "voice": "Głos i mikrofon", "voice_sub": "Mikrofon do słowa wybudzenia i wyjście, na którym Achaja mówi.",
        "mic": "Mikrofon", "out": "Wyjście głosu (lokalne)", "rate": "Tempo mowy (np. +15%)", "default_dev": "(domyślne systemowe)",
        "cast": "Mów także przez głośnik Google Cast / Google Home", "cast_name": "Nazwa głośnika", "cast_host": "Adres IP głośnika",
        "cast_find": "Szukaj głośników w sieci", "cast_default": "Domyślnie mów przez głośnik", "searching": "Szukam…",
        "none_found": "Nie znaleziono głośników.", "found": "Znaleziono: {}",
        "agents": "Agenci projektów", "agents_sub": "Foldery z Twoimi projektami — każdy podfolder to projekt, któremu Achaja może zlecić pracę.",
        "add_folder": "Dodaj folder…", "remove": "Usuń",
        "mail": "Poczta — konta", "mail_sub": "Achaja pilnuje skrzynek IMAP: usuwa reklamy, spam i phishing, a o ważnych mailach mówi na głos.",
        "mail_on": "Włącz nasłuch poczty", "add": "Dodaj…", "edit": "Edytuj…", "test": "Testuj",
        "col_name": "Nazwa", "col_user": "Adres", "col_host": "Serwer",
        "rules": "Poczta — zasady", "rules_sub": "Co jest dla Ciebie ważne i kiedy Achaja ma o tym mówić.",
        "hint": "Co jest ważne (własnymi słowami)", "important": "Zawsze ważni nadawcy (adresy lub @domeny, po przecinku)",
        "ignored": "Pomijani nadawcy", "quiet": "Godziny ciszy (np. 22:00-07:00)", "digest": "Raport o godzinach (np. 09:00, 18:00)",
        "delete": "Usuwaj z serwera po (dniach)", "announce": "Mów na głos o:",
        "c_important": "ważnych", "c_threat": "zagrożeniach", "c_ad": "reklamach", "c_spam": "spamie",
        "ha": "Home Assistant", "ha_sub": "Sterowanie domem przez integrację „Model Context Protocol Server” i token długoterminowy.",
        "ha_on": "Włącz Home Assistant", "ha_url": "Adres Home Assistant", "ha_token": "Token (puste = bez zmian)",
        "summary": "Podsumowanie", "summary_sub": "Sprawdź i zapisz. Ustawienia zmienisz później w menu Start: „Achaja – ustawienia”.",
        "acc_title": "Konto pocztowe", "acc_name": "Nazwa konta", "acc_user": "Adres / login", "acc_pass": "Hasło (puste = bez zmian)",
        "acc_host": "Serwer", "acc_port": "Port", "acc_sec": "Szyfrowanie", "acc_display": "Twoje imię w odpowiedziach",
        "acc_sig": "Podpis", "ok": "OK", "testing": "Sprawdzam…", "need_host": "Podaj serwer i adres.",
        "saved": "Zapisano ustawienia.", "save_error": "Nie udało się zapisać: {}", "sum_accounts": "konta pocztowe: {}",
        "sum_mail_off": "poczta: wyłączona", "sum_roots": "foldery projektów: {}", "sum_ha": "Home Assistant: {}",
        "sum_mic": "mikrofon: {}", "sum_out": "wyjście: {}", "sum_cast": "głośnik: {}", "off": "wyłączony",
    },
    "en": {
        "title": "Achaja — settings", "back": "< Back", "next": "Next >", "save": "Save", "cancel": "Cancel",
        "step": "Step {} of {}",
        "general": "General", "general_sub": "The assistant's language and the model Achaja runs on.",
        "language": "Language", "model": "Achaja model", "effort": "Effort (speed / accuracy)",
        "voice": "Voice and microphone", "voice_sub": "The microphone for the wake word and the output Achaja speaks on.",
        "mic": "Microphone", "out": "Voice output (local)", "rate": "Speech rate (e.g. +15%)", "default_dev": "(system default)",
        "cast": "Also speak through a Google Cast / Google Home speaker", "cast_name": "Speaker name", "cast_host": "Speaker IP address",
        "cast_find": "Find speakers on the network", "cast_default": "Speak through the speaker by default", "searching": "Searching…",
        "none_found": "No speakers found.", "found": "Found: {}",
        "agents": "Project agents", "agents_sub": "Folders holding your projects — every subfolder is a project Achaja can hand work to.",
        "add_folder": "Add folder…", "remove": "Remove",
        "mail": "Mail — accounts", "mail_sub": "Achaja watches IMAP mailboxes: removes ads, spam and phishing, and announces important mail aloud.",
        "mail_on": "Enable the mail watcher", "add": "Add…", "edit": "Edit…", "test": "Test",
        "col_name": "Name", "col_user": "Address", "col_host": "Server",
        "rules": "Mail — rules", "rules_sub": "What matters to you and when Achaja should speak about it.",
        "hint": "What is important (in your own words)", "important": "Always important senders (addresses or @domains, comma separated)",
        "ignored": "Ignored senders", "quiet": "Quiet hours (e.g. 22:00-07:00)", "digest": "Report at (e.g. 09:00, 18:00)",
        "delete": "Delete from the server after (days)", "announce": "Speak about:",
        "c_important": "important", "c_threat": "threats", "c_ad": "ads", "c_spam": "spam",
        "ha": "Home Assistant", "ha_sub": "Home control through the “Model Context Protocol Server” integration and a long-lived token.",
        "ha_on": "Enable Home Assistant", "ha_url": "Home Assistant address", "ha_token": "Token (empty = unchanged)",
        "summary": "Summary", "summary_sub": "Check and save. Change settings later from the Start menu: “Achaja – settings”.",
        "acc_title": "Mail account", "acc_name": "Account name", "acc_user": "Address / login", "acc_pass": "Password (empty = unchanged)",
        "acc_host": "Server", "acc_port": "Port", "acc_sec": "Encryption", "acc_display": "Your name in replies",
        "acc_sig": "Signature", "ok": "OK", "testing": "Checking…", "need_host": "Enter the server and the address.",
        "saved": "Settings saved.", "save_error": "Could not save: {}", "sum_accounts": "mail accounts: {}",
        "sum_mail_off": "mail: off", "sum_roots": "project folders: {}", "sum_ha": "Home Assistant: {}",
        "sum_mic": "microphone: {}", "sum_out": "output: {}", "sum_cast": "speaker: {}", "off": "off",
    },
}
ACCENT = "#6c4cd4"


class Wizard:
    def __init__(self, modules):
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.ttk = tk, ttk
        self.modules = modules
        self.state = state_for_form(modules)
        self.lang = self.state["language"] if self.state["language"] in TEXT else "en"
        self.t = TEXT[self.lang]
        self.accounts = [dict(a, password="") for a in self.state["mail"]["accounts"]]
        self.saved = False

        self.root = root = tk.Tk()
        root.title(self.t["title"])
        root.geometry("700x540")
        root.minsize(620, 500)
        icon = ROOT / "setup" / "assets" / "achaja.ico"
        if icon.exists():
            root.iconbitmap(str(icon))
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Head.TFrame", background="white")
        style.configure("Head.TLabel", background="white")
        style.configure("Title.TLabel", background="white", font=("Segoe UI", 13, "bold"))
        style.configure("Sub.TLabel", background="white", foreground="#555", font=("Segoe UI", 9))
        style.configure("Step.TLabel", foreground="#777")

        head = ttk.Frame(root, style="Head.TFrame", padding=(18, 12))
        head.pack(fill="x")
        logo = ROOT / "setup" / "assets" / "achaja.png"
        if logo.exists():
            img = tk.PhotoImage(file=str(logo)).subsample(5)
            self._logo = img
            ttk.Label(head, image=img, style="Head.TLabel").pack(side="right")
        self.title_lbl = ttk.Label(head, style="Title.TLabel")
        self.title_lbl.pack(anchor="w")
        self.sub_lbl = ttk.Label(head, style="Sub.TLabel", wraplength=560, justify="left")
        self.sub_lbl.pack(anchor="w", pady=(2, 0))
        ttk.Separator(root).pack(fill="x")

        self.body = ttk.Frame(root, padding=(22, 16))
        self.body.pack(fill="both", expand=True)
        ttk.Separator(root).pack(fill="x")
        nav = ttk.Frame(root, padding=(14, 10))
        nav.pack(fill="x")
        self.step_lbl = ttk.Label(nav, style="Step.TLabel")
        self.step_lbl.pack(side="left")
        ttk.Button(nav, text=self.t["cancel"], command=root.destroy).pack(side="right")
        self.next_btn = ttk.Button(nav, text=self.t["next"], command=self.next)
        self.next_btn.pack(side="right", padx=(0, 8))
        self.back_btn = ttk.Button(nav, text=self.t["back"], command=self.back)
        self.back_btn.pack(side="right", padx=(0, 4))

        self.vars()
        self.pages = [("general", self.page_general)]
        if "voice" in modules:
            self.pages.append(("voice", self.page_voice))
        if "agents" in modules:
            self.pages.append(("agents", self.page_agents))
        if "mail" in modules:
            self.pages += [("mail", self.page_mail), ("rules", self.page_rules)]
        if "ha" in modules:
            self.pages.append(("ha", self.page_ha))
        self.pages.append(("summary", self.page_summary))
        self.index = 0
        self.show()

    # --- dane ---
    def vars(self):
        tk, s = self.tk, self.state
        v, m, h = s["voice"], s["mail"], s["ha"]
        self.v = {
            "language": tk.StringVar(value=s["language"]),
            "model": tk.StringVar(value=s["achaja"].get("model", "sonnet")),
            "effort": tk.StringVar(value=s["achaja"].get("effort", "low")),
            "mic": tk.StringVar(value=self.match(v["microphone"], s["devices"]["input"])),
            "out": tk.StringVar(value=self.match(v["local_device"], s["devices"]["output"])),
            "rate": tk.StringVar(value=v["rate"]),
            "cast_on": tk.BooleanVar(value=v["cast"]["enabled"]),
            "cast_name": tk.StringVar(value=v["cast"]["name"]),
            "cast_host": tk.StringVar(value=v["cast"]["host"]),
            "cast_default": tk.BooleanVar(value=v["default"] == "cast"),
            "mail_on": tk.BooleanVar(value=m["enabled"] or not m["accounts"]),
            "important": tk.StringVar(value=m["important_senders"]),
            "ignored": tk.StringVar(value=m["ignored_senders"]),
            "quiet": tk.StringVar(value=m.get("quiet_hours") or ""),
            "digest": tk.StringVar(value=m["digest_at"]),
            "delete": tk.StringVar(value=str(m.get("delete_after_days", 7))),
            "ha_on": tk.BooleanVar(value=h["enabled"]),
            "ha_url": tk.StringVar(value=h["url"]),
            "ha_token": tk.StringVar(),
        }
        self.announce = {c: tk.BooleanVar(value=c in m["announce"]) for c in ("important", "threat", "ad", "spam")}
        self.hint_text = m.get("important_hint") or ""
        self.roots = list(s["agents"]["project_roots"])

    def match(self, wanted, names):
        if not wanted:
            return self.t["default_dev"]
        return next((n for n in names if wanted.lower() in n.lower()), wanted)

    def device(self, value):
        return "" if value == self.t["default_dev"] else value

    # --- nawigacja ---
    def show(self):
        for w in self.body.winfo_children():
            w.destroy()
        key, build = self.pages[self.index]
        self.title_lbl.configure(text=self.t[key])
        self.sub_lbl.configure(text=self.t[f"{key}_sub"])
        self.step_lbl.configure(text=self.t["step"].format(self.index + 1, len(self.pages)))
        self.back_btn.state(["disabled"] if self.index == 0 else ["!disabled"])
        self.next_btn.configure(text=self.t["save"] if key == "summary" else self.t["next"])
        page = self.ttk.Frame(self.body)  # swieza ramka: ustawienia siatki nie przechodza miedzy stronami
        page.pack(fill="both", expand=True)
        build(page)

    def collect_page(self):
        if hasattr(self, "hint_widget") and self.hint_widget.winfo_exists():
            self.hint_text = self.hint_widget.get("1.0", "end").strip()

    def next(self):
        self.collect_page()
        if self.pages[self.index][0] == "summary":
            return self.save()
        self.index += 1
        self.show()

    def back(self):
        self.collect_page()
        self.index = max(0, self.index - 1)
        self.show()

    # --- pomocnicze ---
    def field(self, parent, label, var, row, width=40, show=None, values=None, col=0):
        ttk = self.ttk
        ttk.Label(parent, text=label).grid(row=row, column=col, sticky="w", pady=(0, 2))
        if values is not None:
            w = ttk.Combobox(parent, textvariable=var, values=values, width=width)
        else:
            w = ttk.Entry(parent, textvariable=var, width=width, show=show)
        w.grid(row=row + 1, column=col, sticky="we", pady=(0, 10), padx=(0, 12))
        return w

    def run_bg(self, work, done):
        """Test/wyszukiwanie w tle, zeby okno nie zamarzalo."""
        result = {}

        def worker():
            try:
                result["value"] = work()
            except Exception as exc:
                result["value"] = [(False, f"{type(exc).__name__}: {exc}")]

        th = threading.Thread(target=worker, daemon=True)
        th.start()

        def poll():
            if th.is_alive():
                self.root.after(150, poll)
            else:
                done(result.get("value"))
        poll()

    @staticmethod
    def results_text(results):
        return "\n".join(("✓ " if ok else "✗ ") + text for ok, text in results or [])

    # --- strony ---
    def page_general(self, p):
        p.columnconfigure(0, weight=1)
        self.field(p, self.t["language"], self.v["language"], 0, values=["pl", "en"], width=20)
        self.field(p, self.t["model"], self.v["model"], 2, values=["sonnet", "opus", "haiku"], width=20)
        self.field(p, self.t["effort"], self.v["effort"], 4, values=["low", "medium", "high"], width=20)

    def page_voice(self, p):
        ttk, dev = self.ttk, self.state["devices"]
        p.columnconfigure(0, weight=1)
        p.columnconfigure(1, weight=1)
        self.field(p, self.t["mic"], self.v["mic"], 0, values=[self.t["default_dev"]] + dev["input"])
        self.field(p, self.t["out"], self.v["out"], 0, values=[self.t["default_dev"]] + dev["output"], col=1)
        self.field(p, self.t["rate"], self.v["rate"], 2, width=12)
        box = ttk.Frame(p)
        box.grid(row=4, column=0, columnspan=2, sticky="we", pady=(6, 0))
        box.columnconfigure(0, weight=1)
        box.columnconfigure(1, weight=1)
        inner = ttk.Frame(box)

        def toggle():
            if self.v["cast_on"].get():
                inner.grid(row=1, column=0, columnspan=2, sticky="we", pady=(8, 0))
            else:
                inner.grid_remove()
        ttk.Checkbutton(box, text=self.t["cast"], variable=self.v["cast_on"], command=toggle).grid(row=0, column=0, sticky="w")
        inner.columnconfigure(0, weight=1)
        inner.columnconfigure(1, weight=1)
        self.field(inner, self.t["cast_name"], self.v["cast_name"], 0)
        self.field(inner, self.t["cast_host"], self.v["cast_host"], 0, col=1)
        ttk.Checkbutton(inner, text=self.t["cast_default"], variable=self.v["cast_default"]).grid(row=2, column=0, sticky="w")
        status = ttk.Label(inner, foreground="#555")
        status.grid(row=3, column=1, sticky="w")

        def find():
            status.configure(text=self.t["searching"])
            btn.state(["disabled"])

            def done(found):
                btn.state(["!disabled"])
                if not found:
                    status.configure(text=self.t["none_found"])
                    return
                first = found[0]
                self.v["cast_name"].set(first["name"])
                self.v["cast_host"].set(first["host"])
                status.configure(text=self.t["found"].format(", ".join(f"{c['name']} ({c['host']})" for c in found)))
            self.run_bg(discover_cast, done)
        btn = ttk.Button(inner, text=self.t["cast_find"], command=find)
        btn.grid(row=3, column=0, sticky="w", pady=(8, 0))
        toggle()

    def page_agents(self, p):
        ttk, tk = self.ttk, self.tk
        from tkinter import filedialog
        p.columnconfigure(0, weight=1)
        p.rowconfigure(0, weight=1)
        lb = tk.Listbox(p, height=10, activestyle="none", borderwidth=1, relief="solid", highlightthickness=0)
        lb.grid(row=0, column=0, sticky="nsew")
        for r in self.roots:
            lb.insert("end", r)
        side = ttk.Frame(p)
        side.grid(row=0, column=1, sticky="n", padx=(10, 0))

        def add():
            path = filedialog.askdirectory(parent=self.root, mustexist=True)
            if path:
                path = str(Path(path))
                if path not in self.roots:
                    self.roots.append(path)
                    lb.insert("end", path)

        def remove():
            for i in reversed(lb.curselection()):
                self.roots.pop(i)
                lb.delete(i)
        ttk.Button(side, text=self.t["add_folder"], command=add).pack(fill="x")
        ttk.Button(side, text=self.t["remove"], command=remove).pack(fill="x", pady=(6, 0))

    def page_mail(self, p):
        ttk = self.ttk
        p.columnconfigure(0, weight=1)
        p.rowconfigure(1, weight=1)
        ttk.Checkbutton(p, text=self.t["mail_on"], variable=self.v["mail_on"]).grid(row=0, column=0, sticky="w", pady=(0, 8))
        tree = ttk.Treeview(p, columns=("name", "user", "host"), show="headings", height=8, selectmode="browse")
        for col, key, w in (("name", "col_name", 160), ("user", "col_user", 220), ("host", "col_host", 160)):
            tree.heading(col, text=self.t[key])
            tree.column(col, width=w)
        tree.grid(row=1, column=0, sticky="nsew")
        status = ttk.Label(p, foreground="#555", wraplength=600, justify="left")
        status.grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))

        def refresh():
            tree.delete(*tree.get_children())
            for i, a in enumerate(self.accounts):
                tree.insert("", "end", iid=str(i), values=(a.get("name") or a["user"], a["user"], a["host"]))

        def selected():
            sel = tree.selection()
            return int(sel[0]) if sel else None

        def add():
            acc = self.account_dialog({"port": 993, "security": "ssl"})
            if acc:
                self.accounts.append(acc)
                refresh()

        def edit(_=None):
            i = selected()
            if i is not None:
                acc = self.account_dialog(dict(self.accounts[i]))
                if acc:
                    self.accounts[i] = acc
                    refresh()

        def remove():
            i = selected()
            if i is not None:
                self.accounts.pop(i)
                refresh()

        def test():
            i = selected()
            if i is None:
                return
            status.configure(text=self.t["testing"])
            self.run_bg(lambda: test_mail(self.accounts[i]), lambda r: status.configure(text=self.results_text(r)))
        tree.bind("<Double-1>", edit)
        side = ttk.Frame(p)
        side.grid(row=1, column=1, sticky="n", padx=(10, 0))
        for key, cmd in (("add", add), ("edit", edit), ("remove", remove), ("test", test)):
            ttk.Button(side, text=self.t[key], command=cmd).pack(fill="x", pady=(0, 6))
        refresh()

    def account_dialog(self, acc):
        tk, ttk = self.tk, self.ttk
        win = tk.Toplevel(self.root)
        win.title(self.t["acc_title"])
        win.transient(self.root)
        win.resizable(False, False)
        frm = ttk.Frame(win, padding=16)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(0, weight=1)
        frm.columnconfigure(1, weight=1)
        v = {k: tk.StringVar(value=str(acc.get(k, "") or "")) for k in
             ("name", "user", "password", "host", "port", "security", "display_name")}
        self.field(frm, self.t["acc_name"], v["name"], 0)
        self.field(frm, self.t["acc_user"], v["user"], 0, col=1)
        self.field(frm, self.t["acc_host"], v["host"], 2)
        pw = self.field(frm, self.t["acc_pass"], v["password"], 2, show="•", col=1)
        if acc.get("has_password"):
            pw.configure()
        self.field(frm, self.t["acc_sec"], v["security"], 4, values=["ssl", "starttls"], width=12)
        self.field(frm, self.t["acc_port"], v["port"], 4, width=8, col=1)
        v["security"].trace_add("write", lambda *_: v["port"].set("993" if v["security"].get() == "ssl" else "143"))
        self.field(frm, self.t["acc_display"], v["display_name"], 6)
        ttk.Label(frm, text=self.t["acc_sig"]).grid(row=8, column=0, sticky="w")
        sig = tk.Text(frm, height=3, width=60, font=("Segoe UI", 9), relief="solid", borderwidth=1)
        sig.grid(row=9, column=0, columnspan=2, sticky="we", pady=(0, 10))
        sig.insert("1.0", acc.get("signature") or "")
        status = ttk.Label(frm, foreground="#555", wraplength=520, justify="left")
        status.grid(row=10, column=0, columnspan=2, sticky="w")
        result = {}

        def current():
            data = {k: var.get().strip() for k, var in v.items()}
            data["signature"] = sig.get("1.0", "end").strip()
            data["key"] = acc.get("key", "")
            data["has_password"] = acc.get("has_password", False) or bool(data["password"])
            if not data["name"]:
                data["name"] = data["user"]
            return data

        def test():
            data = current()
            if not data["host"] or not data["user"]:
                status.configure(text=self.t["need_host"])
                return
            status.configure(text=self.t["testing"])
            self.run_bg(lambda: test_mail(data), lambda r: status.configure(text=self.results_text(r)))

        def ok():
            data = current()
            if not data["host"] or not data["user"]:
                status.configure(text=self.t["need_host"])
                return
            result["acc"] = data
            win.destroy()
        btns = ttk.Frame(frm)
        btns.grid(row=11, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(btns, text=self.t["test"], command=test).pack(side="left", padx=(0, 16))
        ttk.Button(btns, text=self.t["ok"], command=ok).pack(side="left", padx=(0, 6))
        ttk.Button(btns, text=self.t["cancel"], command=win.destroy).pack(side="left")
        win.grab_set()
        self.root.wait_window(win)
        return result.get("acc")

    def page_rules(self, p):
        ttk, tk = self.ttk, self.tk
        p.columnconfigure(0, weight=1)
        p.columnconfigure(1, weight=1)
        ttk.Label(p, text=self.t["hint"]).grid(row=0, column=0, columnspan=2, sticky="w")
        self.hint_widget = tk.Text(p, height=3, font=("Segoe UI", 9), relief="solid", borderwidth=1, wrap="word")
        self.hint_widget.grid(row=1, column=0, columnspan=2, sticky="we", pady=(2, 10))
        self.hint_widget.insert("1.0", self.hint_text)
        self.field(p, self.t["important"], self.v["important"], 2)
        self.field(p, self.t["ignored"], self.v["ignored"], 2, col=1)
        self.field(p, self.t["quiet"], self.v["quiet"], 4)
        self.field(p, self.t["digest"], self.v["digest"], 4, col=1)
        self.field(p, self.t["delete"], self.v["delete"], 6, width=8)
        row = ttk.Frame(p)
        row.grid(row=8, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Label(row, text=self.t["announce"]).pack(side="left", padx=(0, 8))
        for c in ("important", "threat", "ad", "spam"):
            ttk.Checkbutton(row, text=self.t[f"c_{c}"], variable=self.announce[c]).pack(side="left", padx=(0, 8))

    def page_ha(self, p):
        ttk = self.ttk
        p.columnconfigure(0, weight=1)
        ttk.Checkbutton(p, text=self.t["ha_on"], variable=self.v["ha_on"]).grid(row=0, column=0, sticky="w", pady=(0, 10))
        self.field(p, self.t["ha_url"], self.v["ha_url"], 1)
        tok = self.field(p, self.t["ha_token"], self.v["ha_token"], 3, show="•")
        if self.state["ha"]["has_token"]:
            tok.configure()
        status = ttk.Label(p, foreground="#555")
        status.grid(row=6, column=0, sticky="w", pady=(6, 0))

        def test():
            status.configure(text=self.t["testing"])
            self.run_bg(lambda: test_ha(self.v["ha_url"].get(), self.v["ha_token"].get()),
                        lambda r: status.configure(text=self.results_text(r)))
        ttk.Button(p, text=self.t["test"], command=test).grid(row=5, column=0, sticky="w")

    def page_summary(self, p):
        ttk = self.ttk
        lines = [f"{self.t['language']}: {self.v['language'].get()} · {self.t['model']}: {self.v['model'].get()} / {self.v['effort'].get()}"]
        if "voice" in self.modules:
            lines.append(self.t["sum_mic"].format(self.v["mic"].get()))
            lines.append(self.t["sum_out"].format(self.v["out"].get()))
            cast = f"{self.v['cast_name'].get()} ({self.v['cast_host'].get()})" if self.v["cast_on"].get() else self.t["off"]
            lines.append(self.t["sum_cast"].format(cast))
        if "agents" in self.modules:
            lines.append(self.t["sum_roots"].format(", ".join(self.roots) or "—"))
        if "mail" in self.modules:
            if self.v["mail_on"].get() and self.accounts:
                lines.append(self.t["sum_accounts"].format(", ".join(a.get("name") or a["user"] for a in self.accounts)))
            else:
                lines.append(self.t["sum_mail_off"])
        if "ha" in self.modules:
            lines.append(self.t["sum_ha"].format(self.v["ha_url"].get() if self.v["ha_on"].get() else self.t["off"]))
        for line in lines:
            ttk.Label(p, text="•  " + line, wraplength=620, justify="left").pack(anchor="w", pady=2)
        self.save_status = ttk.Label(p, foreground="#555")
        self.save_status.pack(anchor="w", pady=(14, 0))

    # --- zapis ---
    def form_data(self):
        v = self.v
        return {
            "language": v["language"].get(),
            "achaja": {"model": v["model"].get(), "effort": v["effort"].get()},
            "voice": {"microphone": self.device(v["mic"].get()), "local_device": self.device(v["out"].get()),
                      "rate": v["rate"].get(), "default": "cast" if v["cast_default"].get() else "local",
                      "cast": {"enabled": v["cast_on"].get(), "name": v["cast_name"].get(), "host": v["cast_host"].get()}},
            "agents": {"project_roots": "\n".join(self.roots)},
            "ha": {"enabled": v["ha_on"].get(), "url": v["ha_url"].get(), "token": v["ha_token"].get()},
            "mail": {"enabled": v["mail_on"].get(), "important_hint": self.hint_text,
                     "important_senders": v["important"].get(), "ignored_senders": v["ignored"].get(),
                     "quiet_hours": v["quiet"].get(), "digest_at": v["digest"].get(), "delete_after_days": v["delete"].get(),
                     "announce": [c for c, b in self.announce.items() if b.get()], "accounts": self.accounts},
        }

    def save(self):
        from tkinter import messagebox
        try:
            cfg = apply_form(self.form_data(), self.modules)
            restart_mail(cfg)
        except Exception as exc:
            messagebox.showerror(self.t["title"], self.t["save_error"].format(f"{type(exc).__name__}: {exc}"))
            return
        self.saved = True
        messagebox.showinfo(self.t["title"], self.t["saved"])
        self.root.destroy()

    def run(self):
        self.root.mainloop()
        return self.saved


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--modules", default=",".join(MODULES))
    args = ap.parse_args()
    modules = [m for m in args.modules.replace(" ", "").split(",") if m in MODULES]
    try:  # ostre czcionki na ekranach z powiekszeniem
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    Wizard(modules).run()


if __name__ == "__main__":
    main()
