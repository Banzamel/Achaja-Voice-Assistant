"""Poczta Achai: wspolne funkcje IMAP/SMTP i polecenia dla sesji Achai.

Uzycie:
  mail.py status                          nasluch, konta, bledy, przeglad starej poczty
  mail.py summary [--hours H]             raport do przeczytania na glos (ile waznych, ile usunietych...)
  mail.py list [--category C] [--hours H] [--account A] [--all]
                                          ostatnio sklasyfikowane wiadomosci
  mail.py show <id>                       pelna tresc (z serwera; nie oznacza jako przeczytanej)
  mail.py move <id> <kategoria|inbox>     poprawka klasyfikacji / przywrocenie do skrzynki
  mail.py rescan [--account A] [--days N] [--all]
                                          ponowny przeglad poczty w skrzynce (nieprzeczytane zawsze)
  mail.py reply <id> --text-file F [--all] [--draft] [--dry-run]
                                          odpowiedz na wiadomosc (--draft: tylko szkic na serwerze)
  mail.py send --account A --to ADRES --subject T --text-file F [--draft] [--dry-run]
  mail.py test                            logowanie IMAP/SMTP i mozliwosci serwera kazdego konta
  mail.py start | stop | restart          nasluch poczty w tle (mail_watch.py)

Kategorie: important, normal, ad, spam, threat.
Konta i zasady: config.json -> "mail" (tablica "accounts"; kazde konto moze nadpisac ustawienia wspolne).
Na dysku zostaja tylko metadane (nadawca, temat, kategoria) z ostatnich log_days dni - tresci nie.
"""
import argparse
import email
import email.policy
import html
import re
import smtplib
import ssl
import subprocess
import sys
import threading
import time
from email.message import EmailMessage
from email.utils import formataddr, formatdate, getaddresses, make_msgid, parseaddr

from common import (CREATE_NO_WINDOW, DETACHED_PROCESS, PYTHONW, SCRIPTS, STATE, load_config, pid_alive,
                    read_json, write_json)

MAIL_STATE = STATE / "mail"
MAIL_STATE.mkdir(exist_ok=True)
LOG = MAIL_STATE / "messages.json"
STATUS = MAIL_STATE / "status.json"
RESCAN = MAIL_STATE / "rescan.json"
LOG_LIMIT = 3000

CATEGORIES = ("important", "normal", "ad", "spam", "threat")
LABELS = {
    "pl": {"important": "ważne", "normal": "zwykłe", "ad": "reklama", "spam": "spam", "threat": "zagrożenie"},
    "en": {"important": "important", "normal": "normal", "ad": "ad", "spam": "spam", "threat": "threat"},
}
# gdzie trafiaja wiadomosci danej kategorii: nazwa folderu, "keep" (zostaw w skrzynce) albo "delete" (usun od razu)
HANDLING = {
    "pl": {"important": "keep", "normal": "keep", "ad": "Achaja/Reklamy", "spam": "Achaja/Spam",
           "threat": "Achaja/Kwarantanna"},
    "en": {"important": "keep", "normal": "keep", "ad": "Achaja/Ads", "spam": "Achaja/Spam",
           "threat": "Achaja/Quarantine"},
}
DEFAULTS = {
    "enabled": True,
    "model": "haiku",
    "folder": "INBOX",
    "security": "ssl",
    "verify_tls": True,
    "announce": ["important", "threat"],
    "digest_at": [],
    "quiet_hours": "",
    "important_hint": "",
    "important_senders": [],
    "ignored_senders": [],
    "delete_after_days": 7,
    "log_days": 14,
    "scan_existing": True,
    "scan_existing_days": 30,
    "scan_attachments": True,
    "blocked_extensions": ["exe", "scr", "com", "pif", "bat", "cmd", "vbs", "vbe", "js", "jse", "wsf", "wsh",
                           "hta", "msi", "msix", "appx", "lnk", "iso", "img", "vhd", "vhdx", "jar", "ps1", "cpl",
                           "reg", "docm", "xlsm", "pptm", "one"],
    "poll_seconds": 120,
    "signature": "",
}

