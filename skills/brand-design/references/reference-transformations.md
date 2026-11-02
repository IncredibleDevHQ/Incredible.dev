# Reference-faithful transformations

Use this contract when the ask says restyle, reskin, clean up, make it on brand, resize, or
otherwise transform an attached visual. It differs from a new asset: the reference already owns the
information architecture, and your job is to change its visual language without changing what it
says.

## Priority order

When rules pull in different directions:

1. The person's explicit instruction for this deliverable.
2. The reference's information and meaning.
3. The active brand pack.
4. Skill and template defaults.

Brand compliance changes the look. It does not grant permission to change the message.

How to read the person's instructions:

- **An explicit revert beats the principle that produced it.** If someone rejects an asset built
  from a rule they stated earlier, follow the revert and do not re-derive the old rule next time.
- **Pasted data is the data.** A pasted payload, table or list ships verbatim and in its order.
  Withdraw any "better" illustrative substitute in one line, then find the angle that makes the real
  data teach the point.
- **Their own sketch is the spec.** When someone posts a wireframe after you delivered directions,
  rebuild to their structure; keep only your typography, geometry and connector discipline.
- **A message that restates the whole deliverable is a respec, not a patch.** Build what it names, in
  its order, and mark the earlier requirements it leaves out `superseded` in the contract. A note that
  changes one thing is a patch: everything else persists.
- **Follow-on edits are part of the instruction.** Spelling out an acronym removes the legend that
  defined it; moving art into a box whose title already says the thing makes its old label redundant.
  Make the follow-on edit in the same pass, say so, and offer the removed element back in one line.

## Lock the source before composing

Start `projects/<slug>/artifact-contract.json` from
[artifact-contract.example.json](artifact-contract.example.json) before editing anything. The
inventory is the checklist of everything the output must still carry:

- every visible string, number, product or model name and annotation, verbatim;
- cards, marks, icons, labels, tags and diagrams;
- hierarchy, grouping, reading order and connector relationships;
- colours that encode a real state or category (not decoration);
- the requested output size and mode, and the allowed additions, removals and changes.

If the person did not authorize a content change, the allowed additions, removals and changes are
empty. Each later review note becomes its own requirement with its own id; never summarize earlier
requirements away. Check the contract before composing:

```bash
node /workspace/tools/artifact-contract.mjs --contract projects/<slug>/artifact-contract.json --phase plan
```

Do not ask whether to drop a source element to simplify the composition. Ask one question only when
the reference and the ask genuinely conflict, or the answer would change meaning.

## Measure proportions, not absolute offsets

Faithfulness is a ratio. Measure these on the source before rebuilding, and check the rebuild
against them:

- **Spacing ratios.** An uneven stack (a large gap, then a small one) keeps its ratio at the new
  size. Reproducing the intent at a new scale can quietly double the ratio when one gap has to absorb
  a taller element; compute both.
