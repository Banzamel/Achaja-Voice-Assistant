# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.0] — 2026-09-21

First public release.

### Added
- **Hands-free control of Claude Code**: an offline wake-word listener (Vosk) presses
  Space in the Claude Code console, Claude's own dictation transcribes the prompt, and
  the end word submits it. Keystrokes go straight into the console input buffer, so the
  window does not need focus.
- **Spoken answers**: a Stop hook reads the `[VOICE]` / `[GŁOS]` summary of every reply
  through edge-tts, on a local device or a Google Cast speaker, with switching by voice.
- **Conversation mode**: when a reply ends with a question, recording of the answer starts
  automatically. Acknowledgements ("on it") and "still working" reminders keep you informed.
- **Project agents**: a task for a project starts a separate Claude Code session inside that
  project's folder, with its own `CLAUDE.md`, live progress window and a report that the
  assistant summarizes aloud. Conversations per project are continuous.
- **Home Assistant** through the official MCP server integration, plus `setup/ha_areas.py`
  for reviewing and assigning entities to areas.
- **Per-app audio routing for Windows** (`setup/set_app_audio.py`): give one program its own
  microphone or speaker without touching the system defaults.
- **Installer** (`install.ps1`) with `-Language pl|en`: project-local virtual environment,
  dependencies, speech model, configuration, voice hooks and an optional startup shortcut.
- **One universal `config.json`** with a `languages` block: control words, speech model, voice
  and acknowledgement phrases per language. The name "Achaja" is recognized as `aha ja`
  (Polish) and `a kaya` (English).

### Known limitations
- Windows only; the screen must be unlocked for keystrokes to reach Claude Code.
- Dictation requires Claude Code signed in with a claude.ai account.
- Control words depend on the installed Vosk model, so they are language-specific.
- Tested on Windows 10 with Python 3.14; other setups may need adjustments.

[0.1.0]: https://github.com/Banzamel/Achaja-Voice-Assistant/releases/tag/v0.1.0
