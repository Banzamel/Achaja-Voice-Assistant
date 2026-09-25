"""Konfigurator Achai: formularz w przegladarce do uzupelnienia config.json (tylko ten komputer).

Uzycie:
  configure.py                              wszystkie moduly
  configure.py --modules voice,agents,mail,ha   tylko wybrane (instalator podaje wybrane skladniki)
  configure.py --no-browser                 nie otwiera przegladarki (adres wypisuje w konsoli)

Zapisuje: config.json, state/ha_token.txt, .mcp.json i .claude/settings.local.json (Home Assistant).
Hasla i token nie wracaja do przegladarki - puste pole przy zapisie oznacza "bez zmian".
Serwer slucha tylko na 127.0.0.1 i wymaga losowego klucza z adresu strony.
"""
import argparse
import json
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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


def make_handler(key, modules, server_ref):
    last_ping = {"at": time.time()}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", f"{ctype}; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def authorized(self):
            return self.headers.get("X-Achaja-Key") == key

        def do_GET(self):
            if self.path == f"/?k={key}":
                return self.send(200, PAGE.encode("utf-8"), "text/html")
            if not self.authorized():
                return self.send(403, {"error": "forbidden"})
            last_ping["at"] = time.time()
            if self.path == "/api/state":
                return self.send(200, state_for_form(modules))
            if self.path == "/api/cast":
                return self.send(200, discover_cast())
            if self.path == "/api/ping":
                return self.send(200, {"ok": True})
            self.send(404, {"error": "not found"})

        def do_POST(self):
            if not self.authorized():
                return self.send(403, {"error": "forbidden"})
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            if self.path == "/api/test-mail":
                return self.send(200, test_mail(body))
            if self.path == "/api/test-ha":
                return self.send(200, test_ha(body.get("url", ""), body.get("token", "")))
            if self.path in ("/api/save", "/api/quit"):
                if self.path == "/api/save":
                    try:
                        cfg = apply_form(body, modules)
                        restart_mail(cfg)
                    except Exception as exc:
                        return self.send(200, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})
                self.send(200, {"ok": True})
                threading.Timer(0.5, server_ref[0].shutdown).start()
                return
            self.send(404, {"error": "not found"})

    return Handler, last_ping


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--modules", default=",".join(MODULES))
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--port", type=int, default=0)
    args = ap.parse_args()
    modules = [m for m in args.modules.replace(" ", "").split(",") if m in MODULES]
    key = secrets.token_urlsafe(24)
    server_ref = [None]
    handler, last_ping = make_handler(key, modules, server_ref)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    server_ref[0] = server
    url = f"http://127.0.0.1:{server.server_address[1]}/?k={key}"

    def watchdog():  # zamknieta karta bez zapisu nie blokuje instalatora na zawsze
        while True:
            time.sleep(10)
            if time.time() - last_ping["at"] > 900:
                server.shutdown()
                return

    threading.Thread(target=watchdog, daemon=True).start()
    print(f"Konfiguracja Achai / Achaja setup: {url}", flush=True)
    print("Formularz otworzy sie w przegladarce. Zapisz go, aby zakonczyc. / Save the form to finish.")
    if not args.no_browser:
        webbrowser.open(url)
    server.serve_forever()
    print("Konfiguracja zakonczona. / Setup finished.")


