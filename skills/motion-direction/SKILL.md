---
name: motion-direction
description: Direct and review motion built in HyperFrames, from a sting to a film. The idea and its turn, timing on a grid, craft, named moves, sound on the picture, and the review rubric.
---

# Motion direction

How to make motion worth watching. HyperFrames is the engine: the composition contract, the CLI,
GSAP adapters and the catalog are in the vendored `hyperframes`, `hyperframes-core`,
`hyperframes-cli` and `hyperframes-animation` skills, and this skill does not repeat them. The
storyboard comes first (`storyboard`); a 1-3 minute film with helpers runs through `launch-film`;
the sound is made with `sound`. This is the director's judgment that sits across all of them.

Everything here is a default to weigh unless it names its evidence. The brand pack outranks it.

| Job | Page |
| --- | --- |
| The idea, the hook, the turn, proof, the final frame, structure, pacing | [references/directing.md](references/directing.md) |
| Easing, springs, type in motion, camera, transitions, composition, rhythm, polish | [references/craft.md](references/craft.md) |
| Named moves: when, timing, sound, how to build them | [references/techniques.md](references/techniques.md) |
| The grid, a sound for each event, the cull, balance, loudness, sync | [references/sound.md](references/sound.md) |
| Brand decisions in motion and who wins a conflict | [references/brand-in-motion.md](references/brand-in-motion.md) |
| Scoring a film at a gate; how to look; failure patterns | [references/review.md](references/review.md) |

## The one difference

A deck is a sequence of frames. A film is a sequence of frames with something crossing between
them. A film is an argument with a turn, and a frame asks for at most two things at once. Everything
below serves that.

## 1. The idea, before any code

- **One sentence a stranger could repeat after one viewing.** If you cannot say it, there is no film
  yet. Read the beats aloud as one continuous sentence: if each beat is a self-contained label, you
  have a deck.
- **The concept gate** (`brand-design`): a real thing shown, a specific idea, or bold type. Decorative
  nodes, dots and glows are never the idea.
- **The hook is complete inside the first second**: something on frame 0 already moving, the
  statement readable with the sound off. Frame 0 is also the poster. `artifact-contract`'s
  `--allow-blank-ends` is for a fade from or to a flat ground the person asked for, never to get a
  blank opening past the gate.
- **The turn** is the one concrete thing the film pivots on, as an image: a before and after, many
  becoming one, the impossible made possible.
- **Proof on screen**: the real product surface, the real number with its source. A claim with no
  proof on screen is a slide.
- **The final frame** is big and calm: the logo or the one line, landing on a downbeat or the last
  word, held long enough to read.
- **One motif** threads the film and resolves on the last frame. **Moves come from the subject**:
  derive each move from what the product does, never from the last film's moves.

Decide early whether the film is **voiceover-led** (cut to the words; copy lands on or just before
its word) or **music-led** (cut to the beat grid; something visible changes on the beats). A film
with a voiceover is cut to the voiceover, not the music. Details: [directing](references/directing.md).

## 2. The grid: one clock for picture and sound

Write the timing down before you animate, as a named beat table at the top of the composition's
script for a short piece, or as `timeline.js` in the project when there is a soundtrack grid or more
than one file. It holds the frame rate and length, the tempo and beats (or the voiceover's word
starts), the cuts, the hits, the storyboard frame times, and the holds you mean (`AUDIT`, below).
Scenes read their times from it and never type them, so a re-time is one number.

- From a reference film or a supplied track: `film-breakdown` drafts it (`breakdown.mjs` writes
  `timeline.draft.js`; `analyze-audio.mjs --js` writes the grid of a track).
- From a mood: pick a tempo (cinematic around 60-80 BPM, smooth 90-110, kinetic 115-128) and fill
  whole bars: BPM = 240 × bars ÷ seconds.
- **Holds are arithmetic**: settled hold = next event start − (entrance start + entrance duration).
  Run it on every beat before defending the pacing; a reading hold follows reading speed
  ([design-wiki](../design-wiki/references/typography.md), type on screen over time).