_log_lock = threading.Lock()


def lang(cfg):
    return cfg.get("language", "pl") if cfg.get("language") in LABELS else "en"


def label(category, cfg):
    return LABELS[lang(cfg)].get(category, category)


def accounts(cfg, include_disabled=False):
    """Konta z config.json: ustawienia wspolne sekcji "mail" + nadpisania z kazdego konta."""
    mail = cfg.get("mail") or {}
    # mail.enabled wlacza caly nasluch; "enabled" w koncie wylacza tylko to konto
    base = {**DEFAULTS, **{k: v for k, v in mail.items() if k not in ("accounts", "enabled") and not k.startswith("_")}}
    result = []
    for raw in mail.get("accounts", []):
        acct = {**base, **{k: v for k, v in raw.items() if not k.startswith("_")}}
        acct["handling"] = {**HANDLING[lang(cfg)], **(base.get("handling") or {}), **(raw.get("handling") or {})}
        acct["name"] = acct.get("name") or acct.get("user")
        acct["address"] = acct.get("address") or acct.get("user")
        if not acct.get("host") or not acct.get("user"):
            continue
        if acct.get("enabled", True) or include_disabled:
            result.append(acct)
    return result


def find_account(cfg, name):
    for acct in accounts(cfg, include_disabled=True):
        if acct["name"].lower() == str(name).lower() or acct["address"].lower() == str(name).lower():
            return acct
    sys.exit(f"Nie ma konta '{name}' w config.json (mail.accounts).")


# ---------- IMAP ----------

def tls_context(acct):
    context = ssl.create_default_context()
    if not acct.get("verify_tls", True):  # np. wlasny serwer z certyfikatem self-signed
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return context


def connect(acct):
    from imapclient import IMAPClient
    security = acct.get("security", "ssl")
    port = acct.get("port") or (993 if security == "ssl" else 143)
    client = IMAPClient(acct["host"], port=port, ssl=security == "ssl", ssl_context=tls_context(acct), timeout=90)
    if security == "starttls":
        client.starttls(tls_context(acct))
    client.login(acct["user"], acct["password"])
    return client


def _text(value):
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else (value or "")


def server_folder(client, name):
    """'Achaja/Reklamy' -> nazwa zgodna z serwerem (separator i prefiks, np. 'INBOX.Achaja.Reklamy')."""
    if name.upper() == "INBOX":
        return "INBOX"
    if not hasattr(client, "_achaja_ns"):
        try:
            prefix, delim = client.namespace().personal[0]
            client._achaja_ns = (_text(prefix), _text(delim) or "/")
        except Exception:
            client._achaja_ns = ("", "/")
    prefix, delim = client._achaja_ns
    path = name.replace("/", delim)
    return path if not prefix or path.startswith(prefix) else prefix + path


def special_folder(client, use, names):
    """Folder specjalny (\\Sent, \\Drafts) wg RFC 6154, a gdy serwer go nie oznacza - po typowych nazwach."""
    folders = client.list_folders()
    for flags, _, name in folders:
        if use in flags:
            return name
    lowered = {_text(n).lower(): n for _, _, n in folders}
    for n in names:
        for candidate in (n, server_folder(client, n)):
            if candidate.lower() in lowered:
                return lowered[candidate.lower()]
    return ensure_folder(client, names[0])


def ensure_folder(client, name):
    folder = server_folder(client, name)
    if not client.folder_exists(folder):
        client.create_folder(folder)
        try:
            client.subscribe_folder(folder)
        except Exception:
            pass
    return folder


def expunge(client, uids):
    if client.has_capability("UIDPLUS"):
        client.uid_expunge(uids)
    else:
        client.expunge()


def move(client, uids, target):
    """Przenosi (albo przy target == "delete" usuwa z serwera) wiadomosci z aktualnie wybranego folderu."""
    if not uids or target == "keep":
        return None
    if target == "delete":
        client.delete_messages(uids)
        expunge(client, uids)
        return None
    folder = ensure_folder(client, target)
    if client.has_capability("MOVE"):
        client.move(uids, folder)
    else:
        client.copy(uids, folder)
        client.delete_messages(uids)
        expunge(client, uids)
    return folder