- **Annotation clearance.** A note sits against what it annotates. Measure the source's clearance and
  keep it; then check both directions (each note's distance to its target, and that no target falls
  inside a note's box).
- **Semantic colour families.** Two tinted families in a source usually mean two categories. Find
  out what they are before recolouring and map each to its own brand colour; flattening them to one
  colour erases the categories.
- **Element count.** Count the source's elements and do not exceed them. More detail is not more
  faithful; it is a different design.
- **Alignment.** Copy the source's alignment. Left-aligning a centred three-up leaves a dead strip
  down one side even when every label is right.

## A source that is already on brand

A diagram taken from the brand's own site or deck often already uses its colours. Count its colours
first (`ffmpeg -i source.png -vf palettegen=max_colors=16 swatch.png`, then look at the swatch).
When every odd value turns out to be a
low-opacity blend of a brand colour over a brand ground, the palette needs nothing and the real job
is elsewhere. What such sources usually still need is copy and asset work: decorative separators in
sub-lines, mono used for prose, an all-caps label, a missing or unofficial logo.

**"Make it look less generated"** is a transformation with a known diagnosis, not a redesign: same
elements, same copy. The usual tells, strongest first: mono type on prose, heavy display weights
the brand does not use, fallback faces shipped in a final, all-caps labels, floating columns with no
container, everything centred, glows and other effects. Change those and name the diagnosis in one
line; it is the part the person cannot see.

**Check the source's logos.** Exports often carry a typeset stand-in for the real mark. Crop each mark
at full resolution and compare it with `/workspace/brand/logos/` before assuming it is real; replace a
stand-in with the real file and say why the mark differs from the reference.

## Additive edits: "add a title, change nothing else"

The source pixels are the contract. Extend the canvas and composite the source raster unchanged under
the new element (`image-ops`); do not rebuild the figure or embed it in a page you re-render, because
the renderer resamples it.

- Match the figure's own system: its margins, its left edge, its type ramp by cap height, its weight
  (read from stem width).
- The gap between the new title and the figure exceeds the figure's largest internal gap, or the
  title reads as another row.
- Zero changed source pixels is the answer to "change nothing else".

## Transformation rules

- **Preserve by default.** Do not add, remove, rename, summarize, reinterpret or reorder source
  content, including titles, eyebrows, footers, badges, annotations and product names.
- **A logo is content.** Keep a source logo; add, replace, move or remove a mark only when the person
  asks or a named delivery spec requires it. "Social asset" and "on brand" do not by themselves call
  for a new logo.
- **Supplied official assets are immutable.** Use the supplied bytes, colours, proportions and
  geometry. Reference the file as an image when inlining it would invite recolouring or path edits.
  If the exact asset cannot be used, stop and say so.
- **Recompose for the target ratio.** The output keeps the source's size unless the ask names another,
  and a revision never drifts from it. For a new ratio, scale type and components, reflow, and balance
  margins; never fill the space with new copy, branding or decoration.
- **Translate colour without losing meaning.** Use the pack's primary palette; where categories or
  states need distinguishing, use its extended palette semantically, with the brand's primary colour
  as the anchor.
- **Finish typography at the delivered size.** Casing from the pack, never forced with CSS; proper
  nouns and exact product names kept; supporting text, sub-lines and corner tags scaled for the final
  canvas; no one-word last lines.
- **No generic decoration.** Do not add dot grids, node clouds or network wallpaper. Keep such a motif
  only if the source has it, or where nodes encode real data or relationships (mark them
  `data-brand-role="diagram"` so the lint can tell a diagram from filler).
- **The brand's fonts, or nothing.** Render with `--brand-fonts` (or `--require-font`); a missing
  face fails the render and is reported, never replaced by a fallback.
- **Judge spacing optically**, on the render. Grow a card or reflow it when the numbers look right and
  the result still looks tight.
- **Calibrate component shape.** Not every label is a pill: match a tag's radius to its card and the
  pack's maximum radius, one clean outline, consistent alignment.
- **Make geometry intentional.** Axis-aligned connectors stay dead straight; return paths are clean
  computed curves; arrowheads land on their shapes; no connector crosses text. Do not invent an
  arrow-weight or dash system from one reference.

## Verify source and output together

Once, on the final render:

1. Tile the source first and the output second:
   `node /workspace/tools/review-thumb.mjs --sheet <source> <output>`, then `look` at the sheet with
   the inventory in hand.
2. Every source item is accounted for, every output-only item was authorized, the size and the
   allowed changes are honoured, and each requirement has evidence you inspected.
3. Check it at preview size too: a label that vanishes in a feed preview is not legible.
4. The final gate fails closed while any requirement lacks evidence:
   `node /workspace/tools/artifact-contract.mjs --contract projects/<slug>/artifact-contract.json --phase final`.

## Acceptance checks

A correct transformation shows all of these:

1. **Preservation**: every source label, card, annotation and relationship remains; no new copy.
2. **Logo boundary**: a source without a logo stays without one unless the brief asks.
3. **Ratio**: a landscape source fills a square canvas with balanced margins and legible support text,
   with its hierarchy unchanged.
4. **Palette**: colours come from the pack; categories stay distinguishable.
5. **Type**: casing from the pack; proper nouns exact; requested casing honoured; small text survives
   preview size; no one-word last lines.
6. **Geometry**: straight connectors axis-aligned, curves smooth, endpoints clean, nothing crossing text.
7. **Spacing**: padding optically balanced; labels clear the frame and their neighbours.
8. **No wallpaper**: no decorative dot or network filler where nothing calls for a diagram.
9. **Fonts**: the render's font check passed for every face it uses.
10. **Assets**: supplied official assets are recognizable and unchanged.
11. **Requirements**: every original and revision requirement is closed with evidence.

## What not to learn from one review

A particular tint, which card got the accent, one tag's radius or one chart's label placement are
choices for that artifact, not rules. When a review teaches something reusable, save the decision
behind it as an observation (`save_observations` under `brand-design`) with its evidence, and let the
next job weigh it.
