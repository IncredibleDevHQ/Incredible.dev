# Alpha, compositing and sharp gotchas

## Compositing order

Within one sharp pipeline, operations run in sharp's fixed order, not the order you call them:
`composite()` runs after `resize()`, and `extend()` before a post-resize `extract()`. Chaining a
composite of full-size layers and then a smaller resize fails with "Image to composite must have same
dimensions or smaller", because the canvas shrinks first. `img.mjs` settles the image after every op,
so its ops really run left to right; in your own scripts, write each stage to a buffer before the next.

## Prove alpha with numbers

A cut-out that looks clean on a white preview can carry a fringe. Read the raw pixels
(`--pipe '[["ensureAlpha"]]'` to a PNG, then sample with sharp's `.raw()`): corners should read
alpha 0 and the subject's interior 255. Along an antialiased edge, the transitional pixels should
share the edge colour; a dark antialias pixel beside a light edge is the fringe tell, and a fringe
usually measures a low but non-zero alpha in the band just outside the edge.

## Luminance key: a mark on a flat dark ground to transparency

`a = clip((lum - lo) / (hi - lo) * 255, 0, 255)` with `lum = 0.299 R + 0.587 G + 0.114 B`. A soft
ramp leaves a visible halo, so keep it tight: near-ground pixels go fully transparent and the ramp
spans only a few dozen luminance steps. Flatten the result on the destination ground to preview it
before using it.

## Recolouring a supplied mark

Only when the brand's own usage notes allow that colourway. Rewrite RGB, keep the alpha channel
byte for byte, and prove it: an alpha-only hash identical across the source and every recolour is the
receipt that the geometry is untouched. Recolour only the pixels of the ink you mean to change (for
example near-black, `r, g, b < 90`), so a coloured element beside it survives.

## Cut-out edges

A cropped cut-out edge must run off a frame edge, never be feathered mid-canvas. Per-row feathers
stair-step, smoothstep fades show a diagonal band across bright areas, and blurring the alpha
re-reveals the old background as a halo. Anchor the subject so the cropped edge bleeds off frame.

`.trim()` finds slightly different bounds frame to frame during a fade, so a trimmed sprite wobbles.
Extract sprites at a fixed source offset instead.

## Grading a set of supplied photos

When one face in a row of headshots pops, measure each photo inside the shape it will sit in (a
square crop's ground corners drag the mean down), then give every photo the same transform: a gamma
solved toward a common mean luminance (it lifts midtones without clipping highlights the way a gain
does) and a saturation scale, both clamped (about 0.62-1.40 and 0.70-1.15). Match the set rather
than shipping the mismatch with a disclaimer.

## Gotchas

- `file` is not installed; read the format from `--info`. AVIF reports `format: "heif"`.
- GIF pages: `sharp(path, { page: i })` reads one frame, `{ pages: -1 }` all of them;
  `metadata().pages` is the frame count and `.delay` the per-frame milliseconds. Animated work goes
  to `gif-edit`.
- In your own `.mjs`, load sharp from the toolchain, never a bare import:
  `createRequire((process.env.DESIGN_AGENT_RENDER_DIR || '/opt/design-agent/render') + '/package.json')('sharp')`.
- `brand-lint` text-scans its input, so it refuses rasters (compressed bytes read as off-brand
  hexes). Lint the HTML that produced the image.
- macOS screenshot names carry U+202F (narrow no-break space) before "AM"/"PM", so a path typed
  with a normal space fails. Use a glob: `cp attachments/*2.03.48*.png projects/<slug>/`.