# ---------- wiadomosci ----------

def html_to_text(value):
    value = re.sub(r"(?is)<(script|style|head).*?</\1>", " ", value)
    value = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", value)
    return html.unescape(re.sub(r"<[^>]+>", " ", value))


def body_text(msg):
    try:
        part = msg.get_body(preferencelist=("plain", "html"))
        if part is None:
            return ""
        content = part.get_content()
        if part.get_content_type() == "text/html":
            content = html_to_text(content)
    except Exception:
        return ""
    return re.sub(r"[ \t\r\f\v]+", " ", re.sub(r"\n\s*\n+", "\n\n", content)).strip()


def attachments(msg):
    result = []
    for part in msg.iter_attachments():
        try:
            data = part.get_payload(decode=True) or b""
        except Exception:
            data = b""
        result.append({"name": part.get_filename() or "bez_nazwy", "size": len(data), "data": data,
                       "type": part.get_content_type()})
    return result


def parse(raw):
    msg = email.message_from_bytes(raw, policy=email.policy.default)

    def header(name):
        try:
            return str(msg.get(name, "") or "")
        except Exception:
            return ""

    from_name, from_addr = parseaddr(header("From"))
    reply = [a for _, a in getaddresses([header("Reply-To")]) if a]
    auth = header("Authentication-Results").lower()
    auth_summary = " ".join(sorted(set(re.findall(r"\b(?:dmarc|spf|dkim)=\w+", auth))))
    return {
        "msg": msg,
        "from_name": from_name.strip().strip('"'),
        "from_addr": from_addr.lower(),
        "reply_to": ", ".join(reply),
        "to": header("To"),
        "cc": header("Cc"),
        "subject": " ".join(header("Subject").split()),
        "date": header("Date"),
        "message_id": header("Message-ID").strip(),
        "references": " ".join(header("References").split()),
        "auth": auth_summary,
        "newsletter": bool(header("List-Unsubscribe") or header("List-Id")),
        "server_spam": (header("X-Spam-Flag").strip().lower() == "yes"
                        or header("X-Spam-Status").strip().lower().startswith("yes")
                        or header("X-Spam").strip().lower() in ("yes", "true")),
        "server_virus": bool(re.search(r"infected|virus found", header("X-Virus-Status") + header("X-Virus"),
                                       re.IGNORECASE)),
        "text": body_text(msg),
        "attachments": attachments(msg),
    }


def sender_matches(addr, patterns):
    addr = (addr or "").lower()
    domain = addr.rsplit("@", 1)[-1]
    for p in patterns or []:
        p = p.strip().lower()
        if not p:
            continue
        if "@" in p and not p.startswith("@"):
            if addr == p:
                return True
        else:
            d = p.lstrip("@")
            if domain == d or domain.endswith("." + d):
                return True
    return False


def speak_name(entry):
    name = entry.get("from_name") or entry.get("from_addr", "").split("@")[0]
    return re.sub(r"[<>\"@]", " ", name).strip() or "nieznanego nadawcy"


# ---------- dziennik (tylko metadane, krotko) ----------

def load_log():
    return read_json(LOG, [])


def _prune(log, cfg=None):
    days = ((cfg or {}).get("mail") or {}).get("log_days", DEFAULTS["log_days"])
    cutoff = time.time() - days * 86400
    return [e for e in log if e["at"] >= cutoff][-LOG_LIMIT:]


def add_entries(entries, cfg=None):
    with _log_lock:
        log = load_log()
        next_id = max((e["id"] for e in log), default=0) + 1
        for e in entries:
            e["id"] = next_id
            next_id += 1
        write_json(LOG, _prune(log + entries, cfg))
    return entries


def update_entry(entry_id, **changes):
    with _log_lock:
        log = load_log()
        for e in log:
            if e["id"] == entry_id:
                e.update(changes)
        write_json(LOG, log)