- `AUDIT = { preset, holds: [[t0, t1, "reason"]] }` declares the stillness the film means: an end
  card, a copy read. The preset (`reel`, `launch`, `explainer`, `loop`) says how much stillness its
  format expects ([directing](references/directing.md#declaring-the-holds-audit)). `video-score`
  reports frozen runs and shots that never develop; a finding inside a declared hold is named in the
  delivery note, any other is a fix.

## 3. Build it in HyperFrames

- **Search before you author**: `hyperframes catalog --query "<the move in plain words>"`, then
  `hyperframes add`; write by hand only when nothing fits (`hyperframes-registry`).
- **One paused timeline per composition**, seek-driven; scenes as sub-compositions mounted by a thin
  `index.html` (`hyperframes-core`). Elements a later move needs get stable ids, scene-prefixed
  (`#s3-card`), and a carrier that crosses scenes is unprefixed (`#carrier-report`) on its own track.
- **One easing family per film.** [scripts/motion-presets.js](scripts/motion-presets.js) holds the
  frame presets and five families (silk, snap, spring, float, pulse) with `enter`, `exit`, a seeded
  hash, log-space zoom and frame snapping; copy it next to the composition and load it after GSAP.
- **Offline**: copy GSAP and every asset next to the composition (`media-production` says where
  GSAP lives); HyperFrames examples that load from a CDN fail in the sandbox.
- **Brand**: tokens from `/workspace/brand/tokens.css`, the real logo from `/workspace/brand/logos/`,
  fonts through local `@font-face` (`hyperframes lint` requires it).

## 4. Sound on the same grid

Every event the eye follows gets its own designed sound on the same timeline constant; silence is a
choice. With a voiceover, generate the lines first (`generate_voiceover`) and cut to their word
timings. Mixing, levels, mastering to -14 LUFS and the `audio-lint` gate are `sound`'s job; what to
put where is [references/sound.md](references/sound.md).

## 5. Look, render, look again

The loop you run on code, run on pixels:

1. **Before any render**: `node /workspace/tools/video-gate.mjs projects/<slug>/index.html` at zero
   errors, `node /workspace/tools/brand-lint.mjs projects/<slug>/index.html`, and `hyperframes check`
   in the project folder (it lints first; a lint error turns its layout and contrast audits off). The
   gates take paths relative to `/workspace`.
2. **Strips through every cut**, not settled frames: `hyperframes snapshot --at <t−0.06>,<t+0.10>,<t+0.28>`
   around each boundary, tiled with `review-thumb.mjs --sheet`, then one `look` per sheet. A perfect
   endpoint can hide a broken journey.
3. **The artifact**: `node /workspace/tools/video-score.mjs projects/<slug>/index.html` measures
   what is on screen at every sample: blank or thin frames, cuts that carry nothing, shots that never
   develop or never rest, crops, collisions, flat hierarchy. Its six axis numbers are a reading aid,
   never a target.
4. **A draft render** with `start_render_job` (`hyperframes render --quality draft`): it outlives your
   turn and wakes you when it exits. Then frames from the file (`film-breakdown/scripts/grab.mjs
   --sheet`), and against a reference or the animatic, `compare.mjs`.
5. **Review** against [the rubric](references/review.md). For anything over about 30 s, or any film
   you are not sure of, have a helper review it with the critic brief
   ([launch-film/briefs/critic.md](../launch-film/briefs/critic.md), `xhigh`) before delivery.
6. **The final** only after the person approved the preview (`hyperframes-cli`), then
   `artifact-contract.mjs --expect <file>:<W>x<H>@<seconds>` and `audio-lint`. Deliver with
   `upload_files` and one line naming the calls they would not expect.

Iterating on your own sheets and draft renders is how a film gets made, not a correction round; the
two-round stop is for notes from people.

## Formats

16:9 at 1920×1080 by default; 9:16 and 1:1 are re-laid out on the same grid and score, never cropped
from 16:9. HyperFrames renders at 30 fps unless told otherwise; render a film that matches a reference
at the reference's rate, and prefer 30 fps for long films (60 doubles the render). The aspect presets
are in [motion-presets.js](scripts/motion-presets.js); placement specs in
[design-wiki](../design-wiki/references/platforms.md).

## When something is off

| Symptom | Likely cause and fix |
| --- | --- |
| A sub-composition renders as tiny unstyled text | Its `<style>` or `<script>` sits outside the `<template>` (`hyperframes-core`, sub-compositions) |
| A scene shows its initial state for the whole slot | The host's `data-composition-id` does not match the file's and its timeline key |
| A frame dips to grey or black at a cut | A dissolve between unrelated grounds, or separate clips on alternating tracks; see transitions in [craft](references/craft.md) |
| A number or word lands one frame late in one render and not another | A time not snapped to its frame (`MotionPresets.onFrame`) |
| A counter or a text swap is wrong when scrubbed | A callback that increments instead of writing state derived from its time (`video-gate` warns) |
| Motion looks fine in preview, dead in the render | Something runs on the wall clock (CSS animation, a standalone tween, a timer): `video-gate` names it |
| The render is slow | Fewer motion-blurred elements or lower blur samples; check the render summary's second line (`hyperframes-cli`) |
