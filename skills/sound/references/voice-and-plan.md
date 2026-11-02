# Voice direction and the plan

## Directing a voiceover

- **Voice.** Any voice id from the provider's library works; pick one whose register fits the brand's
  voice (`/workspace/brand/voice.md`) and say which one you used so the next film can match it.
- **Continuity.** One call per line, with `previous_text` and `next_text`, so the read flows across
  cuts. A `seed` keeps a retake close to the last one.
- **Write the performance into the text.** Put a bracketed audio tag right before the words it should
  shape, where the delivery changes:
  `[warm] Meet the new canvas. [pause] It ships today.`
  - Delivery: `[warm]`, `[curious]`, `[matter-of-fact]`, `[excited]`, `[quiet, measured narration]`.
  - Reactions: `[soft chuckle]`, `[exhales]`.
  - Pauses and stress: `[pause]`, an ellipsis for a hesitant beat, a dash for a short break, CAPITALS
    on the one word that carries the line.
  - Describe the voice, not a sound: a tag like `[rain]` may come back as a noise. Effects belong in
    the score.
  - Match tags to the brand: a calm narrator does not shout. One or two tags per line, on the change.
- **Settings.** Lower `stability` gives a more varied, expressive read; higher keeps every line close
  to one delivery. Check pace in the tool's report (syllables per second) rather than trusting a slider.
- **What comes back.** Where the line ends, its pace, and `<name>.words.json` with every word's start
  and end (tags left out), for captions, cuts and landing a sound on a word.

## plan.json

```json
{
  "video": { "path": "projects/<slug>/renders/film-silent.mp4", "duration_s": 24.0, "fps": 30 },
  "music": [
    { "act": "all", "start_s": 0, "end_s": 24.0, "crossfade_out_s": 2,
      "selected": { "source": "elevenlabs", "file": "music/bed.mp3", "title": "calm pulse", "prompt": "…" } }
  ],
  "sfx_cues": [
    { "t_start_s": 1.2, "dur_s": 0.2, "intent": "reveal", "description": "first card lands",
      "gain": 1.0, "source": "synth", "recipe": "ui-soft-in" },
    { "t_start_s": 6.8, "dur_s": 1.4, "intent": "riser", "description": "into the product shot",
      "gain": 0.8, "source": "elevenlabs", "file": "sfx/riser.mp3", "prompt": "…" }
  ],
  "vo": [
    { "start_s": 0.6, "dur_s": 3.4, "file": "vo/line-01.mp3", "text": "Meet the new canvas." }
  ]
}
```

- `source` is `elevenlabs` (made by a host tool), `code` (made in the sandbox), `supplied` (came with
  the request) or, for cues only, `synth` with a `recipe`. Files live in `<jobDir>/sound-assets/` under
  their kind's folder with a slug name; anything else is skipped with a warning.
- A bed that starts after 0 (`start_s` > 0) fades in over `crossfade_in_s`; one that starts at 0 fades
  out over `crossfade_out_s` before `end_s`. `music` may be empty.
- Cue `intent` words drive the bed automation: `riser`/`swell` (duck under), `swoosh`, `hero`,
  `transition`, `turn`, `flash` (dip just before), `shimmer`, `chime`, `reveal`, `bloom` (duck under),
  `sting`, `signature`, `logo` (duck under).
- A voice line's `dur_s` is where the tool says it ends. `source` defaults to `elevenlabs`.
- `<jobDir>/sound-assets/ledger.json` records every file's source, hash and licence basis.