def get_entry(entry_id):
    for e in load_log():
        if e["id"] == int(entry_id):
            return e
    sys.exit(f"Nie ma wiadomosci o numerze {entry_id} (mail.py list pokazuje numery).")


def locate(client, entry):
    """Znajduje wiadomosc na serwerze: najpierw po Message-ID w folderze, gdzie trafila, potem w pozostalych."""
    names = [entry.get("folder") or "INBOX", "INBOX"] + [
        f for f in (entry.get("handling") or {}).values() if f not in ("keep", "delete")]
    seen = set()
    for name in names:
        folder = server_folder(client, name)
        if folder in seen or not client.folder_exists(folder):
            continue
        seen.add(folder)
        client.select_folder(folder)
        uids = client.search(["HEADER", "Message-ID", entry["message_id"]]) if entry.get("message_id") else []
        if not uids and folder == entry.get("folder") and entry.get("uid"):
            uids = client.search(["UID", str(entry["uid"])])
        if uids:
            return folder, uids[-1]
    return None, None


def fetch_entry(acct, entry):
    """(client, folder, uid, surowa tresc) - client zostaje zalogowany (wywolujacy robi logout)."""
    entry.setdefault("handling", acct["handling"])
    client = connect(acct)
    folder, uid = locate(client, entry)
    if not uid:
        client.logout()
        sys.exit("Nie znalazlam tej wiadomosci na serwerze (usunieta albo przeniesiona recznie).")
    raw = client.fetch([uid], ["BODY.PEEK[]"])[uid][b"BODY[]"]
    return client, folder, uid, raw


# ---------- raporty glosowe ----------

FORMS = {
    "pl": {"important": ("jeden ważny mail", "ważne maile", "ważnych maili"),
           "normal": ("jeden zwykły mail", "zwykłe maile", "zwykłych maili"),
           "ad": ("jedną reklamę", "reklamy", "reklam"),
           "spam": ("jeden spam", "spamy", "spamów"),
           "threat": ("jedną podejrzaną wiadomość", "podejrzane wiadomości", "podejrzanych wiadomości")},
    "en": {"important": ("one important e-mail", "important e-mails", "important e-mails"),
           "normal": ("one ordinary e-mail", "ordinary e-mails", "ordinary e-mails"),
           "ad": ("one ad", "ads", "ads"),
           "spam": ("one spam message", "spam messages", "spam messages"),
           "threat": ("one suspicious e-mail", "suspicious e-mails", "suspicious e-mails")},
}


def count_phrase(n, category, cfg):
    one, few, many = FORMS[lang(cfg)][category]
    if n == 1:
        return one
    if lang(cfg) == "pl" and 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} {few}"
    return f"{n} {many}"


def join_words(items, cfg):
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + (" i " if lang(cfg) == "pl" else " and ") + items[-1]


def cap(text):
    return text[:1].upper() + text[1:]


def report(entries, cfg, intro="", names=3, multi_account=False):
    """Raport do przeczytania na glos: wazne z nadawca i sednem, reszta jako liczby."""
    pl = lang(cfg) == "pl"
    by = {c: [e for e in entries if e["category"] == c] for c in CATEGORIES}
    parts = [intro] if intro else []

    def src(e):
        where = (f" na koncie {e['account']}" if pl else f" in {e['account']}") if multi_account else ""
        about = (e.get("summary") or e.get("subject") or "").rstrip(".")
        return f"{'od' if pl else 'from'} {speak_name(e)}{where}: {about}"

    imp = sorted(by["important"], key=lambda e: not e.get("unread", True))  # nieprzeczytane najpierw
    if len(imp) == 1:
        parts.append(("Ważny mail " if pl else "Important e-mail ") + src(imp[0]) + ".")
    elif imp:
        parts.append(cap(count_phrase(len(imp), "important", cfg)) + ".")
        parts += [cap(src(e)) + "." for e in imp[:names]]
        if len(imp) > names:
            parts.append(f"I jeszcze {len(imp) - names}." if pl else f"And {len(imp) - names} more.")
    removed = [count_phrase(len(by[c]), c, cfg) for c in ("ad", "spam") if by[c]]
    if removed:
        parts.append(("Usunęłam ze skrzynki " if pl else "I removed from the inbox ") + join_words(removed, cfg) + ".")
    if by["threat"]:
        t = by["threat"]
        detail = f", {src(t[0])}" if len(t) == 1 else ""
        parts.append(("Odizolowałam " if pl else "I quarantined ") + count_phrase(len(t), "threat", cfg) + detail + ".")
    if by["normal"]:
        parts.append(cap(count_phrase(len(by["normal"]), "normal", cfg))
                     + (" zostawiłam w skrzynce." if pl else " left in the inbox."))
    if len(parts) == (1 if intro else 0):
        parts.append("Nic nowego w poczcie." if pl else "Nothing new in the mail.")
    return " ".join(parts)


