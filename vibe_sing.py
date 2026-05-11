#!/usr/bin/env python3
"""
/vibe-sing — distill the current Claude Code session into a Lyria song.

Pipeline:
  1. Find the current Claude Code session's transcript JSONL.
  2. Slice recent messages into vibe-relevant text (skip tool calls/results).
  3. Ask Gemini for a Lyria prompt (genre/mood/tempo, no specifics, no tech refs).
  4. Call Lyria. Save the audio. Open it.

Usage:
  python vibe_sing.py [pro]
"""
import json
import os
import re
import signal
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from google import genai


SKILL_DIR = Path(__file__).parent
GENERATIONS_DIR = SKILL_DIR / "generations"
GENERATIONS_DIR.mkdir(exist_ok=True)
PID_FILE = SKILL_DIR / ".playing.pid"

env_file = SKILL_DIR / ".env"
if env_file.exists():
    load_dotenv(env_file)

API_KEY = os.environ.get("GOOGLE_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("VIBE_SING_GEMINI_MODEL", "gemini-3-flash-preview")

MAX_TRANSCRIPT_CHARS = 400_000  # ~100k tokens

NOISE_PATTERNS = [
    re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL),
    re.compile(r"<local-command-[^>]*>.*?</local-command-[^>]*>", re.DOTALL),
    re.compile(r"<command-name>.*?</command-name>", re.DOTALL),
    re.compile(r"<command-message>.*?</command-message>", re.DOTALL),
    re.compile(r"<command-args>.*?</command-args>", re.DOTALL),
]


def encode_cwd_variants(cwd: Path) -> list[str]:
    """Claude Code project dir naming has varied — try both encodings."""
    s = str(cwd.resolve()).strip("/")
    return [
        "-" + s.replace("/", "-").replace("_", "-"),
        "-" + s.replace("/", "-"),
    ]


def find_transcript() -> Path:
    """
    Locate the JSONL transcript of the *current* Claude Code session.

    Deterministic when running inside Claude Code: the harness exports
    CLAUDE_CODE_SESSION_ID, which is the JSONL filename stem. We glob for it
    under ~/.claude/projects/ so we don't depend on the project-dir encoding.

    Fallback (older Claude Code versions or out-of-session use): the most
    recently modified JSONL whose project dir matches the current cwd.
    """
    projects_root = Path.home() / ".claude" / "projects"

    session_id = os.environ.get("CLAUDE_CODE_SESSION_ID", "").strip()
    if session_id:
        matches = list(projects_root.rglob(f"{session_id}.jsonl"))
        if matches:
            return matches[0]
        sys.exit(
            f"CLAUDE_CODE_SESSION_ID={session_id} but no matching transcript "
            f"under {projects_root}. Was the session just started?"
        )

    cwd = Path.cwd()
    candidates: list[Path] = []
    for enc in encode_cwd_variants(cwd):
        d = projects_root / enc
        if d.exists():
            candidates.extend(d.glob("*.jsonl"))
    if not candidates:
        candidates = list(projects_root.rglob("*.jsonl"))
    if not candidates:
        sys.exit("No Claude Code session transcripts found.")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def strip_noise(text: str) -> str:
    for pat in NOISE_PATTERNS:
        text = pat.sub("", text)
    return text.strip()


def extract_text(transcript: Path) -> str:
    """Pull user prompts and assistant text blocks. Skip thinking, tool calls, tool results."""
    parts: list[str] = []
    for line in transcript.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip():
            continue
        try:
            evt = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = evt.get("message") or {}
        role = msg.get("role")
        content = msg.get("content")
        if not role or content is None:
            continue
        if isinstance(content, str):
            cleaned = strip_noise(content)
            if cleaned:
                parts.append(f"{role}: {cleaned}")
        elif isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    text = strip_noise(block.get("text", ""))
                    if text:
                        parts.append(f"{role}: {text}")

    blob = "\n\n".join(parts)
    if len(blob) > MAX_TRANSCRIPT_CHARS:
        blob = blob[-MAX_TRANSCRIPT_CHARS:]
    return blob


