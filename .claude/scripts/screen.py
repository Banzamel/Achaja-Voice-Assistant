"""Odczytuje widoczny tekst z konsoli innego procesu (bez fokusu okna).

Uzycie: screen.py <pid>  -> wypisuje widoczne linie okna konsoli

Jak inject.py: proces wolajacy nie moze byc podlaczony do tej samej konsoli co cel,
dlatego nasluch w oknie konsoli uruchamia ten skrypt jako osobny proces (bez okna).
"""
import sys

from console import read_screen

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("\n".join(read_screen(int(sys.argv[1]))))
