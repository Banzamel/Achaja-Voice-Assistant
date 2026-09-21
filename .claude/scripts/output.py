"""Wybor wyjscia glosu Achai.

Uzycie:
  output.py                      pokazuje aktualne wyjscie i dostepne
  output.py set <nazwa>          przelacza na stale (np. glosnik, sluchawki)
  output.py set <nazwa> --once   tylko nastepna wypowiedz, potem powrot do domyslnego
  output.py reset                powrot do domyslnego (config.json: voice.default_output)
  output.py discover             szuka glosnikow Google Cast w sieci
"""
import sys
import unicodedata

from audio_out import OUTPUT_FILE, current_output, outputs
from common import write_json


def fold(s):
    """Porownanie bez polskich znakow: 'glosnik' == 'głośnik' ('ł' nie rozklada sie w NFKD)."""
    s = s.lower().replace("ł", "l")
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def main():
    outs, default = outputs()
    args = sys.argv[1:]
    if not args:
        print(f"Aktualne wyjscie: {current_output()} (domyslne: {default})")
        for name, out in outs.items():
            print(f"  {name}: {out}")
    elif args[0] == "set":
        wanted = fold(args[1])
        name = next((n for n in outs if fold(n) == wanted or wanted in fold(n)
                     or wanted in fold(outs[n].get("name", ""))
                     or any(fold(a) == wanted or wanted in fold(a) for a in outs[n].get("aliases", []))), None)
        if not name:
            sys.exit(f"Nie ma wyjscia '{args[1]}'. Dostepne: {', '.join(outs)}")
        write_json(OUTPUT_FILE, {"output": name, "once": "--once" in args})
        print(f"Wyjscie glosu: {name}{' (tylko nastepna wypowiedz)' if '--once' in args else ''}")
    elif args[0] == "reset":
        OUTPUT_FILE.unlink(missing_ok=True)
        print(f"Wyjscie glosu: {default} (domyslne)")
    elif args[0] == "discover":
        import pychromecast
        casts, browser = pychromecast.get_chromecasts(timeout=8)
        for c in casts:
            ci = c.cast_info
            print(f"{ci.friendly_name} | {ci.model_name} | {ci.host} | {ci.cast_type}")
        browser.stop_discovery()


if __name__ == "__main__":
    main()
