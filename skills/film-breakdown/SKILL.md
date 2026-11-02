---
name: film-breakdown
description: Measure a film someone hands you (cuts, contact sheets, motion energy, beat grid, colours) and compare a recreation against it frame by frame. Use for "recreate this", "make one like this", "what makes this work", "match this pacing" or "time it to this track".
---

# Film breakdown

Four scripts turn a film into numbers and review images, all Node plus ffmpeg:

- `breakdown.mjs`: cuts, sheets, stills, motion energy, the soundtrack, a draft shot list and timeline.
- `grab.mjs`: frame-exact stills.
- `analyze-audio.mjs`: a soundtrack (or any music track) to a beat grid, hits and loudness.
- `compare.mjs`: a recreation against the reference, after every change.

Scripts live in `/workspace/skills/film-breakdown/scripts/`. A reference film is someone else's
work: study it, never ship its frames, footage or copy. Teardowns go to `/workspace/references/`
(see `reference-study`). Big productions run through `launch-film`; the picture is a HyperFrames
composition (`hyperframes`, `motion-direction`).

## Pick the job

| The ask | Run | Then |
| --- | --- | --- |
| "Recreate this video" | the whole method below | build it act by act, compare after every change |
| "Make one like this" | breakdown, then read the sheets and the draft shot list | lift the cadence, grid, palette logic and transition types; write your own content on them, in the brand |
| "What makes this work?" | breakdown | answer from the numbers: cut rhythm, where cuts land on words and hits, the energy arc, the recurring systems |
| "Match this pacing" or "time it to this track" | `analyze-audio.mjs` on the track, plus the reference's cut list | paste BPM, GRID0 and HITS into the project's `timeline.js` |

## 1. Break it down, then look

```bash
S=/workspace/skills/film-breakdown/scripts
node $S/breakdown.mjs /workspace/attachments/<file> /workspace/projects/<slug>/ref
```

Review images are at most 1,500 px and every tile is labelled `time f<frame> #<shot>`. Read them in
this order (one `look` per sheet group, not per frame):

1. `sheets/overview-1fps.jpg`: the whole film. Hard cuts have red borders.
2. `sheets/section-NN_*.jpg`: 4 fps, 5 s a sheet.
3. `sheets/cut-NN_*.jpg`: 10 fps around each cut. The last frame before the cut has an orange
   border, the first after it red.

`stills/` holds full-resolution frames: n-1, n, n+3 and n+10 around every cut, plus each shot's
first and middle frame. Take positions and colours from these, never from sheets.

`breakdown.json` holds every number: `cuts[]` (frame, time, confidence, grid position, the hit or
word it lands on), `transitions[]` (frames that looked like cuts but are blends, steps or tails, with
the reason), `moves` (whips and fast moves), `shots[]` (palette, motion, sound per shot), `motion`
(per-second energy and the still-frame audit) and `audio`.

## 2. Finish the shot list

`SHOTLIST.draft.md` arrives with everything measurable filled in. Replace every `____` by eye.
Shots are the hard-cut segments, split at fast moves inside them; the splits are suggestions, so
merge or split where the idea changes. Write copy verbatim.

The format: a header (path, codec, size, rational fps, duration, frames, audio); **Sound** (grid:
BPM, beat, origin, downbeat and local shifts; loudness; strongest hits; voice-over word starts,
which are the sync spec for copy); **Hard cuts** (each with frame, confidence and what it lands on,
then one line on what is continuous instead); **Look** (grounds and accents, light and texture, type
face, weight and size in px, recurring systems); and **Shots**:

| # | In-out (s) | Copy (verbatim) | Layout / content | Camera / motion | Transition out | Sound it lands on |
| --- | --- | --- | --- | --- | --- | --- |
| 8 | 11.51-14.55 | "Ship on Friday" | Dark ground, one accent circle enters from the left edge; headline x 1040-1336 at y 532 | Circle grows 11.5-12.0, near-static hold, 14.3 a line extends right and the camera follows | Pan right along the line | Cut on beat 21; word "Friday" 11.64-11.88; hit 13.35 |

Positions in px, camera fits and sampled colours are measured, not eyeballed.

## 3. Freeze the grid

`timeline.draft.js` starts the project's `timeline.js`: `FPS` (rational), `DUR`, `CUT_FRAMES`,
`CUTS` (half a frame early, so a frame never straddles a cut), `SHOTS`, `BPM`, `BEAT`, `GRID0`,
`beat(k)`, `DOWNBEAT`, `HITS` and `VO`. Scenes read their times from it and never hard-code them.
Render at the reference's rate (`hyperframes render --fps 30000/1001`). For a person's own track,
run `analyze-audio.mjs --js timeline.snippet.js` on it and paste the result.

