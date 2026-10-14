"""Wstrzykuje nacisniecia klawiszy do konsoli innego procesu (bez fokusu okna).

Uzycie: inject.py <pid> <klawisz> [<klawisz> ...]
Klawisze: space, enter, esc, ctrl+u, backspace, albo text:<dowolny tekst>

Proces wolajacy nie moze byc podlaczony do tej samej konsoli co cel,
dlatego nasluch w oknie konsoli uruchamia ten skrypt jako osobny proces (bez okna).
Aplikacja okienkowa (app.py) robi to samo w swoim procesie - patrz console.py.
"""
import sys

from console import write_keys

if __name__ == "__main__":
    write_keys(int(sys.argv[1]), sys.argv[2:])
