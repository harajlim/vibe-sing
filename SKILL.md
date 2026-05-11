---
name: vibe-sing
description: Generate a song that captures the vibe of the current Claude Code session. Reads the session transcript, asks Gemini for a non-corny mood prompt, calls Google Lyria, and auto-plays the result. Default is a 30s clip; pass `pro` for a ~2 minute version.
disable-model-invocation: false
argument-hint: [pro]
allowed-tools: Bash
---

When the user invokes `/vibe-sing`, run the pipeline script. It distills the current session's emotional vibe into a Lyria music prompt (via Gemini) and composes a song.

## What to do

1. Run the skill's launcher, passing through the user's argument verbatim:

   ```bash
   ~/.claude/skills/vibe-sing/run.sh <arg-if-any>
   ```

   The only meaningful argument is `pro` — generates a ~2 minute song instead of the default 30s clip.

2. The script handles everything: finding the current session's transcript JSONL, slicing the recent vibe-relevant text (skipping tool calls/results), calling Gemini for a mood prompt, calling Lyria, saving the mp3 to `~/.claude/skills/vibe-sing/generations/`, and `open`-ing the file so it plays.

3. After the script returns, the **last line of stdout** is a JSON object with `mood_prompt`, `audio_file`, `model`, and `gemini_model`. Report back to the user in **at most two sentences**:
   - One sentence quoting the mood prompt Gemini chose.
   - One sentence with the file path.

   Do **not** describe what the song is "about" — let the audio speak. Do not add commentary about whether the vibe seems right. The user will hear it and decide.

## Errors

If the script fails (missing `GOOGLE_API_KEY`, no transcript, API error), surface the stderr message verbatim and stop — do not retry.

## Notes

- Requires `GOOGLE_API_KEY` in `.env` inside the skill dir (or in the environment).
- The transcript reader explicitly skips tool calls and tool results to keep the vibe extraction focused on conversational tone.
- Both the transcript filter and the Gemini system prompt are designed to prevent corny "song about debugging React" output — the mood prompt should never reference programming, files, or specific topics.
