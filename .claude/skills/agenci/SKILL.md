---
name: agenci
description: Stan agentów projektów — kto teraz pracuje, ostatnie wyniki, pełny raport agenta, przerwanie pracy agenta, lista projektów. Używaj, gdy użytkownik pyta „co robią agenci”, „co zrobił agent X”, „przerwij agenta”, „jakie mam projekty”.
---

# Stan agentów

Python: `& ".venv\Scripts\python.exe" ".claude\scripts\agent.py" <komenda>`

| Pytanie użytkownika | Komenda |
|---|---|
| Kto pracuje / co się dzieje | `status` |
| Co zrobił agent X | `last <projekt>` |
| Przerwij agenta X | `stop <projekt>` (akcja odwracalna tylko częściowo — potwierdź, jeśli agent jest w połowie zmian) |
| Jakie mam projekty | `list` |

Postęp na żywo pracującego agenta: `state\agents\<projekt>.log` (czytaj końcówkę pliku).

Odpowiedź głosowa: krótko — ilu agentów pracuje i nad czym, albo najważniejszy efekt ostatniego wyniku.
