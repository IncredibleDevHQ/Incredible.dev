# Hierarchy and layout

What the eye sees first, second and never, and the space that makes it so. Every item says whether
it is a checkable rule or a default to weigh.

## Hierarchy

| Principle | How to check it | Status |
| --- | --- | --- |
| One focal element per frame: the largest, highest-contrast thing is the thing the frame is for | Squint (or blur the thumbnail): the first shape you see is the subject | Default to weigh |
| Count attention demands, not elements. A field of nine related cards is one demand; a headline, a busy card and a sidebar are three | Write the demands as a list in the brief or beat sheet. One is right, two is the ceiling, three is two frames | Default to weigh |
| Supporting layers step down hard: much smaller, lighter or lower in contrast than the focal element, so they read as context | Compare sizes on the render: a support line at nearly the headline's size competes with it | Default to weigh |
| A headline plus one proof line, not a headline plus a sub-line plus a caption | Count the text blocks the ask did not supply; each is a candidate to delete | Default to weigh |
| Real product UI is proof, not copy: its small labels read as a real surface and are exempt from the copy budget | Say which text is overlay copy and which is inside a real surface | Default to weigh |
| Simplify by removing competing explanations, not the evidence of work: keep the chart, kill the caption that restates it | After a cut, the frame still shows the real thing | Default to weigh |
| Deleting is re-staging: when a cut leaves one element where three were, promote the survivor to fill the space it inherited | The surviving element grows; no hole is left | Default to weigh |
| Empty space is a feature. A frame that feels empty is missing work (more of the real surface, a larger subject), not ornament | Never add decoration to fill space | Default to weigh |

## Grids, margins and alignment

- **Use the brand's grid.** The pack's spacing unit (`--brand-space-unit`) and margins
  (`graphic-language.md`) set the grid; positions and sizes are multiples of it. Fractional box
  lengths snap unevenly to device pixels (`brand-lint` warns on `grid.fractional`).
- **Spacing encodes grouping.** Gaps grow with the level of grouping (within a line < between lines
  < between blocks < between zones, roughly doubling at a zone boundary), stay equal among peers,
  and never invert. Measure gaps between the ink, not the boxes: a large line box carries slack
  below its descenders. Default to weigh.
- **One spacing scale.** Padding and gaps come from the pack's unit and its multiples; peers share a
  value, and padding is symmetric unless the design says otherwise. An off-scale value usually
  means the structure is wrong, not that the number needs nudging. Default to weigh.
- **Margins on all four sides.** Every frame and page keeps real outer margins, bottom included,
  and nothing clips at the edge unless the piece is meant to bleed. Default to weigh.
- **A box that cannot grow takes its room from gaps, not leading.** Tightening line-height to fit a
  capped card undoes the reading comfort the leading was there for. Default to weigh.
- **One alignment system per frame.** Pick left-aligned or centred and hold it; mixed alignment reads
  as accident. Text aligns left unless the format centres it (a poster, an end card). Default to weigh.
- **Equal outer margins across a set.** A carousel, a deck or a size set holds the same margins, so
  the set reads as one family. Default to weigh.
- **Optical, not numeric.** Balance top and bottom padding by eye on the render: cap height and
  descenders make equal numbers look unequal. Grow a box rather than accept a tight one. Default to
  weigh.
- **Explicit geometry for the elements that carry the composition.** Absolutely position the few
  elements a person will want to nudge, so "move the logo up" is one property, not a reflow
  (`stills`). Default to weigh.

## Safe areas

Platform chrome covers parts of the frame. Keep the subject, the text and the logo out of it.

- **Video players** draw controls across the bottom; captions sit in the lower band. Keep the bottom
  tenth of a 16:9 frame free of anything that must be read. Default to weigh.
- **Vertical feeds** (Shorts, Reels, TikTok) overlay the caption, the account and the action buttons
  on the bottom and the right edge. Platforms publish safe-zone templates for ads; check the current
  one before a final ([platforms](platforms.md)).
- **Video thumbnails** carry a duration badge in the bottom-right corner (`thumbnails`).
- **Feed crops.** A grid or preview may show a crop of a tall image; keep the subject in the middle
  of a 4:5 or taller frame.

## Composition defaults

- **The hero is big.** In a frame with one subject, the subject spans a large share of the frame
  (roughly half the width or more); a small thing alone on an empty ground reads as dead air. Default
  to weigh.
- **The background never competes.** A ground is a colour, a quiet field or the real surface, never a
  pattern that draws the eye. Default to weigh.
- **Vary the spatial idea, not the system.** Across a set or a film, beats get different spatial ideas
  (a field of work, a wide composer, a three-part architecture, a path), while the grid, type scale
  and accent stay fixed. Do not turn every frame into the same floating card, and do not vary layout
  only to avoid repeating one. Default to weigh.
- **Taller twins spend their height on content.** A 4:5 twin of a square scales elements and gaps
  together; when width caps the type, the extra height goes into one deliberate band of air
  (`stills`). Default to weigh.
- **The phone is the default reader** for social work: design the portrait version first when the
  piece will mostly be seen on a phone. Default to weigh.

## Decks and sequences

A deck is a sequence of frames; each slide makes one point. Vary layouts slide to slide (statement,
diagram, before and after, number, screenshot) while margins, grid and accent stay fixed. A slide
number, if any, is a bare numeral, not a footer strip. Carousels follow the same rule, with the cover
as the most designed frame (`stills`, sizes and sets). Defaults to weigh.
