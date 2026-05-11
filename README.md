# /vibe-sing

A Claude Code skill that ends your session with a song.

Pipeline: **Claude Code session transcript → Gemini (mood translation) → Google Lyria 3 (music) → auto-play.**

- `/vibe-sing` — 30-second clip (default)
- `/vibe-sing pro` — ~2-minute full song

## Why it isn't corny

Both the transcript filter and the Gemini system prompt explicitly forbid references to programming, files, libraries, bugs, or anything technical. The output is a *cinematic mood prompt* — genre, instrumentation, tempo, feel — not a song about your session. A listener should never guess what you were working on.

## Install

Clone directly into Claude Code's skills directory:

```bash
git clone https://github.com/harajlim/vibe-sing.git ~/.claude/skills/vibe-sing
cd ~/.claude/skills/vibe-sing

# Python deps
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# API key — get one at https://aistudio.google.com/apikey
cp .env.example .env
$EDITOR .env  # paste your GOOGLE_API_KEY
```

Then in any Claude Code session, type `/vibe-sing`.

> **Hacking on the source?** Clone anywhere and symlink instead:
> `ln -s "$(pwd)" ~/.claude/skills/vibe-sing` — edits go live immediately.

## Configuration

Env vars (set in `.env` or shell):

- `GOOGLE_API_KEY` — required.
- `VIBE_SING_GEMINI_MODEL` — defaults to `gemini-flash-latest` (auto-tracks newest Flash). Pin a version like `gemini-2.5-flash` if you want.

Output mp3s land in `./generations/` (gitignored).

## How it works

1. Finds the JSONL transcript of the current session at `~/.claude/projects/<encoded-cwd>/<session>.jsonl` (picks the most recently modified — i.e. the live session).
2. Extracts user prompts and assistant prose. Skips tool calls, tool results, thinking blocks, and system reminders. Up to ~100k tokens, tail-biased.
3. Sends to Gemini with strict instructions: cinematic mood prompt only, no technical references, no specifics, no corniness.
4. Sends Gemini's prompt to Lyria 3 (clip or pro).
5. Saves the mp3 and `open`s it (macOS default audio player).

## Files

```
vibe-sing/
├── SKILL.md           # instructions Claude follows when /vibe-sing fires
├── run.sh             # launcher (picks .venv/bin/python or system python3)
├── vibe_sing.py       # pipeline
├── requirements.txt   # google-genai, python-dotenv
├── .env.example       # template for your GOOGLE_API_KEY
└── generations/       # output mp3s (gitignored)
```

## Platform

macOS (uses `open` to auto-play). Linux users: swap `open` for `xdg-open` in `vibe_sing.py`.