PAGE = r"""<!doctype html>
<html lang="pl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Achaja — konfiguracja</title>
<style>
:root{--bg:#f4f5f7;--card:#fff;--text:#1d2330;--muted:#667085;--line:#dde1e7;--accent:#6c4cd4;--ok:#1a7f4b;--err:#b42318}
@media (prefers-color-scheme:dark){:root{--bg:#14161b;--card:#1d2027;--text:#e6e8ec;--muted:#9aa1ad;--line:#30343d;--accent:#9d86ff;--ok:#4ccf8a;--err:#ff7b6e}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:860px;margin:0 auto;padding:24px 16px 120px}h1{margin:0 0 4px;font-size:26px}p.lead{margin:0 0 20px;color:var(--muted)}
section{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px 20px;margin:0 0 16px}
section h2{margin:0 0 4px;font-size:18px}section p.hint{margin:0 0 14px;color:var(--muted);font-size:13px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px 16px}
label{display:block;font-size:13px;color:var(--muted);margin-bottom:4px}label.inline{display:flex;gap:8px;align-items:center;color:var(--text);font-size:15px}
input,select,textarea{width:100%;padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--text);font:inherit}
input[type=checkbox]{width:auto}textarea{min-height:60px;resize:vertical}
button{border:1px solid var(--line);background:var(--card);color:var(--text);padding:7px 14px;border-radius:8px;font:inherit;cursor:pointer}
button.primary{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:600}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:10px}
.account{border:1px dashed var(--line);border-radius:10px;padding:12px;margin:10px 0}
.result{font-size:13px;margin-top:8px;white-space:pre-wrap}.ok{color:var(--ok)}.err{color:var(--err)}
.bar{position:fixed;left:0;right:0;bottom:0;background:var(--card);border-top:1px solid var(--line);padding:12px 16px}
.bar .in{max-width:860px;margin:0 auto;display:flex;gap:10px;align-items:center;justify-content:flex-end;flex-wrap:wrap}
.bar .msg{margin-right:auto}.hidden{display:none}
</style></head><body><main>
<h1 data-t="title"></h1><p class="lead" data-t="lead"></p>
<section id="s-general"><h2 data-t="general"></h2><div class="grid">
 <div><label data-t="language"></label><select id="language"><option value="pl">Polski</option><option value="en">English</option></select></div>
 <div><label data-t="model"></label><select id="model"><option value="sonnet">Sonnet</option><option value="opus">Opus</option><option value="haiku">Haiku</option></select></div>
 <div><label data-t="effort"></label><select id="effort"><option value="low">low</option><option value="medium">medium</option><option value="high">high</option></select></div>
</div></section>
<section id="s-voice"><h2 data-t="voice"></h2><p class="hint" data-t="voiceHint"></p><div class="grid">
 <div><label data-t="mic"></label><select id="mic"></select></div>
 <div><label data-t="out"></label><select id="outdev"></select></div>
 <div><label data-t="rate"></label><input id="rate"></div>
</div>
 <div class="row"><label class="inline"><input type="checkbox" id="cast-on"><span data-t="cast"></span></label></div>
 <div class="grid" id="cast-box"><div><label data-t="castName"></label><input id="cast-name"></div><div><label data-t="castHost"></label><input id="cast-host" placeholder="192.168.0.10"></div>
 <div><label data-t="defaultOut"></label><select id="default-out"><option value="local" data-t="optLocal"></option><option value="cast" data-t="optCast"></option></select></div></div>
 <div class="row" id="cast-find-row"><button id="cast-find" data-t="find"></button><span id="cast-result" class="result"></span></div>
</section>
<section id="s-agents"><h2 data-t="agents"></h2><p class="hint" data-t="agentsHint"></p>
 <label data-t="roots"></label><textarea id="roots" placeholder="C:\projects"></textarea></section>
<section id="s-ha"><h2>Home Assistant</h2><p class="hint" data-t="haHint"></p>
 <label class="inline"><input type="checkbox" id="ha-on"><span data-t="haOn"></span></label>
 <div class="grid" style="margin-top:10px"><div><label data-t="haUrl"></label><input id="ha-url" placeholder="http://homeassistant.local:8123"></div>
 <div><label data-t="haToken"></label><input id="ha-token" type="password" autocomplete="off"></div></div>
 <div class="row"><button id="ha-test" data-t="test"></button><span id="ha-result" class="result"></span></div></section>
<section id="s-mail"><h2 data-t="mail"></h2><p class="hint" data-t="mailHint"></p>
 <label class="inline"><input type="checkbox" id="mail-on"><span data-t="mailOn"></span></label>
 <div id="accounts"></div><div class="row"><button id="add-account" data-t="addAccount"></button></div>
 <div class="grid" style="margin-top:14px">
  <div style="grid-column:1/-1"><label data-t="hintLbl"></label><textarea id="m-hint" data-tp="hintPh"></textarea></div>
  <div><label data-t="importantLbl"></label><input id="m-important" placeholder="szef@firma.pl, @urzad.gov.pl"></div>
  <div><label data-t="ignoredLbl"></label><input id="m-ignored"></div>
  <div><label data-t="quietLbl"></label><input id="m-quiet" placeholder="22:00-07:00"></div>
  <div><label data-t="digestLbl"></label><input id="m-digest" placeholder="09:00, 18:00"></div>
  <div><label data-t="deleteLbl"></label><input id="m-delete" type="number" min="0"></div>
 </div>
 <div class="row"><span data-t="announceLbl"></span>
  <label class="inline"><input type="checkbox" class="ann" value="important"><span data-t="cImportant"></span></label>
  <label class="inline"><input type="checkbox" class="ann" value="threat"><span data-t="cThreat"></span></label>
  <label class="inline"><input type="checkbox" class="ann" value="ad"><span data-t="cAd"></span></label>
  <label class="inline"><input type="checkbox" class="ann" value="spam">spam</label></div>
</section>
</main>
<div class="bar"><div class="in"><span class="msg result" id="save-result"></span>
 <button id="quit" data-t="quit"></button><button class="primary" id="save" data-t="save"></button></div></div>
<template id="acc-tpl"><div class="account"><div class="grid">
 <div><label data-t="accName"></label><input data-f="name" placeholder="Firma"></div>
 <div><label data-t="accUser"></label><input data-f="user" placeholder="ja@firma.pl"></div>
 <div><label data-t="accPass"></label><input data-f="password" type="password" autocomplete="new-password"></div>
 <div><label data-t="accHost"></label><input data-f="host" placeholder="mail.firma.pl"></div>
 <div><label data-t="accPort"></label><input data-f="port" type="number" value="993"></div>
 <div><label data-t="accSec"></label><select data-f="security"><option value="ssl">SSL (993)</option><option value="starttls">STARTTLS (143)</option></select></div>
 <div><label data-t="accDisplay"></label><input data-f="display_name"></div>
 <div style="grid-column:1/-1"><label data-t="accSig"></label><textarea data-f="signature"></textarea></div></div>
 <div class="row"><button class="acc-test" data-t="test"></button><button class="acc-del" data-t="remove"></button><span class="result acc-result"></span></div></div></template>
<script>
const KEY=new URLSearchParams(location.search).get("k");
const T={pl:{title:"Achaja — konfiguracja",lead:"Uzupełnij ustawienia wybranych modułów. Wszystko zostaje na tym komputerze; hasła nie wracają do tej strony — puste pole hasła oznacza „bez zmian”.",
general:"Ogólne",language:"Język asystentki",model:"Model Achai",effort:"Wysiłek (szybkość / dokładność)",voice:"Głos i mikrofon",voiceHint:"Mikrofon do słowa wybudzenia i wyjście, na którym Achaja mówi.",
mic:"Mikrofon",out:"Wyjście głosu (lokalne)",rate:"Tempo mowy",cast:"Głośnik Google Cast / Google Home",castName:"Nazwa głośnika",castHost:"Adres IP głośnika",defaultOut:"Domyślne wyjście",optLocal:"lokalne",optCast:"głośnik",find:"Szukaj głośników w sieci",
agents:"Agenci projektów",agentsHint:"Foldery, w których leżą Twoje projekty — każdy podfolder to projekt, któremu Achaja może zlecić pracę.",roots:"Foldery z projektami (jeden w linii)",
haHint:"Sterowanie domem przez integrację „Model Context Protocol Server” w Home Assistant i token długoterminowy.",haOn:"Włącz Home Assistant",haUrl:"Adres Home Assistant",haToken:"Token (puste = bez zmian)",
mail:"Poczta",mailHint:"Achaja pilnuje skrzynek IMAP: usuwa reklamy, spam i phishing, a o ważnych mailach mówi na głos. Odpowiedzi idą przez SMTP tego samego serwera.",mailOn:"Włącz nasłuch poczty",addAccount:"+ Dodaj konto",
hintLbl:"Co jest dla Ciebie ważne (własnymi słowami)",hintPh:"Np. wszystko od klientów i o fakturach jest ważne; newslettery to reklama.",importantLbl:"Zawsze ważni nadawcy (adresy lub @domeny)",ignoredLbl:"Pomijani nadawcy",quietLbl:"Godziny ciszy",digestLbl:"Raport o godzinach",deleteLbl:"Usuwaj z serwera po (dniach)",
announceLbl:"Mów na głos o:",cImportant:"ważnych",cThreat:"zagrożeniach",cAd:"reklamach",accName:"Nazwa konta",accUser:"Adres / login",accPass:"Hasło (puste = bez zmian)",accHost:"Serwer",accPort:"Port",accSec:"Szyfrowanie",accDisplay:"Twoje imię w odpowiedziach",accSig:"Podpis",
test:"Testuj",remove:"Usuń",save:"Zapisz i zakończ",quit:"Zamknij bez zapisu",saved:"Zapisano. Możesz zamknąć tę kartę.",closed:"Zamknięto bez zapisu. Możesz zamknąć tę kartę.",testing:"Sprawdzam…",searching:"Szukam…",none:"Nie znaleziono głośników.",default:"(domyślne systemowe)"},
en:{title:"Achaja — setup",lead:"Fill in the settings of the selected modules. Everything stays on this computer; passwords are never sent back to this page — an empty password field means “unchanged”.",
general:"General",language:"Assistant language",model:"Achaja model",effort:"Effort (speed / accuracy)",voice:"Voice and microphone",voiceHint:"The microphone for the wake word and the output Achaja speaks on.",
mic:"Microphone",out:"Voice output (local)",rate:"Speech rate",cast:"Google Cast / Google Home speaker",castName:"Speaker name",castHost:"Speaker IP address",defaultOut:"Default output",optLocal:"local",optCast:"speaker",find:"Find speakers on the network",
agents:"Project agents",agentsHint:"Folders holding your projects — every subfolder is a project Achaja can hand work to.",roots:"Project folders (one per line)",
haHint:"Home control through the “Model Context Protocol Server” integration in Home Assistant and a long-lived token.",haOn:"Enable Home Assistant",haUrl:"Home Assistant address",haToken:"Token (empty = unchanged)",
mail:"Mail",mailHint:"Achaja watches IMAP mailboxes: removes ads, spam and phishing, and announces important mail aloud. Replies go through SMTP on the same server.",mailOn:"Enable the mail watcher",addAccount:"+ Add account",
hintLbl:"What is important to you (in your own words)",hintPh:"E.g. anything from clients or about invoices is important; newsletters are ads.",importantLbl:"Always important senders (addresses or @domains)",ignoredLbl:"Ignored senders",quietLbl:"Quiet hours",digestLbl:"Report at",deleteLbl:"Delete from the server after (days)",
announceLbl:"Speak about:",cImportant:"important",cThreat:"threats",cAd:"ads",accName:"Account name",accUser:"Address / login",accPass:"Password (empty = unchanged)",accHost:"Server",accPort:"Port",accSec:"Encryption",accDisplay:"Your name in replies",accSig:"Signature",
test:"Test",remove:"Remove",save:"Save and finish",quit:"Close without saving",saved:"Saved. You can close this tab.",closed:"Closed without saving. You can close this tab.",testing:"Checking…",searching:"Searching…",none:"No speakers found.",default:"(system default)"}};
let L="pl",S=null;const $=id=>document.getElementById(id);
const api=(p,b)=>fetch(p,{method:b?"POST":"GET",headers:{"X-Achaja-Key":KEY,"Content-Type":"application/json"},body:b?JSON.stringify(b):undefined}).then(r=>r.json());
function tr(root=document){root.querySelectorAll("[data-t]").forEach(e=>e.textContent=T[L][e.dataset.t]);root.querySelectorAll("[data-tp]").forEach(e=>e.placeholder=T[L][e.dataset.tp]);document.documentElement.lang=L}
function show(el,res){el.innerHTML="";res.forEach(([ok,t])=>{const d=document.createElement("div");d.className=ok?"ok":"err";d.textContent=(ok?"✓ ":"✗ ")+t;el.appendChild(d)})}
function fillSelect(sel,items,val){sel.innerHTML="";const o=new Option(T[L].default,"");sel.add(o);items.forEach(n=>sel.add(new Option(n,n)));
 if(val&&!items.some(n=>n.toLowerCase().includes(val.toLowerCase())))sel.add(new Option(val,val));
 sel.value=items.find(n=>val&&n.toLowerCase().includes(val.toLowerCase()))||val||""}
function addAccount(a={}){const n=$("acc-tpl").content.firstElementChild.cloneNode(true);n.dataset.key=a.key||"";
 n.querySelectorAll("[data-f]").forEach(e=>{const v=a[e.dataset.f];if(v!==undefined&&v!=="")e.value=v});
 if(a.has_password)n.querySelector('[data-f=password]').placeholder="••••••••";
 n.querySelector(".acc-del").onclick=()=>n.remove();
 n.querySelector("[data-f=security]").onchange=e=>{n.querySelector("[data-f=port]").value=e.target.value==="ssl"?993:143};
 n.querySelector(".acc-test").onclick=async()=>{const r=n.querySelector(".acc-result");r.textContent=T[L].testing;show(r,await api("/api/test-mail",readAccount(n)))};
 tr(n);$("accounts").appendChild(n)}
function readAccount(n){const a={key:n.dataset.key};n.querySelectorAll("[data-f]").forEach(e=>a[e.dataset.f]=e.value.trim?e.value.trim():e.value);return a}
async function load(){S=await api("/api/state");L=S.language in T?S.language:"en";tr();
 for(const m of["voice","agents","mail","ha"])$("s-"+m).classList.toggle("hidden",!S.modules.includes(m));
 $("language").value=S.language;$("model").value=S.achaja.model||"sonnet";$("effort").value=S.achaja.effort||"low";
 const v=S.voice;fillSelect($("mic"),S.devices.input,v.microphone);fillSelect($("outdev"),S.devices.output,v.local_device);$("rate").value=v.rate;
 $("cast-on").checked=v.cast.enabled;$("cast-name").value=v.cast.name;$("cast-host").value=v.cast.host;$("default-out").value=v.default;castToggle();
 $("roots").value=S.agents.project_roots.join("\n");
 $("ha-on").checked=S.ha.enabled;$("ha-url").value=S.ha.url;if(S.ha.has_token)$("ha-token").placeholder="••••••••";
 const m=S.mail;$("mail-on").checked=m.enabled;$("m-hint").value=m.important_hint||"";$("m-important").value=m.important_senders;$("m-ignored").value=m.ignored_senders;
 $("m-quiet").value=m.quiet_hours||"";$("m-digest").value=m.digest_at;$("m-delete").value=m.delete_after_days;
 document.querySelectorAll(".ann").forEach(c=>c.checked=m.announce.includes(c.value));
 m.accounts.forEach(addAccount);if(!m.accounts.length)addAccount();
 setInterval(()=>api("/api/ping"),20000)}
function castToggle(){const on=$("cast-on").checked;$("cast-box").classList.toggle("hidden",!on);$("cast-find-row").classList.toggle("hidden",!on)}
$("cast-on").onchange=castToggle;
$("language").onchange=e=>{L=e.target.value;tr()};
$("cast-find").onclick=async()=>{const r=$("cast-result");r.textContent=T[L].searching;const list=await api("/api/cast");r.innerHTML="";
 if(!list.length){r.textContent=T[L].none;return}list.forEach(c=>{const b=document.createElement("button");b.textContent=`${c.name} (${c.host})`;b.onclick=()=>{$("cast-name").value=c.name;$("cast-host").value=c.host};r.appendChild(b)})};
$("ha-test").onclick=async()=>{const r=$("ha-result");r.textContent=T[L].testing;show(r,await api("/api/test-ha",{url:$("ha-url").value,token:$("ha-token").value}))};
$("add-account").onclick=()=>addAccount();
function collect(){return{language:$("language").value,achaja:{model:$("model").value,effort:$("effort").value},
 voice:{microphone:$("mic").value,local_device:$("outdev").value,rate:$("rate").value,default:$("default-out").value,cast:{enabled:$("cast-on").checked,name:$("cast-name").value,host:$("cast-host").value}},
 agents:{project_roots:$("roots").value},ha:{enabled:$("ha-on").checked,url:$("ha-url").value,token:$("ha-token").value},
 mail:{enabled:$("mail-on").checked,important_hint:$("m-hint").value,important_senders:$("m-important").value,ignored_senders:$("m-ignored").value,quiet_hours:$("m-quiet").value,
  digest_at:$("m-digest").value,delete_after_days:$("m-delete").value,announce:[...document.querySelectorAll(".ann:checked")].map(c=>c.value),
  accounts:[...document.querySelectorAll("#accounts .account")].map(readAccount)}}}
function done(msg){document.querySelectorAll("button,input,select,textarea").forEach(e=>e.disabled=true);$("save-result").className="msg result ok";$("save-result").textContent=msg}
$("save").onclick=async()=>{const r=await api("/api/save",collect());if(r.ok)done(T[L].saved);else{$("save-result").className="msg result err";$("save-result").textContent=r.error}};
$("quit").onclick=async()=>{await api("/api/quit",{});done(T[L].closed)};
load();
</script></body></html>"""

if __name__ == "__main__":
    main()
