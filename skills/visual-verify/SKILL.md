---
name: visual-verify
description: Look at your own renders before delivery and fix what is off. A restyle beside its source, a pixel-level fix as zoomed before/after crops, a video as a filmstrip of key frames.
---

# visual-verify

Look at the final raster before you deliver it, the same loop you run on code: render, look, fix,
look again. Judge it against the ask, not your own taste; when someone asked for a specific change,
that change is the bar. The deterministic gates (`brand-lint`, font checks, `video-gate`,
`hyperframes check`, `artifact-contract`) own tokens, fonts, clipping and dimensions. Your eyes own
everything they cannot measure: does it say the one thing, does the eye land where it should, is
anything generic or broken.

```bash
node /workspace/tools/review-thumb.mjs <img>                 # a <=1600 px .thumb.jpg to look at
node /workspace/tools/review-thumb.mjs --sheet <a> <b> ...   # several tiled into one sheet
```

Then `look` with the thumb or sheet and one specific question ("Is the headline the first thing you
read, and is any text clipped?"). One sheet costs far less than many frames.

## Restyles and reskins: source first, output second

For a restyle, reskin, cleanup or resize, the failure that matters is an unrequested addition,
deletion or change of meaning, which the output alone cannot show. Tile the source and the output:

```bash
node /workspace/tools/review-thumb.mjs --sheet attachments/source.png projects/<slug>/renders/restyled.png
```

A contract violation is a hard stop however good it looks: missing or changed source content,
invented copy or marks, skipped explicit feedback, wrong dimensions, broken connector relationships,
or an altered official asset. Fix the input or the renderer and re-render.

## A fix measured in pixels needs a zoomed crop

A 6 px seam vanishes when a 1600 px comp is downscaled for viewing, so a full-frame look reports
"fixed" when it is not. A weight, word or colour change reads at full frame and needs no crop. Crop
the same region out of before and after, wide enough to include the edge the fix is measured
against, and upscale both:

```bash
IMG="node /workspace/skills/image-ops/scripts/img.mjs"
$IMG renders/before.png review/crop-before.png --crop L,T,W,H --resize 800x
$IMG renders/after.png  review/crop-after.png  --crop L,T,W,H --resize 800x
node /workspace/tools/review-thumb.mjs --sheet review/crop-before.png review/crop-after.png
```

If a second attempt at a local fix is still wrong, show the zoomed crop and ask for the edge in the
person's own words instead of nudging again.

## Video: a filmstrip, not one frame

For a composition, `hyperframes snapshot --at <t1>,<t2>,...` (or `--frames 8`) before rendering;
for a rendered file, extract key frames with ffmpeg or `film-breakdown/scripts/grab.mjs --sheet`.
Tile them with `review-thumb.mjs --sheet` and look at the title and end cards too. A strip through
each transition shows broken handoffs that a sparse strip hides.

## What to look for

Defects that a gate passes and a person notices at once:

- garbled or fake text and logo marks, especially in generated images;
- an uncut white plate or a halo around a cut-out;
- a lockup clipped out of its card, or a logo below its minimum size;
- an arrowhead landing inside a rounded cap, or a connector that misses its shape;
- an identifier rendered wrong (`after_model` set as `after__model` by markdown-style escaping);
- a marker or label the same colour as its ground;
- generic node, dot or network wallpaper where the concept should be;
- more words than the ask supplied: a sub-line, caption, footer or URL nobody asked for.
