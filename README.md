# Achaja — steruj Claude Code głosem

**Achaja** zamienia [Claude Code](https://claude.com/claude-code) w asystenta głosowego, który działa bez klawiatury. Mówisz słowo wybudzenia, dyktujesz polecenie, kończysz słowem „wykonaj” — prompt wysyła się sam, a odpowiedź słyszysz w słuchawkach lub na głośniku. Achaja wykonuje polecenia na komputerze, **zleca pracę agentom Twoich projektów** i potrafi sterować domem przez Home Assistant.

> **English summary:** Achaja turns Claude Code into a hands-free voice assistant on Windows. A small offline model (Vosk) listens only for control words; the prompt itself is transcribed by Claude Code's built-in dictation, so quality stays high. Answers are spoken back (edge-tts) through your headphones or a Google Cast speaker. Achaja can also delegate work to per-project Claude agents (each running in its own project folder with its own `CLAUDE.md`), control Home Assistant devices over MCP, and drive an Android TV over ADB. The assistant's prompts and docs are in Polish, but wake words, voices and rules are configurable for any language supported by Claude Code dictation and edge-tts.

---

## Jak to działa

```
[mikrofon] --- nasłuch słowa wybudzenia (Vosk, offline, tylko słowa kluczowe)
     │
     ├─► naciska spację w oknie Claude Code  → dyktowanie Claude zapisuje prompt
     │
     └─► po słowie „wykonaj” naciska spację ponownie → prompt wysyła się sam
                     │
                     ▼
        Claude Code (sesja „Achaja”)
         ├─ wykonuje polecenia na komputerze
         ├─ zleca zadania agentom projektów (osobne sesje claude)
         └─ steruje domem (Home Assistant przez MCP), telewizorem (ADB)
                     │
                     ▼
        hook Stop → sekcja [GŁOS] z odpowiedzi → mowa (edge-tts)
                     → słuchawki albo głośnik Google Cast
```

Kluczowa decyzja projektowa: **treść promptu rozpoznaje Claude Code**, a nie lokalny model. Mały model offline wychwytuje wyłącznie kilka słów sterujących, dzięki czemu jakość dyktowania pozostaje taka, jak w Claude Code, a nasłuch nie wysyła niczego do sieci.

Klawisze trafiają wprost do bufora konsoli Claude Code (`WriteConsoleInputW`), więc **okno nie musi mieć fokusu** — możesz pracować na komputerze w trakcie.

## Funkcje

- **Sterowanie głosem bez rąk** — słowo wybudzenia, dyktowanie, słowo końcowe, automatyczne wysłanie.
- **Odpowiedź głosowa** — Claude kończy każdą odpowiedź krótkim podsumowaniem w sekcji `[GŁOS]`, które jest czytane na głos.
- **Tryb rozmowy** — gdy odpowiedź kończy się pytaniem, nagrywanie Twojej odpowiedzi włącza się samo.
- **Potwierdzenia** — „Już sprawdzam” zaraz po wysłaniu i „Nadal pracuję” przy dłuższych zadaniach.
- **Agenci projektów** — „niech agent od <projekt> zrobi…” uruchamia osobną sesję Claude Code **w folderze tego projektu** (z jego `CLAUDE.md`, skillami i ustawieniami), pokazuje postęp w osobnym oknie i zwraca raport, który Achaja streszcza głosem.
- **Wyjścia audio** — słuchawki albo głośnik Google Cast / Google Home („odpowiadaj przez głośnik”).
- **Dom (opcjonalnie)** — Home Assistant przez oficjalną integrację MCP: światła, klimatyzacja, rolety, multimedia, stan domu.
- **Telewizor (opcjonalnie)** — Android TV przez ADB: włączanie, uruchamianie aplikacji, Netflix z konkretnym tytułem, klawisze pilota, zrzut ekranu.
- **Narzędzie audio dla Windows** — przypisanie mikrofonu lub głośnika do jednego programu (np. `claude.exe`) bez zmiany urządzeń domyślnych w systemie.

## Wymagania

- **Windows 10/11** (mechanizm wpisywania klawiszy korzysta z API konsoli Windows).
- **[Claude Code](https://claude.com/claude-code)** zalogowany **kontem claude.ai** — dyktowanie nie działa z kluczem API ani przez Bedrock/Vertex.
- **Python 3.11+** (instalator tworzy własne `.venv` w folderze projektu).
- **Mikrofon** i wyjście audio; dla mowy syntetycznej połączenie z internetem (edge-tts).
- Opcjonalnie: Home Assistant 2025.2+ (integracja „Model Context Protocol Server”), telewizor z Androidem, głośnik Google Cast.

## Instalacja

```powershell
git clone https://github.com/Banzamel/Achaja-Voice-Assistant.git
cd Achaja-Voice-Assistant
powershell -ExecutionPolicy Bypass -File install.ps1        # + opcje: -WithAdb -Autostart
```

Instalator tworzy `.venv`, instaluje biblioteki, pobiera model mowy (Vosk PL, ~50 MB), tworzy `config.json` z szablonu i generuje `.claude/settings.json` z hookami. Opcje: `-Autostart` (uruchamianie po zalogowaniu), `-WithAdb` (narzędzia Android do sterowania TV), `-SkipModel`.

Następnie:

1. Otwórz `config.json` i ustaw przynajmniej `wake.microphone` oraz `agents.project_roots` (foldery z Twoimi projektami).
2. Sprawdź nazwy urządzeń audio: `.venv\Scripts\python.exe .claude\scripts\listener.py --devices`.
3. Uruchom `start-achaja.cmd`. Otworzą się dwa okna: nasłuch i sesja Claude Code „Achaja”.

**Inne imię asystentki lub inny język?** W `config.json` zmień `wake.phrases` (frazy wybudzenia), `wake.end` / `cancel` / `clear`, `voice.tts_voice` (głos edge-tts) oraz język odpowiedzi w `.claude/settings.json` (`"language"`). Model Vosk zna tylko słowa ze swojego słownika — dla nietypowego imienia dobierz frazę brzmiącą podobnie (dla „Achaja” działa `aha ja`). Modele dla innych języków: [alphacephei.com/vosk/models](https://alphacephei.com/vosk/models).

## Użycie

| Mówisz | Co się dzieje |
|---|---|
| **„Achaja”** → *piknięcie* | Claude Code zaczyna nagrywać prompt |
| treść polecenia… **„wykonaj”** + chwila ciszy | prompt wysłany; Achaja potwierdza: „Już sprawdzam” |
| **„anuluj”** | nagranie odrzucone |
| **„nowa rozmowa”** | czysty kontekst (`/clear`) |
| „Achaja”, gdy Achaja mówi | przerywa mowę i zaczyna nagrywanie |
| pytanie od Achai | nagrywanie odpowiedzi włącza się samo (tryb rozmowy) |

Przykłady poleceń:

- „uruchom kalkulator i dodaj pierwiastek z dwóch i z trzech”
- „sprawdź w internecie, ile kosztuje…”
- „niech agent od **vision** sprawdzi, czemu nie działa logowanie”
- „co robią agenci?”, „co zrobił agent od taxi?”, „przerwij agenta vision”
- „odpowiadaj przez głośnik”, „wróć na słuchawki”
- „włącz światło w gabinecie”, „ustaw klimatyzację na 22 stopnie” (Home Assistant)

## Agenci projektów

```
Achaja ──► agent.py run <projekt> ──► claude -p  (cwd = folder projektu)
                                        │  własny .claude/CLAUDE.md, skille, uprawnienia
                                        ├─ okno „Agent: <projekt>” z postępem na żywo
                                        └─ raport → Achaja streszcza głosem
```

- Nazwy projektów dopasowywane są rozmyto (dyktowanie je przekręca) plus aliasy z `config.json`.
- Każdy projekt ma własną, ciągłą rozmowę (`--resume`); `--new` zaczyna od zera.
- Agenci działają w trybie uprawnień `auto`; akcje ryzykowne są blokowane i wracają do Ciebie jako pytanie.
- Polecenia: `run`, `status`, `last <projekt>`, `stop <projekt>`, `list`.

## Home Assistant (opcjonalnie)

1. W HA dodaj integrację **Model Context Protocol Server** (sterowanie: Assist).
2. Utwórz token długoterminowy i zapisz go w `state/ha_token.txt` (plik jest w `.gitignore`).
3. Skopiuj `.mcp.example.json` → `.mcp.json` i wpisz adres swojego HA. Token trafia do sesji jako `${HA_TOKEN}` i nie jest zapisywany w żadnym pliku konfiguracyjnym.
4. W HA udostępnij Asystentowi te urządzenia, którymi Achaja ma sterować (Ustawienia → Asystenci głosowi → Udostępnij).

Dodatkowo `setup/ha_areas.py` pomaga uporządkować dom: `dump` pokazuje obszary i encje bez przypisanego pokoju, `apply plan.json` przypisuje urządzenia do obszarów (Assist lepiej rozumie polecenia typu „zgaś światła w sypialni”).

## Telewizor z Androidem (opcjonalnie)

1. Na telewizorze: Informacje → 7× „Kompilacja” → Opcje programisty → **Debugowanie USB / przez sieć**.
2. `install.ps1 -WithAdb` (pobiera `platform-tools` do folderu projektu).
3. W `config.json` uzupełnij sekcję `tv`, a potem `.venv\Scripts\python.exe .claude\scripts\tv.py connect` i zatwierdź pytanie na ekranie TV.

## Konfiguracja

Wszystko jest w `config.json` (tworzonym z `config.example.json`): mikrofon, słowa sterujące i ich czułość, model i wysiłek sesji Achai, głos i wyjścia audio, frazy potwierdzeń, foldery projektów i aliasy, Home Assistant, telewizor. Najczęściej strojone:

| Klucz | Znaczenie |
|---|---|
| `wake.end_match`, `wake.end_stable_seconds` | czułość i opóźnienie słowa końcowego |
| `wake.auto_listen_after_question` | tryb rozmowy |
| `achaja.model`, `achaja.effort` | szybkość vs jakość odpowiedzi |
| `voice.outputs`, `voice.default_output` | słuchawki, głośnik Cast |
| `voice.ack_phrases`, `voice.working_phrases` | potwierdzenia i przypomnienia |

## Prywatność i bezpieczeństwo

- Nasłuch słów kluczowych działa **offline** (Vosk). Dźwięk promptu trafia do Claude Code (dyktowanie), a tekst mowy syntetycznej do usługi edge-tts.
- `config.json`, `.mcp.json`, `state/` (tokeny, logi, transkrypcje robocze) i `.claude/settings*.json` są w `.gitignore` — nie publikuj ich.
- Achaja pyta głosem o zgodę przed akcjami nieodwracalnymi (git push, deploy, usuwanie danych, zamki i alarmy w domu).
- Nasłuch wpisuje klawisze wyłącznie do konsoli wskazanej sesji Claude Code.

## Rozwiązywanie problemów

| Objaw | Co sprawdzić |
|---|---|
| Brak piknięcia po słowie wybudzenia | `state\listener.log` — wpisy `czuwanie:`; dobierz `wake.phrases` |
| Piknięcie jest, ale Claude nie nagrywa | pole promptu musi być puste; tryb `voice tap` w Claude Code |
| Słowo końcowe nie wysyła promptu | log pokazuje, co usłyszał nasłuch — obniż `wake.end_match` |
| Prompt wysyła się za wcześnie | podnieś `wake.end_match` lub `wake.end_stable_seconds` |
| Nie słychać odpowiedzi | `voice.outputs`, `state\speak_error.txt`; przy słuchawkach Bluetooth wybierz wyjście „zestaw słuchawkowy” (profil HFP) |
| Agent nie odpowiada | okno „Agent: …”, `state\agents\<projekt>.log` |

## Ograniczenia

- Tylko Windows (wstrzykiwanie klawiszy i wybór urządzeń audio per program korzystają z API Windows).
- Ekran nie może być zablokowany (wygaszony monitor nie przeszkadza).
- Dyktowanie wymaga konta claude.ai w Claude Code.
- Mały model Vosk myli podobne słowa — dlatego słowa sterujące są dopasowywane rozmyto, a treść promptu rozpoznaje Claude.

## Licencja

MIT — patrz [LICENSE](LICENSE).

Pull requesty mile widziane: obsługa innych systemów, inne silniki mowy, nowe satelity głosowe.
