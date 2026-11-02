# Storyboard for a launch film

The board is where the person approves the argument, the copy and the look before anything expensive
happens. A note here costs minutes; the same note after production costs an hour or more. Follow the
`storyboard` skill (intake, the argument, the beat and handoff sheets, poses from real HTML, one
contact sheet, sign-off). A launch film adds the pieces below.

## 1. The argument, with its parts named

Before any frame, write the film as one paragraph that reads as a single continuous sentence. Then
name:

- **The hook**: complete inside the first second.
- **The turn**: the one concrete thing the film pivots on, as an image.
- **The proof**: what the viewer sees that makes the message true: the product surface, the real
  diagram, the number with its source.
- **The resolve**: the final frame, big and calm, on a downbeat or the last word.
- **The motif**: one element that threads every act and resolves at the end, taken from the brand's
  graphic language where it has one.

Every number and product claim on a frame goes in the claims ledger in `BRIEF.md` with its source and
whether it is verified. An invented number under a real-looking label is a credibility failure.

## 2. The shot list

One row per shot, on top of the beat sheet's fields:

`# · in-out (s) · copy (verbatim) · focal object and layout · camera and motion · transition out, and what crosses the cut · lands on (word, hit or downbeat) · sound`

- **Attention demands**: list each separate thing the viewer must read in the frame; more than two is
  two shots.
- **The change** is the load-bearing field: say what develops after the entrance and what the viewer
  learns from it.
- **Carriers**: for every cut, what crosses it, or `semantic handoff` and what the handoff is.
- **Pace follows the attention job** (recognition short, reading at reading speed, an action plus its
  result, a release that is deliberately quiet; `motion-direction`, directing). A film with one shot
  length is flat.

## 3. Frames: pick a source, render the sheet in the sandbox

| Source | Use it when | How |
| --- | --- | --- |
| **HTML poses** (the default) | The film is type, UI, diagrams and product surfaces in the brand | One page per key frame in `storyboard/frames/NN-name.html`, styled from `/workspace/brand/tokens.css`, with real copy and the real logo; render with `html2png.mjs --brand-fonts` (`storyboard`) |
| **Snapshots of a blocking pass** | A rough `index.html` already exists, or the film is a recreation (the reference's shot list is the board) | `hyperframes snapshot --at <the BOARD times>` |
| **Look plates** | The concept is a look the HTML cannot sketch quickly: light and glass, a 3D world, a physical metaphor | `image-generation`: explore at low quality, finish the plates you show; no text, no logos in the prompt; composite each plate under real type and the real logo in the HTML pose |

**Look plates are look targets, not layouts.** A builder matches a plate's light, material, depth and
palette and redraws everything else in the brand. Label them on the sheet ("look, not frame").

When Paper is connected, mirror the HTML poses onto the canvas so the team can nudge them (the Paper
skill, `paper-design`). The thread always gets the rendered sheet, whether or not Paper is connected.

**The sheet**: frames of the film's aspect in a 3×3 or 4×3 grid, at most 1,500 px on the long edge so
every page stays legible after the review downscale (`review-thumb.mjs --sheet`); under each frame its
number, time range, verbatim copy, a motion note and its sound event; a header with the title, the one
sentence, the length, the tempo or voiceover, and the formats. A paged PDF of the sheets through
`html2pdf.mjs` when the person wants one file.

## 4. Tie the board to the grid

Put the frames in `timeline.js`, so the board, the animatic and the final can never disagree on
timing:

```js
export const BOARD = [
  { id: "04-proof", t: beat(32) + 1 / FPS, words: "Every export, in one pass", motion: "push into the dialog", sound: "impact", carrier: "dialog" },
];
```

Each time is a beat (or a word start) plus one frame, so the still shows the moment just after the
event. The same times drive the animatic, and they become each builder's acceptance stills: the
builder snapshots its act at its `BOARD` times and compares them with the approved poses.

## 5. The music plan (on the sheet)

- **Tempo from the mood**: cinematic 60-80 BPM, smooth 90-110, kinetic 115-128 (reels, sizzles,
  energetic launches). A voiceover-led film takes the voice's rhythm with the music under it.
- **Where the accents fall**: the hook hit, the turn, the drop, the final chord on the end card, and
  the silence before the last hit if the film uses one.
- **A supplied track wins.** Map its beats first (`film-breakdown`, `analyze-audio.mjs`), then fit the
  shots to its sections.
- **With voiceover**, generate the lines now (`generate_voiceover`): the film is cut to them, and timing
  locks at the animatic.

## 6. Critic check, then send

A critic ([briefs/critic.md](../briefs/critic.md), `xhigh`) checks the board at the storyboard gate.
Cut anything that fails: the hook in a second; one idea, one motif, one accent; proof on screen; two
attention demands or fewer per frame; a carrier or a named handoff at every cut; a calm resolve.

Then `upload_files` the sheet pages (and the PDF), and put the ask in the reply:

> Storyboard for the 60 s launch film: 11 shots, 118 BPM, voiceover on shots 3-9.
> The idea: one export dialog pulls every scattered format into one pass, and it lands on the logo.
> Frames 4 and 7 are look plates: the light and material, not the layout.
> Once you approve, I'll cut the animatic on the music (~35 min); timing locks after that.

Keep in `storyboard/`: the approved sheets, the frame HTML, the plates, and the Paper file and artboard
references if there is a canvas copy. They are the spec the builders measure against.