# ---------- wysylanie ----------

def smtp_send(acct, msg):
    security = acct.get("smtp_security") or ("ssl" if acct.get("security", "ssl") == "ssl" else "starttls")
    host = acct.get("smtp_host") or acct["host"]
    port = acct.get("smtp_port") or {"ssl": 465, "starttls": 587}.get(security, 25)
    user = acct.get("smtp_user") or acct["user"]
    password = acct.get("smtp_password") or acct["password"]
    if security == "ssl":
        server = smtplib.SMTP_SSL(host, port, context=tls_context(acct), timeout=60)
    else:
        server = smtplib.SMTP(host, port, timeout=60)
        if security == "starttls":
            server.starttls(context=tls_context(acct))
    try:
        if password and security != "none" or acct.get("smtp_auth"):
            server.login(user, password)
        server.send_message(msg)
    finally:
        server.quit()


def compose(acct, to, subject, text, cc=None, in_reply_to=None, references=None, quote=None):
    msg = EmailMessage()
    msg["From"] = formataddr((acct.get("display_name") or "", acct["address"]))
    msg["To"] = to
    if cc:
        msg["Cc"] = cc
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=acct["address"].rsplit("@", 1)[-1])
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = f"{references} {in_reply_to}".strip() if references else in_reply_to
    body = text.rstrip()
    if acct.get("signature"):
        body += "\n\n-- \n" + acct["signature"]
    if quote:
        body += "\n\n" + quote
    msg.set_content(body + "\n")
    return msg


def store_copy(client, msg, draft):
    """Kopia w Wyslanych (albo szkic w Szkicach) - zeby odpowiedz byla widoczna w programie pocztowym."""
    if draft:
        folder = special_folder(client, b"\\Drafts", ["Drafts", "Szkice", "INBOX.Drafts"])
        flags = [b"\\Draft", b"\\Seen"]
    else:
        folder = special_folder(client, b"\\Sent", ["Sent", "Wysłane", "Sent Items", "INBOX.Sent"])
        flags = [b"\\Seen"]
    client.append(folder, msg.as_bytes(), flags=flags)
    return folder


def deliver(acct, msg, draft, dry_run, client=None, answered=None):
    if dry_run:
        print("=== PODGLAD (nic nie wyslano) ===")
        print(msg.as_string()[:6000])
        return
    own = client is None
    if not draft:
        smtp_send(acct, msg)
    try:
        client = client or connect(acct)
        folder = store_copy(client, msg, draft)
        if answered and not draft:
            client.select_folder(answered[0])
            client.add_flags([answered[1]], [b"\\Answered"])
    except Exception as exc:
        folder = f"(nie zapisano kopii: {exc})"
    finally:
        if own and client:
            try:
                client.logout()
            except Exception:
                pass
    print(("Zapisano szkic" if draft else "Wyslano") + f" do: {msg['To']}" + (f", DW: {msg['Cc']}" if msg["Cc"] else "")
          + f" | temat: {msg['Subject']} | kopia: {folder}")


# ---------- polecenia ----------

def fmt_time(ts):
    return time.strftime("%d.%m %H:%M", time.localtime(ts))


