# /vibe-sing

A Claude Code skill that ends your session with a song.

Reads the current session's transcript, asks Gemini to write a music prompt tuned to your specific vibe (not the agent's), then has Google Lyria compose and sing it. Plays straight to your speakers.

🔊 **Listen to a sample** generated while finishing this very skill: [examples/we-cooked.mp3](https://github.com/harajlim/vibe-sing/raw/master/examples/we-cooked.mp3) (30s thrash, shouted: *"HOLY SHIT WE COOKED TONIGHT / LET'S HOPE THEY ACCEPT OUR PR"*).

## Commands

```
/vibe-sing        30-second clip (default)
/vibe-sing pro    ~2-minute full song with vocals
/vibe-sing stop   kill the currently-playing song
```

## Install

Clone into Claude Code's skills directory:

```bash
git clone https://github.com/harajlim/vibe-sing.git ~/.claude/skills/vibe-sing
cd ~/.claude/skills/vibe-sing

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

cp .env.example .env
$EDITOR .env       # paste your GOOGLE_API_KEY
```

Get a Google AI Studio key at https://aistudio.google.com/apikey.

Open any Claude Code session and type `/vibe-sing`.

## How it works

1. The skill runs a Python pipeline as a Bash subprocess. Claude Code exposes `CLAUDE_CODE_SESSION_ID` to the subprocess, so the script locates *this* session's transcript JSONL deterministically (no "most recently modified" guessing, works fine with many parallel sessions).
2. It pulls your messages plus the agent's prose out of the transcript. Tool calls, tool results, and thinking blocks are dropped. Up to roughly 100k tokens of recent context, tail-biased.
3. That text goes to Gemini (`gemini-3-flash-preview` by default). The system prompt tells Gemini to read *you* (mood, humor, energy) and output a single Lyria prompt with vocal direction and lyrical tone. Gemini does not write the lyrics. Lyria does.
4. Lyria composes the song. The mp3 lands in `generations/`, plays via `afplay` in a detached subprocess, and the script returns. Audio keeps playing after the skill call ends.

`/vibe-sing stop` reads the stashed PID and `SIGTERM`s the player, with a `pkill` fallback that targets any orphaned afplay running on a file from this skill's `generations/` dir.

## Configuration

| Env var                    | Default                  | Notes                                          |
| -------------------------- | ------------------------ | ---------------------------------------------- |
| `GOOGLE_API_KEY`           | (required)               | From Google AI Studio.                         |
| `VIBE_SING_GEMINI_MODEL`   | `gemini-3-flash-preview` | Override to pin or upgrade.                    |

Output mp3s live in `generations/` (gitignored).

## Platform

macOS. Auto-play uses `afplay`, which is built in. On Linux, swap `afplay` for `mpg123` or `paplay` in `vibe_sing.py`.

## Layout

```
vibe-sing/
├── SKILL.md          # what Claude reads when /vibe-sing fires
├── run.sh            # picks .venv/bin/python or system python3, execs the pipeline
├── vibe_sing.py      # the pipeline
├── requirements.txt  # google-genai, python-dotenv
├── .env.example      # GOOGLE_API_KEY template
└── generations/      # output mp3s (gitignored)
```

## License

MIT.
