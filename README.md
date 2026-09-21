# Achaja — control Claude Code with your voice

*[Wersja polska](README.pl.md)*

**Achaja** turns [Claude Code](https://claude.com/claude-code) into a hands-free voice assistant. Say the wake word, dictate your prompt, finish with the end word — the prompt submits itself and the answer is spoken back through your headphones or a speaker. Achaja runs commands on your PC, **delegates work to agents in your own projects**, and can control your home through Home Assistant.

---

## How it works

```
[microphone] --- wake-word listener (Vosk, offline, control words only)
     │
     ├─► presses Space in the Claude Code window → Claude's dictation writes the prompt
     │
     └─► after the end word, presses Space again → the prompt submits itself
                     │
                     ▼
        Claude Code (the "Achaja" session)
         ├─ runs commands on the computer
         ├─ delegates tasks to project agents (separate claude sessions)
         └─ controls the home (Home Assistant over MCP) and a TV (ADB)
                     │
                     ▼
        Stop hook → [GŁOS] section of the answer → speech (edge-tts)
                     → headphones or a Google Cast speaker
```

The key design decision: **the prompt itself is transcribed by Claude Code**, not by a local model. The small offline model only picks up a handful of control words, so dictation quality stays exactly as good as Claude Code's, and the listener sends nothing to the network.

Keystrokes are written straight into the Claude Code console input buffer (`WriteConsoleInputW`), so **the window does not need focus** — you can keep working while Achaja listens.

## Features

- **Hands-free control** — wake word, dictation, end word, automatic submit.
- **Spoken answers** — Claude ends every reply with a short summary in a `[GŁOS]` ("voice") section, which is read aloud.
- **Conversation mode** — when the answer ends with a question, recording of your reply starts automatically.
- **Acknowledgements** — "I'm on it" right after submit, and "still working" during longer tasks.
- **Project agents** — "have the agent for <project> do X" starts a separate Claude Code session **inside that project's folder** (with its own `CLAUDE.md`, skills and settings), shows live progress in its own window, and returns a report that Achaja summarizes aloud.
- **Audio outputs** — headphones or a Google Cast / Google Home speaker ("answer through the speaker").
- **Home (optional)** — Home Assistant through its official MCP integration: lights, climate, covers, media, live state.
- **TV (optional)** — Android TV over ADB: power, launching apps, opening a specific Netflix title, remote keys, screenshots.
- **Windows audio tool** — assign a microphone or speaker to a single program (e.g. `claude.exe`) without changing the system default devices.

## Requirements

- **Windows 10/11** (keystroke injection and per-app audio routing use Windows APIs).
- **[Claude Code](https://claude.com/claude-code)** signed in with a **claude.ai account** — dictation does not work with an API key or through Bedrock/Vertex.
- **Python 3.11+** (the installer creates a project-local `.venv`).
- A **microphone** and an audio output; an internet connection for speech synthesis (edge-tts).
- Optional: Home Assistant 2025.2+ (the "Model Context Protocol Server" integration), an Android TV, a Google Cast speaker.

## Install

```powershell
git clone https://github.com/Banzamel/Achaja-Voice-Assistant.git
cd Achaja-Voice-Assistant
powershell -ExecutionPolicy Bypass -File install.ps1        # options: -WithAdb -Autostart
```

The installer creates `.venv`, installs the dependencies, downloads the speech model (Vosk PL, ~50 MB), creates `config.json` from the template and generates `.claude/settings.json` with the voice hooks. Options: `-Autostart` (start on login), `-WithAdb` (Android tools for TV control), `-SkipModel`.

Then:

1. Open `config.json` and set at least `wake.microphone` and `agents.project_roots` (the folders holding your projects).
2. List audio device names: `.venv\Scripts\python.exe .claude\scripts\listener.py --devices`.
3. Run `start-achaja.cmd`. Two windows open: the listener and the Claude Code session named "Achaja".

**Another name or another language?** The assistant ships configured for Polish. In `config.json` change `wake.phrases` (wake phrases), `wake.end` / `cancel` / `clear`, `voice.tts_voice` (an edge-tts voice), and set the reply language in `.claude/settings.json` (`"language"`). Vosk only knows words from its own dictionary, so for an unusual name pick a phrase that sounds similar (for "Achaja" the phrase `aha ja` works). Models for other languages: [alphacephei.com/vosk/models](https://alphacephei.com/vosk/models). The assistant's rules live in `.claude/CLAUDE.md` and can be translated as well.

## Usage

| You say | What happens |
|---|---|
| **wake word** → *beep* | Claude Code starts recording your prompt |
| your command… **end word** + a short pause | prompt submitted; Achaja confirms: "I'm on it" |
| **"cancel"** | the recording is discarded |
| **"new conversation"** | clears the context (`/clear`) |
| wake word while Achaja is speaking | stops the speech and starts recording |
| a question from Achaja | recording of your answer starts automatically |

Example commands:

- "open the calculator and add the square roots of two and three"
- "look up how much X costs"
- "have the agent for **vision** check why login is broken"
- "what are the agents doing?", "what did the taxi agent do?", "stop the vision agent"
- "answer through the speaker", "back to headphones"
- "turn on the light in the office", "set the AC to 22 degrees" (Home Assistant)

## Project agents

```
Achaja ──► agent.py run <project> ──► claude -p  (cwd = the project folder)
                                        │  its own .claude/CLAUDE.md, skills, permissions
                                        ├─ an "Agent: <project>" window with live progress
                                        └─ report → Achaja summarizes it aloud
```

- Project names are matched fuzzily (dictation mangles them) plus aliases from `config.json`.
- Each project keeps a continuous conversation (`--resume`); `--new` starts over.
- Agents run in the `auto` permission mode; risky actions are blocked and come back to you as a question.
- Commands: `run`, `status`, `last <project>`, `stop <project>`, `list`.

## Home Assistant (optional)

1. In HA add the **Model Context Protocol Server** integration (control: Assist).
2. Create a long-lived access token and save it to `state/ha_token.txt` (the folder is git-ignored).
3. Copy `.mcp.example.json` → `.mcp.json` and set your HA address. The token reaches the session as `${HA_TOKEN}` and is never stored in a config file.
4. In HA expose the devices Achaja may control (Settings → Voice assistants → Expose).

`setup/ha_areas.py` also helps tidy the home: `dump` lists areas and entities with no room assigned, `apply plan.json` assigns devices to areas — Assist then understands commands like "turn off the lights in the bedroom" much better.

## Android TV (optional)

1. On the TV: About → tap "Build" 7× → Developer options → **USB / network debugging**.
2. Run `install.ps1 -WithAdb` (downloads `platform-tools` into the project folder).
3. Fill in the `tv` section of `config.json`, then run `.venv\Scripts\python.exe .claude\scripts\tv.py connect` and accept the prompt on the TV.

## Configuration

Everything lives in `config.json` (created from `config.example.json`): microphone, control words and their sensitivity, the model and effort of the Achaja session, voice and audio outputs, acknowledgement phrases, project folders and aliases, Home Assistant, TV. Most commonly tuned:

| Key | Meaning |
|---|---|
| `wake.end_match`, `wake.end_stable_seconds` | end-word sensitivity and delay |
| `wake.auto_listen_after_question` | conversation mode |
| `achaja.model`, `achaja.effort` | speed vs. quality of answers |
| `voice.outputs`, `voice.default_output` | headphones, Cast speaker |
| `voice.ack_phrases`, `voice.working_phrases` | acknowledgements and reminders |

## Privacy and safety

- Wake-word listening runs **offline** (Vosk). Prompt audio goes to Claude Code's dictation service, and the spoken text to edge-tts.
- `config.json`, `.mcp.json`, `state/` (tokens, logs, working transcripts) and `.claude/settings*.json` are git-ignored — don't publish them.
- Achaja asks out loud before irreversible or outward-facing actions (git push, deploys, deleting data, locks and alarms at home).
- The listener writes keystrokes only into the console of the Claude Code session it manages.

## Troubleshooting

| Symptom | What to check |
|---|---|
| No beep after the wake word | `state\listener.log` — the `czuwanie:` (idle) entries; tune `wake.phrases` |
| Beep works but Claude doesn't record | the prompt input must be empty; Claude Code must be in `voice tap` mode |
| The end word doesn't submit | the log shows what the listener heard — lower `wake.end_match` |
| The prompt submits too early | raise `wake.end_match` or `wake.end_stable_seconds` |
| No speech is heard | `voice.outputs`, `state\speak_error.txt`; with Bluetooth headsets pick the "headset" (HFP) output |
| An agent doesn't answer | the "Agent: …" window, `state\agents\<project>.log` |

## Limitations

- Windows only (keystroke injection and per-app audio routing use Windows APIs).
- The screen must not be locked (a sleeping monitor is fine).
- Dictation requires a claude.ai account in Claude Code.
- The small Vosk model confuses similar words — that's why control words are matched fuzzily while the prompt itself is transcribed by Claude.

## License

MIT — see [LICENSE](LICENSE).

Pull requests welcome: other operating systems, other speech engines, new voice satellites.