def print_entry(e, cfg):
    extra = f" | {e['reason']}" if e.get("reason") else ""
    flags = (" [stara]" if e.get("backlog") else "") + ("" if e.get("unread", True) else " [przeczytana]")
    print(f"[{e['id']}] {fmt_time(e['at'])} {e['account']} | {label(e['category'], cfg).upper()}{flags} | "
          f"od: {e.get('from_name') or ''} <{e.get('from_addr')}> | {e.get('subject')}")
    if e.get("summary"):
        print(f"      {e['summary']}")
    print(f"      -> {e.get('folder')}{extra}")


def cmd_status(cfg):
    status = read_json(STATUS, {})
    running = status.get("pid") and pid_alive(status["pid"])
    mail = cfg.get("mail") or {}
    print(f"Nasluch poczty: {'DZIALA' if running else 'wylaczony'}"
          f"{' (od ' + fmt_time(status['started']) + ')' if running else ''}"
          f" | mail.enabled: {mail.get('enabled', False)}")
    accts = accounts(cfg, include_disabled=True)
    if not accts:
        print("Brak kont w config.json (mail.accounts).")
    for a in accts:
        s = (status.get("accounts") or {}).get(a["name"], {})
        line = f"- {a['name']} ({a['user']} @ {a['host']})"
        if not a.get("enabled", True):
            line += " [wylaczone]"
        elif running:
            line += f" stan: {s.get('state', '?')}"
            if s.get("backlog"):
                line += f", przeglad starej poczty: zostalo {s['backlog']}"
            if s.get("last_check"):
                line += f", sprawdzone {fmt_time(s['last_check'])}"
            if s.get("error"):
                line += f", BLAD: {s['error']}"
        print(line)
    log = [e for e in load_log() if e["at"] > time.time() - 86400]
    if log:
        counts = {}
        for e in log:
            counts[e["category"]] = counts.get(e["category"], 0) + 1
        print("Ostatnie 24 h: " + ", ".join(f"{label(c, cfg)}: {n}" for c, n in counts.items()))


def cmd_summary(cfg, args):
    since = time.time() - args.hours * 3600
    entries = [e for e in load_log() if e["at"] >= since and (args.backlog or not e.get("backlog"))]
    print(report(entries, cfg, multi_account=len(accounts(cfg)) > 1, names=5))


def cmd_list(cfg, args):
    since = time.time() - args.hours * 3600
    rows = [e for e in load_log() if e["at"] >= since
            and (not args.category or e["category"] == args.category)
            and (not args.account or e["account"].lower() == args.account.lower())
            and (args.all or args.category or e["category"] != "normal")]
    if not rows:
        print("Brak wiadomosci w tym okresie." + ("" if args.all else " (zwykle ukryte - dodaj --all)"))
    for e in rows:
        print_entry(e, cfg)


def cmd_show(cfg, args):
    entry = get_entry(args.id)
    acct = find_account(cfg, entry["account"])
    client, folder, _, raw = fetch_entry(acct, entry)
    client.logout()
    m = parse(raw)
    print(f"Folder: {folder}")
    print(f"Od: {m['from_name']} <{m['from_addr']}>" + (f" | Odpowiedz do: {m['reply_to']}" if m["reply_to"] else ""))
    print(f"Do: {m['to']}" + (f" | DW: {m['cc']}" if m["cc"] else ""))
    print(f"Data: {m['date']}\nTemat: {m['subject']}")
    if m["auth"]:
        print(f"Uwierzytelnienie: {m['auth']}")
    if m["attachments"]:
        print("Zalaczniki: " + ", ".join(f"{a['name']} ({a['size'] // 1024} KB)" for a in m["attachments"]))
    print("\n" + (m["text"][:8000] or "(brak tresci tekstowej)"))


