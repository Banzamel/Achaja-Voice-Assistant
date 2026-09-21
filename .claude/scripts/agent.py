"""Agenci projektow: uruchamia Claude w folderze projektu (z jego wlasnym .claude),
pokazuje postep w osobnym oknie i zwraca wynik Achai.

Uzycie:
  agent.py list                                   projekty i aliasy
  agent.py run <projekt> --prompt "tekst" [--new]  zleca zadanie (czeka na wynik)
  agent.py run <projekt> --prompt-file plik [--new]
  agent.py status                                 kto pracuje, ostatnie wyniki
  agent.py last <projekt>                         pelny ostatni wynik agenta
  agent.py stop <projekt>                         przerywa prace agenta

Kolejne zlecenia do tego samego projektu kontynuuja jego rozmowe (--resume),
chyba ze podasz --new.
"""
import argparse
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from common import (AGENTS_STATE, CREATE_NEW_CONSOLE, CREATE_NO_WINDOW, PYTHON, SCRIPTS, clean_env,
                    load_config, pid_alive, read_json, write_json)

SESSIONS = AGENTS_STATE / "sessions.json"
RUNNING = AGENTS_STATE / "running.json"

AGENT_PROMPT = """Pracujesz jako agent projektu "{name}" na zlecenie Achai - glosowego koordynatora \
uzytkownika. Uzytkownik jest z dala od komputera i NIE odpowie na pytania w trakcie Twojej pracy.
- Wykonaj zadanie samodzielnie, zgodnie z zasadami tego projektu (jego CLAUDE.md, skille, ustawienia).
- Akcji ryzykownych (git push, deploy, produkcja, usuwanie danych, migracje na bazie, wydatki) NIE wykonuj - \
opisz je jako propozycje w podsumowaniu.
- Gdy brakuje decyzji, wybierz rozsadne domyslne rozwiazanie, jesli jest odwracalne; w przeciwnym razie zapytaj w podsumowaniu.
- Zakoncz odpowiedz sekcja "PODSUMOWANIE" po polsku: co zrobiono, zmienione pliki, wyniki testow/buildow, \
problemy, oraz "PYTANIA" do uzytkownika (jesli sa)."""


def norm(s):
    s = s.lower()
    s = re.sub(r"^(project|work)[-_ ]", "", s)
    return re.sub(r"[-_ ]", "", s)


def all_projects(cfg):
    projects = {}
    for root in cfg["agents"]["project_roots"]:
        root = Path(root)
        if root.is_dir():
            for d in sorted(root.iterdir()):
                if d.is_dir() and not d.name.startswith("."):
                    projects[d.name] = d
    return projects


def resolve(query, cfg):
    projects = all_projects(cfg)
    aliases = {k.lower(): v for k, v in cfg["agents"].get("aliases", {}).items()}
    q = query.strip().lower()
    if q in aliases and aliases[q] in projects:
        return aliases[q], projects[aliases[q]]
    by_norm = {norm(n): n for n in projects}
    if query in projects:
        return query, projects[query]
    if norm(q) in by_norm:
        n = by_norm[norm(q)]
        return n, projects[n]
    subs = [n for k, n in by_norm.items() if norm(q) and (norm(q) in k or k in norm(q))]
    if len(subs) == 1:
        return subs[0], projects[subs[0]]
    close = difflib.get_close_matches(norm(q), list(by_norm) + list(aliases), n=1, cutoff=0.6)
    if close:
        n = by_norm.get(close[0]) or aliases.get(close[0])
        if n in projects:
            return n, projects[n]
    sys.exit(f"Nie rozpoznano projektu '{query}'. Dostepne: {', '.join(projects)}")


def short(value, limit=160):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit] + "..."


def describe_tool(block):
    inp = block.get("input", {})
    for key in ("command", "file_path", "pattern", "path", "url", "description", "prompt"):
        if key in inp:
            return f"{block.get('name')}: {short(inp[key])}"
    return f"{block.get('name')}: {short(inp)}"