GEMINI_INSTRUCTIONS = """\
You write ONE short Lyria music prompt for a song that is FOR the USER in this transcript. Read who they are. Then direct Lyria.

OUTPUT: 2-3 sentences total. Tight. No preamble, no JSON, no quotes, no fences. Just the prompt.

THE PROMPT MUST COVER:
- Genre + 1-2 key instruments.
- Tempo (BPM) + mood in a few words.
- Vocal style: who is singing (e.g. "deadpan male indie vocal", "wistful female folk vocal", "spoken-word delivery").
- Lyrical direction: ONE oblique theme or metaphor that captures the SHAPE of the session, plus the lyrics' tone (sardonic, hopeful, cathartic, etc.). One specific image is great. NO literal tech.
- Lyric density: explicitly say "sparse lyrics, breathing room between lines" so Lyria doesn't cram words.

You are NOT writing lyrics. Lyria invents the words. You give it a theme and a vibe.

HOW TO STAY RELATED WITHOUT BEING CRINGE:
- The session has a *shape* (iteration, polishing, frustration, breakthrough, packaging, hand-off, late-night focus, etc.). Lyrics can be about that shape, expressed as metaphor.
- Good: "lyrics about polishing a small object until it gleams" / "lyrics about the rhythm of giving and taking notes" / "lyrics about finally being understood".
- Bad: "lyrics about code", "lyrics about an AI agent", "lyrics about Claude".
- A stranger should not be able to tell this came from a coding session, but YOU should feel a faint echo of the work in the lyrics' theme.

HARD RULES:
- NO literal mentions of: programming, code, files, bugs, libraries, terminals, AI, agents, Claude, Gemini, LLMs, debugging, APIs, scripts, sessions, "the project", repos, GitHub.
- NO proper nouns or names from the transcript.
- NO restating the target length tag in your output.

STYLE TARGETS: indie, wry, sly, slightly absurd. Lonely Island / Bo Burnham / Flight of the Conchords / Father John Misty / Phoebe Bridgers. Specific enough to land. Never corny.

This song is """ + "{LENGTH_HINT}" + """.

TRANSCRIPT:
"""

LENGTH_HINTS = {
    "clip": "a compact 30-second song with sparse lyrics (one short verse, maybe a brief hook)",
    "pro":  "a full ~2 minute song with a verse / chorus / verse / chorus shape and sparse, breathing lyrics",
}


def extract_response_text(resp) -> str:
    if hasattr(resp, "text") and resp.text:
        return resp.text.strip()
    for cand in getattr(resp, "candidates", None) or []:
        content = getattr(cand, "content", None)
        for p in (getattr(content, "parts", None) or []):
            t = getattr(p, "text", None)
            if t:
                return t.strip()
    return ""


def gemini_prompt(transcript_text: str, target: str, client: genai.Client) -> str:
    length_hint = LENGTH_HINTS.get(target, LENGTH_HINTS["clip"])
    contents = GEMINI_INSTRUCTIONS.replace("{LENGTH_HINT}", length_hint) + transcript_text
    resp = client.models.generate_content(model=GEMINI_MODEL, contents=contents)
    text = extract_response_text(resp)
    if not text:
        sys.exit(f"Gemini ({GEMINI_MODEL}) returned no text.")
    return text.strip().strip('"').strip("'").strip()


def lyria_generate(prompt: str, model: str, client: genai.Client) -> tuple[bytes, str]:
    resp = client.models.generate_content(model=model, contents=prompt)
    parts = []
    if hasattr(resp, "parts") and resp.parts:
        parts = resp.parts
    elif getattr(resp, "candidates", None):
        parts = resp.candidates[0].content.parts
    for part in parts:
        inline = getattr(part, "inline_data", None) or getattr(part, "inlineData", None)
        if inline is not None and getattr(inline, "data", None):
            mime = (
                getattr(inline, "mime_type", None)
                or getattr(inline, "mimeType", None)
                or "audio/mpeg"
            )
            return inline.data, mime
    sys.exit("Lyria returned no audio.")