def cmd_move(cfg, args):
    entry = get_entry(args.id)
    acct = find_account(cfg, entry["account"])
    entry.setdefault("handling", acct["handling"])
    target_cat = args.target.lower()
    if target_cat == "inbox":
        target, category = acct["folder"], "normal"
    elif target_cat in CATEGORIES:
        target, category = acct["handling"].get(target_cat, "keep"), target_cat
        if target == "keep":
            target = acct["folder"]
    else:
        sys.exit(f"Nieznany cel '{args.target}'. Dostepne: inbox, {', '.join(CATEGORIES)}.")
    client = connect(acct)
    try:
        folder, uid = locate(client, entry)
        if not uid:
            sys.exit("Nie znalazlam tej wiadomosci na serwerze (juz usunieta).")
        dest = server_folder(client, target) if target != "delete" else "usunieta"
        if dest != folder:
            move(client, [uid], target)
    finally:
        client.logout()
    update_entry(entry["id"], category=category, folder=dest, reason="poprawione przez uzytkownika")
    print(f"Wiadomosc [{entry['id']}] -> {dest} (kategoria: {label(category, cfg)}).")


def cmd_rescan(cfg, args):
    names = [find_account(cfg, args.account)["name"]] if args.account else [a["name"] for a in accounts(cfg)]
    requests = read_json(RESCAN, {})
    for n in names:
        requests[n] = {"all": args.all, "days": args.days}
    write_json(RESCAN, requests)
    running = read_json(STATUS, {}).get("pid") and pid_alive(read_json(STATUS, {})["pid"])
    scope = "cala skrzynka" if args.all else (f"nieprzeczytane + ostatnie {args.days} dni" if args.days is not None
                                              else "nieprzeczytane + okres z scan_existing_days")
    print(f"Zlecono przeglad ({scope}): {', '.join(names)}. "
          + ("Nasluch zacznie w ciagu minuty." if running else "Nasluch nie dziala - przeglad ruszy po starcie."))


def read_text_file(path):
    with open(path, encoding="utf-8-sig") as f:
        text = f.read().strip()
    if not text:
        sys.exit("Plik z trescia jest pusty.")
    return text


def cmd_reply(cfg, args):
    entry = get_entry(args.id)
    acct = find_account(cfg, entry["account"])
    text = read_text_file(args.text_file)
    client, folder, uid, raw = fetch_entry(acct, entry)
    try:
        m = parse(raw)
        to = m["reply_to"] or formataddr((m["from_name"], m["from_addr"]))
        cc = None
        if args.all:
            me = acct["address"].lower()
            others = [formataddr((n, a)) for n, a in getaddresses([m["to"], m["cc"]])
                      if a and a.lower() not in (me, m["from_addr"])]
            cc = ", ".join(others) or None
        subject = m["subject"] if re.match(r"(?i)^(re|odp|aw):", m["subject"]) else f"Re: {m['subject']}"
        wrote = "napisał(a)" if lang(cfg) == "pl" else "wrote"
        quoted = "\n".join("> " + line for line in m["text"].splitlines()[:80])
        quote = f"{m['date']}, {m['from_name'] or m['from_addr']} {wrote}:\n{quoted}"
        msg = compose(acct, to, subject, text, cc=cc, in_reply_to=m["message_id"] or None,
                      references=m["references"], quote=quote)
        deliver(acct, msg, args.draft, args.dry_run, client=client, answered=(folder, uid))
    finally:
        client.logout()


def cmd_send(cfg, args):
    acct = find_account(cfg, args.account)
    msg = compose(acct, args.to, args.subject, read_text_file(args.text_file))
    deliver(acct, msg, args.draft, args.dry_run)


