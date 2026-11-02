# Example Studio graphic language

The mark is a studio window: a frame, a horizon, and one light. Graphics borrow the same three
ideas, so a reader knows where to look before they read anything. The values are in `tokens.json`;
this file is how to compose with them. The concept gate (`brand-design`) comes first: these rules
finish a piece that already has an idea, and never stand in for one.

## The one idea: focus

Every Example Studio visual moves from clutter to one lit subject. Many options become one choice,
a busy screen becomes the one control that matters, a table becomes the one number. Show that
through the content itself: crop to the real thing, set the message large, or light the step that
changed. The window motif is never drawn as decoration.

## What our graphics mean

- **The frame** holds one subject. A layout is a set of frames on a quiet ground, never a collage.
- **The horizon** is the line between context and subject: the baseline of a chart, the divider
  between a headline and its proof, the edge of a stage in a diagram.
- **The light** (signal, `#ff5a36`) marks the single thing that matters most in a frame: the key
  number, the active step, the new feature. One per frame.

Pick one arrangement per piece; never stack them:

| Arrangement | What it is | Use it for |
| --- | --- | --- |
| The window | One subject, large, in a frame on a quiet ground | A product shot, a stat, a quote |
| The horizon | Context and subject split by one line | A headline over its proof, a before and after, a chart |
| The sequence | Frames in a row along a horizon, one of them lit | Steps, a flow, a timeline, a carousel |

## Two modes

Both are on-brand. Choose per piece and surface without asking: blog and docs figures, print and
editorial work sit on paper; product moments, talks and film openings can sit on ink. A set of
options may come in both, built from one theme table so the twins share their layout.

| Role | Light mode | Dark mode |
| --- | --- | --- |
| Ground | paper `#f6f1e7` (white for docs that are white) | ink `#14161a` |
| Raised surface | a sand `#e8dcc4` shell, with white `#ffffff` cards inside it | a graphite `#4a4f57` card |
| Text on a raised surface | ink | paper or mist (6.1:1 on graphite); never slate (2.5:1) |
| Text | ink (16.1:1 on paper) | paper (16.1:1 on ink) |
| Secondary text | graphite (7.3:1) | mist `#d9dde3` (13.3:1) |
| Muted labels, axes | graphite | slate `#8a8f97` (5.6:1) |
| Connectors, meaningful borders | graphite (7.3:1) | slate (5.6:1) |
| Hairline dividers only | mist (1.2:1) | graphite (2.2:1) |
| Emphasis in words | moss `#2f6b4f` (5.6:1) | sky `#8bb8e8` (8.7:1) |
| The light | signal, as a shape or fill | signal, as a shape, fill or words (5.8:1) |

- **The signal is never text on paper** (2.8:1, under even the large-text minimum). On paper it
  fills a shape, a bar, a dot or an underline; words in signal belong on ink, or on white at display
  size only (3.1:1).
- **Elevation flips between modes.** On ink a raised surface is lighter than the ground; on paper
  nothing is lighter than white, so the shell goes darker (sand) and the cards inside it return to
  white. It looks backwards and is right.
- **Step up the ladder, don't jump to the accent.** When a border or a card needs more contrast,
  move one row down this table. A signal-coloured frame around a card is a second light.
- **Hairlines are dividers, never meaningful.** Mist on paper and graphite on ink are too faint for
  a connector, a dashed boundary or a chart mark; those take the connector row.
- Moss, sky and sand fill shapes inside a frame (a field, a chart band, a chip); they are never the
  whole ground. Chart series use the extended tints in order; the signal is never a series.

## Type

One grotesk, Geist, and one mono, Fragment Mono. Hierarchy comes from size and position first, then
weight; never from a new face, an outline or an effect.

| Level | Face | Weight | Tracking | Leading | Case |
| --- | --- | --- | --- | --- | --- |
| Display (headline, the big number) | Geist | 300 | -0.02em | 1.0 | Sentence |
| Heading (a slide or section title under a display line) | Geist | 400 | -0.01em | 1.1 | Sentence |
| Body | Geist | 400 | 0 | 1.4 | Sentence |
| Label, eyebrow, caption, button | Geist | 500 | 0 | 1.2 | Sentence |
| Data, code, file names, sizes | Fragment Mono | 400 | 0 | 1.4 (1.6 for code) | As written |

- **Light display, real weights only.** The headline stays at 300 and gets its energy from size. A
  heavier look comes from a real Geist weight (400 or 500), never from stroking or outlining the
  light face. Bold display type is off-brand.
- **Labels are Geist, not mono.** An eyebrow, a section label or a field key is Geist 500 in
  sentence case, in the secondary text colour. Fragment Mono is for literal values only, at its
  single regular weight and letter-spacing 0, never forced to capitals.