Voice-over words: the sandbox has no Python speech model, so `breakdown.mjs` skips its word pass
with a note. Use the host tool `transcribe_audio` on the reference audio and read its word
timestamps instead, or transcribe the copy from the stills.

## 4. Measure, don't eyeball

- `grab.mjs <video> <t1,t2,...|f123> <outdir> [--scale w] [--jpg] [--sheet]` gives exact frames at
  the poses that matter.
- Read positions and sizes in pixels off the full-resolution PNGs (an ffmpeg crop, or
  `image-ops --crop`).
- Sample colours at named points, then map each to the nearest brand token; never carry a
  reference's palette into the brand's work.
- Fit cameras from geometry. Four items 90° apart on a ring give the projected ellipse's axes, and
  elevation = asin(ry / rx).

## 5. Build, then compare after every change

Inner loop, seconds: `hyperframes snapshot --at <t1>,<t2>,...` on your composition, `grab.mjs` on
the reference at the same times, then one sheet of both (`node /workspace/tools/review-thumb.mjs
--sheet ...`). After a draft render, the full comparison:

```bash
node $S/compare.mjs --ref <ref.mp4> --mine renders/draft.mp4 --times 12.51,25.49,37.5
node $S/compare.mjs --ref <ref.mp4> --mine renders/draft.mp4 --from 45.15 --to 56.26 --every 1
```

It writes, on the reference's clock: `pairs-N.jpg` (REF above MINE with SSIM per pair; read it every
time), `side-by-side.mp4` with timecode and frame number (`--no-video` skips it), and `compare.json`
with per-second motion energy for both, its correlation and global lag, the seconds with the largest
energy deltas, windows whose timing is off, hard cuts matched frame by frame (`exact`,
`missingInMine`, `extraInMine`) and both still-frame audits. Fix the biggest delta first: one second
far above or below the reference usually exposes one element at the wrong size or time.

## Handing acts to parallel builders

Split at hard cuts only: every delegated boundary is a `CUT_FRAMES` entry. An act that crosses a
continuous move stays with one builder. Each brief carries the act as `[C.a, C.b)` from
`timeline.js`; its shot-list rows, section sheets, the cut sheets at both ends and full-resolution
stills of its key poses; the words and hits inside its range; the shared modules' real exports
(read-only); its compare commands with `--from` and `--to`; and what to report back: the pairs
sheet, fidelity 1-5 per shot with a one-line reason, and what did not match and why.

## Fidelity, 1-5 per act

Score from `compare.json` first, then look at the pairs and watch the side-by-side at full speed.

| Score | Means | Typically measures |
| --- | --- | --- |
| 5 | Indistinguishable at playback | every cut exact; motion r ≥ 0.98; layout within a few px |
| 4 | Same shots, copy, layout and timing; only material and light differ | cuts exact; r ≥ 0.95; positions within ~1% of the frame |
| 3 | Same beats in the same places, layout close; some elements designed to read the same rather than traced | cuts within 1-2 frames; r ≥ 0.85 |
| 2 | Recognisably the act, but timing or layout visibly off, or elements missing | cuts more than 2 frames off; energy peaks in the wrong second |
| 1 | Only the order of ideas and the rough palette survive | |

## What the numbers are, and their limits

- **Cuts** need three things: a high scene score, a frame difference that spikes against the 5
  frames either side, and a frame that is not halfway between its neighbours (which rejects fades,
  dissolves and flash decays). Between dark pictures the scene floor drops, but only when the change
  is extremely isolated. A word swapped on a constant ground reads as a `step`, not a cut. To tune:
  `--cut-threshold`, then `--scene-floor`, then `--min-shot`.
- **Grid.** The onset envelope follows librosa's, so times line up with a librosa analysis. The
  origin is where onset energy peaks; drum attacks can sit 10-20 ms earlier, under a frame at 30 fps,
  so check by ear where a downbeat must be frame-exact. Downbeats are often `ambiguous` under a
  voice-over. `drift.shifted` flags edits in the music.
- **Motion energy** is the mean luma of the blurred frame difference at 160 px, per frame pair,
  parsed as floats (ffmpeg prints tiny values in exponent form).
- **Colours.** YUV is converted with the matrix the file declares (BT.709 for HD), so samples agree
  across ffmpeg versions. JPEG stills are re-encoded as BT.601 full range, which JPEG decoders assume.
- **Variable frame rate** (screen and phone recordings): frame maths uses the average rate and
  `grab.mjs` falls back to seeking by time.
- **Runtime.** A breakdown is one decode pass plus audio in parallel; a full compare decodes both
  films. On a long or 4K film, run them as a background job and keep working.
