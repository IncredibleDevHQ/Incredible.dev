---
name: image-ops
description: Deterministic pixel work on an existing image with sharp, Photoshop's image menu in code (resize, crop, rotate, tint, trim, flatten, pad, composite with blend modes, convert, compress, read metadata). Not for new pictures or branded layouts.
---

# image-ops

One CLI, ops applied left to right. Colours are `#rrggbb` or a brand token from the active brand
pack (`--brand-color-paper`), so a tint or a pad stays on brand without copying hex values.

```bash
IMG="node /workspace/skills/image-ops/scripts/img.mjs"
$IMG <input> <output> [ops...]      # prints {"ok","output","format","width","height","bytes"}
$IMG <input> --info                 # {"format","width","height","channels","hasAlpha","space","pages","bytes"}
```

| Need | Op |
| --- | --- |
| resize | `--resize 1200x630:cover` (`800x`, `x600`; fit cover, contain, fill, inside, outside) |
| crop a region | `--crop L,T,W,H` |
| rotate, flip | `--rotate 90`, `--flip`, `--flop` (`--rotate 0` auto-orients from EXIF) |
| convert, compress | `--to webp --quality 80` (or let the output extension decide) |
| adjust | `--modulate 1.1,1.3,20` (brightness, saturation, hue), `--greyscale`, `--negate`, `--gamma 2.2` |
| sharpen, blur | `--sharpen [sigma]`, `--blur 6` |
| trim flat borders | `--trim` |
| tint, duotone | `--tint --brand-color-sky` |
| drop transparency | `--flatten --brand-color-paper` |
| pad | `--extend 20,20,20,20:--brand-color-paper` (top, right, bottom, left) |
| overlay, watermark | `--composite mark.png@40,40:over` (repeatable; blend over, multiply, screen, overlay, ...) |
| anything else | `--pipe '[["clahe",{"width":3,"height":3}],["linear",1.2,-10]]'` (allowlisted sharp methods) |

Exit 0 written; 1 sharp could not process this input with these ops (read the message, fix the
ops); 2 bad arguments, a missing file or token, or no render toolchain (report it, do not retry
blindly).

```bash
# a link-card hero from a big PNG, optimized
$IMG attachments/hero.png projects/<slug>/renders/hero.webp --resize 1200x627:cover --to webp --quality 82
# put a supplied mark on a photo, bottom right, then check what came out
$IMG projects/<slug>/photo.jpg projects/<slug>/renders/photo-marked.jpg \
  --composite /workspace/brand/logos/mark.svg@1792,952
```

## Judgment

- **Upscaling adds no detail.** Interpolation invents no frequency content, and a deck or a browser
  already interpolates when it scales an image. When someone asks for "hi-res" or "sharper", rebuild
  the artwork as HTML or SVG (`stills`, `data-viz`) instead of resizing up.
- **Never resample a diagram with hairline connectors to fit a layout.** A 2 px stroke smears under
  any resample. Keep the art at scale 1 and size the canvas around it with `--extend`.
- **A new aspect fills the new frame.** Recompose the layout at the target ratio (`stills` renders
  each size from HTML) rather than letterboxing, padding or stretching. Pad only to put untouched art
  on a bigger canvas, centred on the ink, not the frame: measure the ink's bounding box and split the
  pad so the ink lands centred. Check first that the source's edge columns are one flat ground colour
  (min equals max); a gradient ground needs a per-row fill, not a flat pad.
- **Logos come from the brand pack** (`/workspace/brand/logos/`, usage in `brand.toml`): minimum
  width, clear space and the colourway for the ground. Never stretch, recolour or rebuild a mark.
- **Look at the result.** `node /workspace/tools/review-thumb.mjs <output>` and `look` at the thumb;
  for a pixel-level fix, compare zoomed crops (`visual-verify`).

Compositing order, alpha proofs, luminance keying, recolouring a supplied mark, grading a set of
photos, and the sharp gotchas: [references/alpha-and-compositing.md](references/alpha-and-compositing.md).

## When not to use it

- A new picture: the `generate_image` host tool (`image-generation`).
- A branded layout with copy and the real logo: an HTML still (`stills`).
- Animated GIFs: `gif-edit`.
- Removing a background from a photo or video: `hyperframes remove-background` (see `media-use`);
  a flat ground keys with the luminance key in the reference.
- Photoshop-only filters and PSD editing are not available; say so.