def cmd_test(cfg):
    accts = accounts(cfg, include_disabled=True)
    if not accts:
        sys.exit("Brak kont w config.json (mail.accounts).")
    for a in accts:
        try:
            client = connect(a)
            caps = {_text(c) for c in client.capabilities()}
            info = client.select_folder(server_folder(client, a["folder"]), readonly=True)
            unseen = len(client.search("UNSEEN"))
            print(f"OK   {a['name']}: {info.get(b'EXISTS')} wiadomosci w {a['folder']} (nieprzeczytane: {unseen}) | "
                  f"IDLE: {'tak' if 'IDLE' in caps else 'nie (odpytywanie co ' + str(a['poll_seconds']) + ' s)'} | "
                  f"MOVE: {'tak' if 'MOVE' in caps else 'nie'} | "
                  f"foldery Achai: {', '.join(server_folder(client, f) for f in set(a['handling'].values()) if f not in ('keep', 'delete')) or '-'}")
            client.logout()
        except Exception as exc:
            print(f"BLAD {a['name']} (IMAP): {type(exc).__name__}: {exc}")
        try:
            security = a.get("smtp_security") or ("ssl" if a.get("security", "ssl") == "ssl" else "starttls")
            host = a.get("smtp_host") or a["host"]
            port = a.get("smtp_port") or {"ssl": 465, "starttls": 587}.get(security, 25)
            if security == "ssl":
                s = smtplib.SMTP_SSL(host, port, context=tls_context(a), timeout=20)
            else:
                s = smtplib.SMTP(host, port, timeout=20)
                if security == "starttls":
                    s.starttls(context=tls_context(a))
            if security != "none" or a.get("smtp_auth"):
                s.login(a.get("smtp_user") or a["user"], a.get("smtp_password") or a["password"])
            s.quit()
            print(f"OK   {a['name']}: wysylanie (SMTP {host}:{port}, {security})")
        except Exception as exc:
            print(f"BLAD {a['name']} (SMTP - odpisywanie nie zadziala): {type(exc).__name__}: {exc}")


def watcher_pid():
    pid = read_json(STATUS, {}).get("pid")
    return pid if pid and pid_alive(pid) else None


def cmd_start():
    if watcher_pid():
        print("Nasluch poczty juz dziala.")
        return
    subprocess.Popen([str(PYTHONW), str(SCRIPTS / "mail_watch.py")], cwd=str(SCRIPTS),
                     creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW, close_fds=True)
    time.sleep(3)
    print("Uruchomiono nasluch poczty." if watcher_pid() else
          "Nasluch nie wystartowal - sprawdz state\\mail\\watch.log i mail.enabled w config.json.")


def cmd_stop():
    pid = watcher_pid()
    if not pid:
        print("Nasluch poczty nie dziala.")
        return
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    print("Zatrzymano nasluch poczty.")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for c in ("status", "test", "start", "stop", "restart"):
        sub.add_parser(c)
    p = sub.add_parser("summary")
    p.add_argument("--hours", type=float, default=24)
    p.add_argument("--backlog", action="store_true", help="wlicz przeglad starej poczty")
    p = sub.add_parser("list")
    p.add_argument("--category", choices=CATEGORIES)
    p.add_argument("--hours", type=float, default=24)
    p.add_argument("--account")
    p.add_argument("--all", action="store_true")
    sub.add_parser("show").add_argument("id", type=int)
    p = sub.add_parser("move")
    p.add_argument("id", type=int)
    p.add_argument("target")
    p = sub.add_parser("rescan")
    p.add_argument("--account")
    p.add_argument("--days", type=int)
    p.add_argument("--all", action="store_true")
    p = sub.add_parser("reply")
    p.add_argument("id", type=int)
    p.add_argument("--text-file", required=True)
    p.add_argument("--all", action="store_true", help="odpowiedz wszystkim")
    p.add_argument("--draft", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("send")
    p.add_argument("--account", required=True)
    p.add_argument("--to", required=True)
    p.add_argument("--subject", required=True)
    p.add_argument("--text-file", required=True)
    p.add_argument("--draft", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    cfg = load_config()

    commands = {"status": lambda: cmd_status(cfg), "summary": lambda: cmd_summary(cfg, args),
                "list": lambda: cmd_list(cfg, args), "show": lambda: cmd_show(cfg, args),
                "move": lambda: cmd_move(cfg, args), "rescan": lambda: cmd_rescan(cfg, args),
                "reply": lambda: cmd_reply(cfg, args), "send": lambda: cmd_send(cfg, args),
                "test": lambda: cmd_test(cfg), "start": cmd_start, "stop": cmd_stop}
    if args.cmd == "restart":
        cmd_stop()
        time.sleep(1)
        cmd_start()
    else:
        commands[args.cmd]()


if __name__ == "__main__":
    main()