- **Separators the person wrote stay, spaced like words.** If the copy says "Live | On demand",
  keep the pipe with a normal word space each side; never pad it into a gap.
- **Numbers that line up** (a table, a counter, a ticker) take `font-variant-numeric: tabular-nums`
  or Fragment Mono. Geist's default figures are proportional, so a counting number jitters without
  it.
- Left-aligned, never justified. Sentence case everywhere except names (`voice.md`).

Starting sizes at delivery size, to adjust by eye on the render:

| Surface | Size | Display | Body and labels |
| --- | --- | --- | --- |
| Square and portrait post | 1080 wide | 96-150 px | 32-40 px |
| Landscape card, blog header | 1600 × 900 | 96-140 px | 32-36 px |
| Slide | 1920 × 1080 | 110-180 px | 36-48 px |
| Thumbnail | 1280 × 720 | 120-180 px, five words at most | none |
| Email banner | 1200 × 600 | 64-88 px | 24-28 px |
| Story | 1080 × 1920 | 110-160 px | 36-44 px |
| Diagram, as a post or slide | the post or slide size | node labels 32-44 px | edge labels 24 px or more |

A diagram fills its frame inside the margins; when its labels come out under these sizes, cut
nodes or words, or turn it into a portrait or a sequence, rather than shrinking the type.

## Construction

- Grid: 8 px, with 4 px as the half step. Margins at least 8% of the frame's short edge, equal on
  all four sides; nothing clips at the edge unless the piece is meant to bleed.
- Spacing encodes grouping. Gaps grow with the level of grouping (within a line < between lines <
  between blocks < between zones, about twice at each zone boundary), stay equal among peers and
  never invert. Use 4, 8, 12, 16, 24, 32, 48, 64 and 96; an off-scale gap means the layout is wrong.
- Strokes: 2 px (`--brand-stroke`) for connectors and rules; the mark's own frame is heavier.
- Corners: 4, 8 or 12 px. A frame inside a frame steps down one size.
- Diagrams: concept first. Draw the specific mechanism (what flows where, what changes) and label
  it in words. Connectors are quieter than the words they join (the connector row above), meet
  shapes at the middle of an edge, and use one arrowhead style.
- The logo goes in a corner at the minimum size that reads, with its clear space (`brand.toml`):
  the lockup on paper, white, sand and mist; the reversed lockup on ink and graphite.

## Motion

The brand moves the way its mark is built: a frame opens, the horizon draws, the light comes on.
Motion is calm and exact; the viewer should feel things settle into place.

- **Settle.** Elements arrive by sliding a short distance along the grid (about 24-48 px at 1080)
  and settling, with `power3.out` over 0.5-0.7 s; peers follow 60-90 ms apart. No bounce, elastic
  or overshoot.
- **Draw.** Lines, horizons and chart baselines draw left to right at a steady speed (`power1.inOut`),
  before the content that sits on them.
- **Light.** The signal switches on in one frame, as a cut, and is the brightest event in the shot.
  It never fades, pulses or glows. One light per shot, meaning the same thing in every shot.
- **The signature move**, for an opening or an end card: the frame draws, the horizon crosses it,
  the light switches on, then everything holds. Frame 0 is the poster a player shows before it
  plays, so the move starts part-drawn (the frame's first side already on screen) and continues
  from exactly that state: nothing visible at frame 0 disappears or redraws later.
- **The end card and a logo sting** assemble the mark the same way (frame, horizon, light, then the
  wordmark), from the real SVG paths. The mark is the subject: about a third of the frame's width,
  centred while it builds, moving aside only when the wordmark joins. Hold 1-1.5 s on a reel or
  2.5 s on a longer film.
- **Allowed in film, declared in `STYLE.md`:** one change of mode at the turn (paper to ink or back);
  a soft falloff of light from the lit element on an ink ground; cards up to 12 px radius, as in
  stills. Not allowed: flash frames, bloom, particles, grain, chromatic fringing, a starfield, or
  any fake 3D.
- Transitions are cuts or a slide along the horizon. Copy holds still long enough to read once it
  has settled.

## Do

- Leave space. A frame that is 40% empty reads as confident.
- Show the real thing (a screenshot, a number, the output) instead of an icon for it.
- Cut words before shrinking type when a render reads busy.

## Don't

- Abstract node, dot or network wallpaper; particles; gradients as decoration.
- More than one signal-coloured element, signal-coloured words on paper, or signal text on a moss
  or sky field.
- Outlined, stroked, shadowed or glowing type; bold display type; mono eyebrows or all-caps labels.
- Drop shadows, glows, bevels, or rounded corners beyond 12 px.
- Stretch, recolor or rebuild the logo; add a tagline to it.