def stop_playing() -> dict:
    """
    Kill any currently-playing vibe-sing song.

    Two-pronged so we cover edge cases:
      1. Precise kill via .playing.pid (the song our last invocation started).
      2. Belt-and-suspenders pkill: any afplay process whose command line
         references our generations dir. Catches orphans from older script
         versions, race conditions during Lyria generation, and manually-
         started playback. Scoped tightly enough not to nuke unrelated afplay.
    """
    killed_pids: list[int] = []

    # 1. Precise: via pid file.
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            try:
                os.kill(pid, signal.SIGTERM)
                killed_pids.append(pid)
            except ProcessLookupError:
                pass  # already finished
            except PermissionError:
                pass
        except ValueError:
            pass
        PID_FILE.unlink(missing_ok=True)

    # 2. Fallback: pkill any afplay playing a file from our generations dir.
    # The "vibe-sing/generations/vibe-" substring appears in both the symlink
    # and resolved paths, so this works regardless of how the script was run.
    pkill_killed = False
    try:
        result = subprocess.run(
            ["pkill", "-f", "afplay.*vibe-sing/generations/vibe-"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        # pkill returns 0 if it killed >=1 process, 1 if no matches.
        pkill_killed = result.returncode == 0
    except FileNotFoundError:
        pass

    if killed_pids or pkill_killed:
        return {
            "action": "stop",
            "status": "stopped",
            "pids": killed_pids,
            "via_pkill": pkill_killed,
        }
    return {"action": "stop", "status": "nothing playing"}


def main():
    arg = sys.argv[1].lower() if len(sys.argv) > 1 else ""

    if arg == "stop":
        print(json.dumps(stop_playing()))
        return

    if not API_KEY:
        sys.exit(
            "GOOGLE_API_KEY not set. Add it to ~/.claude/skills/vibe-sing/.env "
            "or have it available in the environment."
        )

    is_pro = arg == "pro"
    lyria_model = "lyria-3-pro-preview" if is_pro else "lyria-3-clip-preview"
    target = "pro" if is_pro else "clip"

    transcript_path = find_transcript()
    print(f"[transcript] {transcript_path.name}", file=sys.stderr)

    transcript_text = extract_text(transcript_path)
    if not transcript_text.strip():
        sys.exit("Transcript yielded no vibe-relevant text.")
    print(f"[transcript] {len(transcript_text):,} chars of vibe-relevant text", file=sys.stderr)

    client = genai.Client(api_key=API_KEY)

    print(f"[gemini] {GEMINI_MODEL} translating vibe...", file=sys.stderr)
    music_prompt = gemini_prompt(transcript_text, target, client)
    print(f"[mood]\n{music_prompt}", file=sys.stderr)

    print(f"[lyria] {lyria_model} composing...", file=sys.stderr)
    audio_bytes, mime = lyria_generate(music_prompt, lyria_model, client)

    ext = "wav" if "wav" in mime else "mp3"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = GENERATIONS_DIR / f"vibe-{stamp}.{ext}"
    out.write_bytes(audio_bytes)
    print(f"[saved] {out}", file=sys.stderr)

    # If a prior song is still playing, stop it before starting a new one.
    stop_playing()

    # Play inline via afplay (macOS built-in). Detached so the script returns
    # immediately and audio continues in the background. PID gets stashed so
    # `vibe_sing.py stop` can kill it later.
    playing_pid = None
    try:
        proc = subprocess.Popen(
            ["afplay", str(out)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        playing_pid = proc.pid
        PID_FILE.write_text(str(playing_pid))
    except FileNotFoundError:
        subprocess.run(["open", str(out)], check=False)

    print(json.dumps({
        "mood_prompt": music_prompt,
        "audio_file": str(out),
        "model": lyria_model,
        "gemini_model": GEMINI_MODEL,
        "playing_pid": playing_pid,
    }))


if __name__ == "__main__":
    main()
