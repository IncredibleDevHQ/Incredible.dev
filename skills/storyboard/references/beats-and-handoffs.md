# Beat sheet, handoff sheet, craft review, camera

## The beat row

`takeaway · exact on-screen words · focal object · attention demands (listed) · the change · observable
result · incoming carrier · outgoing carrier · read window · sound accent · source claim`

- **Attention demands**: name each separate thing the viewer must interpret (`headline / trace card /
  sidebar` is three, over the ceiling). Written out, an over-full frame is obvious an hour before the
  render shows it. A beat that needs a third demand is two beats.
- **The change** is the load-bearing field. "Title appears, cards fade in" has no work yet: rewrite
  it or cut it.
- **Carriers** name the object that crosses each boundary. Where nothing genuinely spans the cut,
  write `semantic handoff` and say what it is (a question answered by its result, a match cut, a
  preserved motion direction).
- **Read window**: how long the frame must hold for its words at a calm reading pace, plus a beat.
- **The opposing case at its strongest.** In an A-versus-B explainer, build A at its best, then show
  why B still wins. A strawman makes the film untrustworthy to the people who know A.

## The handoff row (one per cut: this is the film)

`carrier id · what it leaves as · what it arrives as · screen bounds at the join · content it keeps ·
path · duration · easing · velocity at the join · what clears and when · who owns the transform ·
z-order`

Every cut gets a row. A row may say `semantic handoff, no carrier`; it may not say nothing. A cut with
no row is a jump cut wearing a crossfade.

## Craft review (before presenting)

- **Squint.** Defocus a frame: one thing to interpret is right; two is the ceiling.
- **Work, not decoration.** The frame shows recognisable work (a real report, a real surface, real
  labels), not a sentence with ornament around it.
- **Concept, not primitives.** If the only thing making a frame on brand is that it contains brand
  shapes or generic nodes and dots, the frame has no concept.
- **Restraint.** One accent per frame, carrying meaning. No effects on type. No trailing full stops
  on headlines.
- **The change.** Name what develops after the entrance in every beat.
- **The carrier.** Every cut has a row, and the midpoint pose shows the object mid-handoff.

## Camera: build it or drop it

A camera move that exists only as a word in a beat row never gets built: the builder receives a pose,
and a pose has no camera. For any beat whose framing changes:

1. It ships two poses (start and end framing), not a label.
2. The board names the wrapper that owns the move, and the focal point and transform origin measured
   on the rendered pose, so the zoom lands on the element rather than empty space.
3. The handoff row names the transform owner. One owner per property: the camera lives on one
   parent, local motion on its children. Two rigs writing the same property is jitter.

Camera moves are native to the composition (a GSAP scale with a transform origin on one wrapper),
never a zoom added in post. A beat that does not need a framing change does not get one: there is no
zoom budget. When the content wants it, scale progresses with purpose (control, component, whole
result, collection). The camera holds still while the viewer reads.
