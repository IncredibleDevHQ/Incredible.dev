# Directing

The creative director's lens: what makes a film worth watching and worth shipping. Read it before
the brief and the concept; the critic reads it at the concept and storyboard gates. Each point is a
default to weigh unless it names its evidence.

## Narrative first, never components first

Decide, in order, before opening the catalog:

1. **Goal**: the one action the film should drive.
2. **Audience and place**: who watches and where. A feed autoplays muted, so the film works with
   the sound off.
3. **The one message**: a single sentence. If it does not fit in one line, the film has no spine.
4. **The argument**: hook, tension, the turn, payoff, the ask, written as prose first.
5. **The visual system**: chosen once and held (one ground family or one deliberate mode change, one
   accent, one type scale, one easing family).
6. **The beat sheet and the handoff sheet** (`storyboard`): only now map beats to moves and
   components, and change each component to serve its beat. A component is a starting point, not the
   finished frame.

**The test of an argument**: read the beats aloud as one continuous sentence. Strong films break one
sentence across their cuts. If each beat is a self-contained label, you have a deck.

**The turn must be an image, not an abstraction.** Find the one concrete thing the product changes
(what nobody would hand over, what used to break, what used to take a day); the mechanism beat then
becomes the payoff of the argument instead of a feature bullet. Do not reach for a bare abstract
noun ("Control.", "Simple.") until the film has earned it.

## The hook in the first second

- Frame 0 hits: full-bleed, already moving, not a black or blank ground. It is also the poster an
  autoplaying feed or a paused player shows (`video-score` flags a blank head).
- The statement is readable sound-off within about a second.
- What moves is big. A small element trembling on an empty ground reads as a held title.
- A voiceover-led film hooks the same way: its first line spoken and on screen by about 1 s, over a
  picture already moving.

## Message hierarchy

- One headline per beat, large and at full contrast. Everything else steps down hard (much smaller or
  much quieter); one proof line may sit under the headline.
- Flat hierarchy is the signature of weak films: chips, frame counters and labels on every frame, or
  section names standing where the headline should be.
- A word on screen either carries the message or does what it says (it stretches, it splits, it
  types itself); never a caption that names the section ("Type", "Colour").

## Proof on screen

The middle of a film is the evidence for its claim: the real product UI with its data, the real
output, the number with its source. Proof must be legible: large enough on a phone, at full
contrast, held long enough to read. Every number and product claim goes in the claims ledger
(`content-brief`).

## The final frame

It is the poster, the thumbnail and the last impression. It needs who (the name or the logo), what
(the one line), what next if the format allows (one call to action), in a big, calm composition with
the motif landing as punctuation. Holds of roughly 1-1.5 s suit a short reel's last card and 2.5-3 s
a long film's end card; the logo gets its own beat or real size, not a corner under a giant headline.

## Structures

Shares of the running time, as starting shapes to bend, not templates to fill.

| Type | Length | Cut to | Shape |
| --- | --- | --- | --- |
| Sting, logo reveal, loop | up to 10 s | music | One move that resolves; a loop's last frame is its first |
| Reel or teaser | 15-30 s | music | Hook and motif (first bar), a roll call of moves, a build, the drop on the final card |
| Feature film | 30-60 s | music or voiceover | Problem and turn, the product enters, two or three proofs, the end card |
| Launch film | 60-120 s | voiceover over a track | The problem and the turn (about an eighth), the name and its promise, the one system diagram, chapters that each prove a stage (about a third), the new thing as the climax, the end card |
| Explainer | any | voiceover | One diagram built up as the voice names each part, with reading holds |

**Speed up, slow down, hold.** Alternate expressive and quiet passages; a quieter evidence passage is
what makes the next large move feel large. A film with one shot length is flat.

## Declaring the holds (`AUDIT`)

A film says how still it means to be, in `timeline.js` or the beat table, so a reviewer can tell a
chosen hold from dead air. The presets are defaults to weigh, not gates:

| Preset | For | What it expects |
| --- | --- | --- |
| `reel` | Music-cut reels, teasers, stings | Something changes on nearly every beat; holds before the final card stay short (well under a second); the final card holds about 1-1.5 s |
| `launch` | Voiceover- or copy-led films | Holds while copy is on screen, each as long as its reading time (a few seconds at most); the end card holds 2.5-3 s |
| `explainer` | Explainers built up as a voice names each part | Reading holds on the diagram as each part lands; about 2 s on the end |
| `loop` | Loops | No final hold: the last frame is the first, velocity included |

`AUDIT = { preset: "launch", holds: [[41.2, 44.0, "the dashboard reads"], [57.5, 60.0, "end card"]] }`.
Each hold carries its reason. `video-score`'s findings inside a declared hold are accepted and named
in the delivery note; one outside every hold is a fix. Judge stillness at the delivery frame rate.

## Pacing by attention job

Set each passage's length from what it asks the viewer to do, never from a cadence number lifted
from a reference film.

| Job | Length follows |
| --- | --- |
| Recognition | Short: as soon as the thing is recognized |
| Reading | Reading speed. A published subtitle ceiling is 20 characters a second for adults (Netflix English Timed Text Style Guide), so a 40-character line needs at least 2 s settled, plus a beat; a typed command needs much longer |
| Action | The action's own duration plus its result landing |
| Spatial change | Long enough to re-orient, no longer |
| Release | Deliberately quiet; it makes the next move feel substantial |

Three different requests, three different edits:

- **"Slow the whole film"** means more frames, never fewer: scale every position and duration and the
  root duration by the factor and render at the same frame rate. Dropping the frame rate for the same
  motion judders.
- **"It's hard to read"** grows the intervals and holds; entrances lengthen only a little.
- **"This beat is too long"** cuts the settled hold, never the entrance, and moves later beats earlier
  so the film gets shorter.

## Voiceover-led or music-led

Decide this first; it changes the sync spec, the analysis and what "on time" means.

| | Music-led (reel, teaser, sizzle) | Voiceover-led (launch film, explainer) |
| --- | --- | --- |
| Sync spec | The beat grid: one line per beat or half beat | The words' start times: copy lands on or just before its word |
| Cuts | On beats and bar lines | On phrases and on a few designed hits |
| Change rate | Something visible on every beat | Every phrase; reading holds are part of the design |
| Tempo | 115-128 BPM for kinetic work | Whatever sits under the voice |
| Stillness | Little: holds are short | More: holds while copy is on screen are expected (declare them in `AUDIT`) |
| Analysis | Choose or map the grid (`film-breakdown`, `analyze-audio.mjs`) | A word-timed transcript (`transcribe_audio`, or `generate_voiceover`'s word timings), plus the track's grid and hits |

A voice shows as speech-shaped bands in a spectrogram; if a reference has one, its words are the sync
spec, and timing it to the beat grid alone would mistime the film.

## What premium films usually leave out

Defaults to weigh:

- The product is rarely the grammatical subject of the on-screen copy; there is no narrated feature
  tour. Copy is a bare noun, an imperative to the viewer, or the user's own words inside the UI.
- A task is shown happening inside the product, not announced as a title.
- At most one number in the overlay copy; numbers inside real UI are proof, not copy.
- Premium is as much what you leave out: extra effects, a sound on nothing, the wrong music.

## What weak films miss

- Sound (a silent film reads unfinished), or sound that ignores the picture.
- Motion between poses: animating into a poster frame and holding it.
- A claim instead of a label, and showing instead of labelling.
- A hero that fills the frame; a signature and a next step on the last frame.
- Legible proof.
- Spending the remaining time on the moments the maker already knows are weakest.
