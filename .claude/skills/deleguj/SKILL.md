---
name: deleguj
description: Zleca zadanie agentowi innego projektu (osobny proces claude w folderze projektu, z jego własnym .claude) i relacjonuje wynik. Używaj, gdy użytkownik chce, by coś zrobiono w projekcie X, zapytać agenta projektu, kontynuować pracę agenta lub uruchomić agenta do pracy nad projektem.
---

# Delegowanie zadania agentowi projektu

Python: `& ".venv\Scripts\python.exe" ".claude\scripts\agent.py" ...`

## 1. Ustal projekt
Jeśli nazwa jest niepewna (dyktowanie przekręca nazwy), sprawdź listę:
```powershell
& ".venv\Scripts\python.exe" ".claude\scripts\agent.py" list
```
`agent.py` sam dopasowuje nazwy rozmyte i aliasy z `config.json`. Gdy dwa projekty pasują równie dobrze — zapytaj głosowo.

## 2. Przygotuj zlecenie
Przepisz dyktowane polecenie na **jasne, kompletne zlecenie** dla agenta (agent nie zna Twojej rozmowy z użytkownikiem): cel, kontekst z rozmowy, oczekiwany rezultat, ograniczenia. Zapisz je do pliku narzędziem Write, np. `state\agents\zlecenie-<projekt>.txt` — omija to problemy z cudzysłowami i polskimi znakami w wierszu poleceń.

## 3. Uruchom agenta W TLE
Wywołaj narzędziem PowerShell z `run_in_background: true`:
```powershell
& ".venv\Scripts\python.exe" ".claude\scripts\agent.py" run <projekt> --prompt-file "state\agents\zlecenie-<projekt>.txt"
```
- Dodaj `--new`, gdy użytkownik chce zacząć z agentem od zera; bez tego agent kontynuuje poprzednią rozmowę w tym projekcie.
- Skrypt otwiera okno „Agent: <projekt>” z postępem na żywo, a na końcu wypisuje raport.
- Jeśli agent tego projektu już pracuje, skrypt odmówi — powiedz o tym użytkownikowi.

Od razu odpowiedz krótko, np. `[GŁOS] Zleciłam agentowi projektu vision poprawę formularza. Dam znać, gdy skończy.`

## 4. Gdy zadanie w tle się zakończy
Przeczytaj wynik (wyjście zadania albo `agent.py last <projekt>`) i zrelacjonuj:
- tekst: pełne podsumowanie agenta, zmienione pliki, wyniki testów, zablokowane akcje, pytania;
- `[GŁOS]`: czy się udało, najważniejszy efekt w 1–2 zdaniach, oraz pytania agenta do użytkownika.

Jeśli wynik zawiera „Zablokowane akcje” — zapytaj głosowo, czy je wykonać. Po zgodzie zleć to agentowi ponownie (kontynuacja rozmowy), wyraźnie pisząc, że użytkownik zatwierdził konkretną akcję.

## 5. Dalsza rozmowa z agentem
„Powiedz agentowi od X, żeby…” → kolejny `run X` bez `--new` (agent pamięta kontekst).
