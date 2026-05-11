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
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from google import genai


SKILL_DIR = Path(__file__).parent
GENERATIONS_DIR = SKILL_DIR / "generations"
GENERATIONS_DIR.mkdir(exist_ok=True)

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
You are writing a single Lyria music prompt for a song that is FOR a specific person — based on a transcript of a conversation they had with an AI agent.

YOUR JOB: read the transcript and produce ONE music prompt (3-6 sentences) that captures *the user's* energy and includes clear vocal/lyrical direction, so Lyria sings vocals in their wavelength. You are NOT writing lyrics. You are directing the singer.

FOCUS ON THE USER, NOT THE AGENT:
- Read the USER's messages closely. The agent's responses are context for understanding the user's reactions.
- Ask yourself silently: How is this person feeling right now? What's their humor — sardonic, dry, irreverent, absurdist, gentle, hyped? What would make THEM laugh vs cringe? What kind of singing voice would fit them?
- The song should feel like a friend who knows them wrote it for them.

THE PROMPT MUST INCLUDE:
1. Genre + instrumentation (e.g. "indie-rock with snappy electric guitar and tight live drums").
2. Tempo (BPM) and overall mood.
3. Vocal style — specify the singer: e.g. "male indie-folk vocal", "female pop vocal", "spoken-word with breathy delivery", "group chant chorus", "Tom-Waits-style gravel baritone".
4. **Lyrical direction** — the *tone, attitude, and emotional content* the lyrics should carry. Direct the song's *energy*, not its literal subject. E.g. "lyrics with a wry, slightly-fed-up but secretly amused tone, building into a cathartic singalong about getting what you finally asked for". Lyria will invent the actual words.

HARD RULES (corniness prevention):
- NO literal references in your prompt to: programming, code, files, bugs, libraries, terminals, AI, agents, Claude, Gemini, LLMs, debugging, APIs, scripts, sessions, "the project".
- NO proper nouns from the transcript. NO project names. NO file names.
- A stranger hearing the resulting song should not be able to tell this came from a coding session — they should just hear a song that feels like *this person*.
- Direct the lyrics' *emotional shape*, not their literal topic. "Song about debugging" is cringe. "Song with the energy of someone gleefully calling out small absurdities" is good.

STYLE TARGETS: Reddit-funny, indie-comedy-adjacent, sly. Lonely Island / Bo Burnham / Flight of the Conchords / Father John Misty wryness. Specific enough to land. Oblique enough to never be cringe.

LENGTH HINT for Lyria (include in the prompt where natural):
- target=clip → "compact 30-second song"
- target=pro → "full ~2 minute song with verse/chorus structure"

OUTPUT: just the prompt text. No JSON. No markdown. No preamble. No quotes around it. No "Here is the prompt:" framing. Just the prompt.

TARGET LENGTH: {target}

TRANSCRIPT:
"""


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
    contents = GEMINI_INSTRUCTIONS.replace("{target}", target) + transcript_text
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


def main():
    if not API_KEY:
        sys.exit(
            "GOOGLE_API_KEY not set. Add it to ~/.claude/skills/vibe-sing/.env "
            "or have it available in the environment."
        )

    arg = sys.argv[1].lower() if len(sys.argv) > 1 else ""
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

    # Play inline via afplay (macOS built-in). Detached so the script returns
    # immediately and audio continues in the background.
    try:
        subprocess.Popen(
            ["afplay", str(out)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except FileNotFoundError:
        subprocess.run(["open", str(out)], check=False)

    print(json.dumps({
        "mood_prompt": music_prompt,
        "audio_file": str(out),
        "model": lyria_model,
        "gemini_model": GEMINI_MODEL,
    }))


if __name__ == "__main__":
    main()
