"""Okno podgladu pracy agenta: pokazuje log na zywo, zamyka sie po czasie od zakonczenia."""
import ctypes
import sys
import time

from common import ROOT  # noqa: F401  (ustawia UTF-8 na stdout)

log_path, name, close_after = sys.argv[1], sys.argv[2], int(sys.argv[3])
ctypes.windll.kernel32.SetConsoleTitleW(f"Agent: {name}")

with open(log_path, encoding="utf-8") as f:
    while True:
        line = f.readline()
        if not line:
            time.sleep(0.3)
            continue
        print(line, end="", flush=True)
        if line.startswith("=== KONIEC ==="):
            break

print(f"\nOkno zamknie sie za {close_after // 60} min (albo zamknij je teraz).", flush=True)
time.sleep(close_after)
