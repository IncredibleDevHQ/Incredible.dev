# Review rubric

How to judge a still, a set, a slide, a chart or a single frame, at a review gate or before you
deliver. Films add story, pacing, sound and finish areas: the film rubric is
[motion-direction's review page](../../motion-direction/references/review.md), and a film critic
scores both.

The rubric is a reading aid for judgment, not a scorecard to optimise: a piece that hits every
anchor and still reads like generic marketing scores low on Idea. The thresholds are defaults to
weigh; the verdict rule is the team's convention, not a measurement.

## Before any score: three gates

1. **Accuracy.** Every product claim, number, name and quote on the piece traces to a source in the
   brief's claims ledger. An invented feature or figure fails the piece outright, however well it is
   made; craft judges cannot catch it, so check it against the source.
2. **Deterministic gates.** `brand-lint` (and `--copy`), `artifact-contract` when there is a
   contract, the renderer's font check, and for charts the `data-viz` gates. Exit 1 is a finding to
   fix; exit 2 means the gate did not run, which is never a pass.
3. **The ask.** When someone asked for a specific change, that change is the bar: check it first.

## Regenerate the evidence

Never score from the maker's own sheet or self-score. Render or crop your own views: the full frame
at review size (`review-thumb.mjs`), the set on one sheet, the smallest view it will get (a phone
width, a thumbnail rail), zoomed crops of type and fine geometry, and for a restyle the source tiled
before the output (`visual-verify`).

## The six areas

Score each 1-5; 4 and 2 sit between the anchors. Cite the crop, the size or the number behind every
score.

| Area | 5 | 3 | 1 |
| --- | --- | --- | --- |
| **Idea** | One sentence a stranger repeats; the concept is a real thing shown, a specific idea or bold type, and survives the kill test | A real message, but the visual idea is generic or arrives as decoration | No message; brand shapes or a network field standing in for a concept |
| **Hierarchy and clarity** | One focal element read first, at most two attention demands, support stepped down hard | Readable, but two elements compete or the support is too loud | Flat: everything at one weight, or labels where the headline should be |
| **Copy** | Fewest words; each fact once; supplied copy exact; casing and voice from the pack | An unrequested sub-line, caption or footer; a word too many | Invented copy, hype the voice bans, or supplied copy changed |
| **Craft** | Type sized for the delivered view, optical spacing, clean geometry, no widows, nothing clipped | Correct but stock: default spacing, tight padding, one awkward wrap | Clipped or garbled text, broken connectors, misaligned grid |
| **Brand** | Tokens only, one accent with meaning, the real logo at its size and clear space, ground chosen for the surface | A slip: a second accent, a radius past the pack's maximum, the logo too small | An invented colour, a redrawn or recoloured logo, off-brand faces |
| **Fit for place** | Right sizes, each recomposed; legible at the smallest view; safe areas clear; the set reads as one family | One size scaled rather than recomposed, or small text lost on a phone | Wrong size, cropped subject, or text under platform chrome |

**Verdict** (convention): **ship** when every area scores 4 or more; **fix, then ship** when none is
below 3 and every must-fix note is concrete; **rework** when Idea scores 2 or less, or any area
scores 1.

## Notes

At most twelve, ranked by impact. Each note has: where (the file and region, or the timestamp), what
is wrong, why it matters to the viewer, and the concrete fix. Mark each MUST-FIX or NICE-TO-HAVE.
Then name the strengths the next pass must protect, so a fix does not break what works.

## Failure patterns

| Pattern | What it looks like | Fix |
| --- | --- | --- |
| Wallpaper | A headline over a field of nodes, dots or glows | Find the real thing to show, or let bold type carry it |
| Over-full frame | Three or more things to read separately | Split into two frames, or cut the weakest |
| Flat hierarchy | Headline, labels and support at similar sizes | One element big and at full contrast; the rest step down hard |
| Extra words | A sub-line, caption, URL or eyebrow nobody asked for | Delete it; put the explanation in the reply |
| Scaled, not recomposed | A portrait version that is the landscape layout shrunk | Recompose each size; spend extra height on content |
| Template sameness | Six slides that are one layout recoloured | Vary the spatial idea; keep the system |
| Lost on a phone | Proof text that is 7 px on a 360 px screen | Fewer words, larger type, a narrower canvas |
| Unofficial logo | A typeset stand-in or recoloured mark | The real file from the pack, at its minimum size or larger |
| Generic software look | Mono on prose, all-caps mono eyebrows, bold display type, everything centred, floating columns with no container, glows | Same elements and copy: retreat mono to literal values, set labels in the text face, the display weight the pack names, one alignment, real containers, no effects. Name the diagnosis in one line |
| Faked weight | A light face stroked or outlined to look heavier | A real weight of the face, or more size |
| Self-review | "It's fine" from the maker | An independent look with fresh evidence |

## Writing the review

`review/REVIEW-<gate>.md` in the project: the verdict, the six scores with their evidence, the ranked
notes, the strengths to protect. When a pipeline reads the verdict, end with the JSON its brief asks
for. Read-only on everything else: a reviewer judges, it does not fix.
