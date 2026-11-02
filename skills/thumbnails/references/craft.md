# Thumbnail craft

Observations that tend to cost several rounds when missed. When the person in front of you asks for
something else, do that.

## A person in the frame

A face belongs to someone who is in the video: the speaker, the host, the guest. A named presenter
tends to help; an anonymous face does not.

- **Source.** The sharpest frame from the footage (no motion blur, natural expression, not mid-word),
  a photo they supplied, or a headshot they approve. Offer several candidate frames rather than one.
- **Cut out** with `hyperframes remove-background portrait.png -o cutout.png` (see `media-use`), then
  trim to the subject. The model can keep stray objects (a chair back, a neighbour's shoulder); erase
  them inside a band clear of the face and jaw, then look at the face again. When a neighbour merges
  with the subject, drop the cut-out: crop the original tight to face and shoulders and soften the
  backdrop instead. Crop out background lettering.
- **Edges.** A cut edge either bleeds off the frame (anchor the subject past the bottom edge) or falls
  into natural shadow. Feathering reads as a masking artefact. Inspect hair and shoulders in a zoomed
  crop (`visual-verify`), not the whole frame.
- **Grade** to the ground: a slight brighten and a gentle S-curve that keeps the skin's own hue. A
  cool grade or a blend toward a brand tint reads as a colour cast. If one source is monochrome,
  taking the whole set to black and white matches them.
- **Scale.** First drafts tend to make the person too big and the title too small. The title still
  has to read at rail size beside a face.
- **Decorative particles** stay off the person entirely.

## A product screen in the frame

- The app only: no recorder backdrop, player bars, cursor trails or face bubble.
- Sharp at the size it is drawn: capture at 2× or 3× the drawn width, or ask for one. `thumb-gate`
  flags a raster drawn wider than its pixels.
- One background: the screen sits on it, often bleeding off one edge, sometimes in a device frame at a
  slight angle. A separate panel behind it reads as a second background.
- Crop to the part that proves the claim, larger and squarer; at rail size nobody reads a full window.

## Type and layout

- One left edge for the mark and the title; optical vertical centring; air between the mark and the
  title. A 12 px misalignment reads as careless at full size.
- Judge type size in the small-size sheet, not by a number: too big crowds the frame, too small
  vanishes on the rail.
- Text never crosses the graphic, and nothing important sits under the duration badge.
- When the words are yours to write, they can state the payoff rather than repeat the title; that is
  itself a good A/B bet.
- A light stroke on a dark ground is the first thing to disappear on the rail; check it there.
- No footer, URL, date, border or edge bar.

## Quotes

- The speaker's own words, word for word, from the transcript.
- Two lines at most, about 25 characters each. Curly quotes; a full stop only for a full sentence.
- The title carries the subject the quote leaves out, so the pair reads together.

## Diagrams and generated imagery

- A diagram in the frame comes from `data-viz`, carries no text, and sits back so the title leads;
  the thumbnail should still read with it removed.
- Generated imagery can carry the whole frame: a scene, a hero object, a concrete metaphor. Leave text
  out of the generation and set it in HTML on top. What costs trust is the generic look: glossy
  sameness, over-saturation, synthetic people, fake UI. Give the prompt a specific idea, a medium and
  a light source (`image-generation`).
- Draw any graphic at final size; an upscaled small asset reads as grainy.