def cmd_run(args, cfg):
    name, path = resolve(args.project, cfg)
    prompt = args.prompt
    if args.prompt_file:
        prompt = Path(args.prompt_file).read_text(encoding="utf-8")
    if not prompt:
        sys.exit("Brak tresci zlecenia (--prompt lub --prompt-file).")

    running = read_json(RUNNING, {})
    if name in running and pid_alive(running[name]["pid"]):
        sys.exit(f"Agent projektu {name} juz pracuje (PID {running[name]['pid']}). "
                 f"Poczekaj na wynik albo uzyj: agent.py stop {name}")

    sessions = read_json(SESSIONS, {})
    claude = shutil.which("claude")
    cmd = [claude, "-p", "--output-format", "stream-json", "--verbose",
           "--permission-mode", cfg["agents"].get("permission_mode", "auto"),
           "--append-system-prompt", AGENT_PROMPT.format(name=name)]
    resumed = name in sessions and not args.new
    if resumed:
        cmd += ["--resume", sessions[name]]

    log_path = AGENTS_STATE / f"{name}.log"
    log = open(log_path, "w", encoding="utf-8")

    def out(line):
        log.write(line + "\n")
        log.flush()

    out(f"=== Agent projektu {name} ({path}) ===")
    out(f"Start: {time.strftime('%Y-%m-%d %H:%M:%S')}  |  {'kontynuacja rozmowy' if resumed else 'nowa rozmowa'}")
    out(f"Zlecenie: {prompt}\n")

    viewer = subprocess.Popen([str(PYTHON), str(SCRIPTS / "agent_view.py"), str(log_path), name,
                               str(cfg["agents"].get("close_window_after_seconds", 300))],
                              creationflags=CREATE_NEW_CONSOLE)

    proc = subprocess.Popen(cmd, cwd=str(path), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, creationflags=CREATE_NO_WINDOW,
                            env=clean_env())
    running[name] = {"pid": proc.pid, "started": time.time(), "prompt": prompt[:300]}
    write_json(RUNNING, running)
    proc.stdin.write(prompt.encode("utf-8"))
    proc.stdin.close()

    result = None
    for raw in proc.stdout:
        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            out(f"  {line}")
            continue
        kind = msg.get("type")
        if kind == "system" and msg.get("subtype") == "init":
            sessions[name] = msg.get("session_id")
            write_json(SESSIONS, sessions)
        elif kind == "assistant":
            for block in msg.get("message", {}).get("content", []):
                if block.get("type") == "text" and block.get("text", "").strip():
                    out(f"\n[agent] {block['text'].strip()}\n")
                elif block.get("type") == "tool_use":
                    out(f"  > {describe_tool(block)}")
        elif kind == "result":
            result = msg
    proc.wait()

    running = read_json(RUNNING, {})
    running.pop(name, None)
    write_json(RUNNING, running)

    if result is None:
        text = f"Agent projektu {name} zakonczyl sie bez wyniku (kod {proc.returncode}). Log: {log_path}"
        out(text)
        out("=== KONIEC ===")
        print(text)
        return 1

    if result.get("session_id"):
        sessions[name] = result["session_id"]
        write_json(SESSIONS, sessions)

    denials = result.get("permission_denials") or []
    meta = (f"projekt: {name} | czas: {round(result.get('duration_ms', 0) / 1000)} s | "
            f"tury: {result.get('num_turns')} | blad: {result.get('is_error')} | "
            f"koszt: {result.get('total_cost_usd', 0):.2f} USD")
    report = [f"# Wynik agenta projektu {name}", meta, "", result.get("result") or "(brak tekstu)"]
    if denials:
        report += ["", "## Zablokowane akcje (wymagaja zgody uzytkownika)"]
        report += [f"- {d.get('tool_name')}: {short(d.get('tool_input', {}), 300)}" for d in denials]
    report_text = "\n".join(report)
    (AGENTS_STATE / f"{name}-last.md").write_text(report_text, encoding="utf-8")

    out("\n" + report_text)
    out("=== KONIEC ===")
    log.close()
    print(report_text)
    return 0


def cmd_list(cfg):
    aliases = cfg["agents"].get("aliases", {})
    sessions = read_json(SESSIONS, {})
    for name, path in all_projects(cfg).items():
        al = [a for a, t in aliases.items() if t == name]
        has_claude = (path / ".claude").is_dir() or (path / "CLAUDE.md").exists()
        print(f"{name:25} aliasy: {', '.join(al) or '-':25} .claude: {'tak' if has_claude else 'nie':4}"
              f" rozmowa: {'tak' if name in sessions else 'nie'}")


def cmd_status():
    running = read_json(RUNNING, {})
    alive = {n: r for n, r in running.items() if pid_alive(r["pid"])}
    if alive:
        for n, r in alive.items():
            print(f"PRACUJE: {n} od {round((time.time() - r['started']) / 60)} min - {r['prompt'][:120]}")
    else:
        print("Zaden agent teraz nie pracuje.")
    lasts = sorted(AGENTS_STATE.glob("*-last.md"), key=os.path.getmtime, reverse=True)[:5]
    for f in lasts:
        print(f"Ostatni wynik: {f.stem[:-5]} ({time.strftime('%H:%M %d.%m', time.localtime(f.stat().st_mtime))})")


def cmd_stop(args, cfg):
    name, _ = resolve(args.project, cfg)
    running = read_json(RUNNING, {})
    if name not in running or not pid_alive(running[name]["pid"]):
        print(f"Agent {name} nie pracuje.")
        return
    subprocess.run(["taskkill", "/PID", str(running[name]["pid"]), "/T", "/F"], capture_output=True)
    print(f"Przerwano agenta {name}.")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    sub.add_parser("status")
    r = sub.add_parser("run")
    r.add_argument("project")
    r.add_argument("--prompt")
    r.add_argument("--prompt-file")
    r.add_argument("--new", action="store_true")
    for c in ("last", "stop"):
        sub.add_parser(c).add_argument("project")
    args = ap.parse_args()
    cfg = load_config()

    if args.cmd == "list":
        cmd_list(cfg)
    elif args.cmd == "status":
        cmd_status()
    elif args.cmd == "run":
        sys.exit(cmd_run(args, cfg))
    elif args.cmd == "last":
        name, _ = resolve(args.project, cfg)
        f = AGENTS_STATE / f"{name}-last.md"
        print(f.read_text(encoding="utf-8") if f.exists() else f"Brak wynikow dla {name}.")
    elif args.cmd == "stop":
        cmd_stop(args, cfg)


if __name__ == "__main__":
    main()
