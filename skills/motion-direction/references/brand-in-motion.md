# Brand in motion

A brand moves differently from how it sits still: a film may use a flash frame, glow, depth, larger
radii or a long end hold that the brand's stills never would. Which of those this brand allows is a
brand fact, read from the pack, never assumed. This page separates what is never broken, what the
pack may allow, the defaults for an original film, and who wins a conflict.

## Never broken

Taste, a reference and a default never override these.

- **The real marks only, geometry untouched.** Logos come from `/workspace/brand/logos/` with their
  usage notes in `brand.toml` (which colourway on which ground, minimum size, clear space). Animating
  a mark's own paths (revealing, slicing, recolouring within the pack's colourways, turning in 3D) is
  a brand decision the pack may allow; redrawing, tracing, reshaping or composing a lockup from parts
  is never allowed. A mark with no official file is an asset request: ask for it; a recreation may
  draw a labelled stand-in and log it.
- **The brand's faces**, loaded locally through `@font-face` from the pack's `fonts.toml` and checked
  by the renderer; never a fallback face in a final.
- **No outlined or stroked type** to fake a weight the face lacks.
- **Supplied artwork moves only by its own layers.** A flat PNG, or an SVG that wraps a raster, is
  not ready to animate: ask for the layered file (isolated parts with their bounds and anchors),
  and never fake a moving part (an eye, a leaf, a limb) by cropping a guess out of the flat image.
- **Colours from the tokens**, or declared with their source in the film's `STYLE.md` when a
  recreation samples a reference (and mapped to the nearest token wherever the brand's own work is
  concerned). `brand-lint` checks the compositions.
- **Third-party logos are not drawn as real marks**; their UI, when it must appear, is rebuilt as
  drawn UI.

## What the pack may allow in motion

Look for these in `graphic-language.md`; use one only when the film's idea calls for it, and declare
it in `STYLE.md` with the line of the pack that allows it.

| Device | Typical rule when allowed |
| --- | --- |
| Flash frames, pure black or white openings | A flash is a cut: listed in the grid and set, never tweened; within the three-flashes-a-second limit |
| Glow, bloom, a white-hot moment | The halo is drawn under the body so the label stays readable (techniques 29) |
| Light falling across a ground (a pool, a falloff) | Light from a source, never a decorative two-colour fill |
| Depth: a sparse, dim field that moves with the camera | Never a particle field or texture wallpaper |
| Larger radii on cards that scale with the card | Declared, since stills usually cap radius lower |
| A different weight for labels or card words | Real weights of the face only |
| A long end-card hold | 2.5-3 s on a long film |

## Defaults for an original film

When the pack is silent:

- the brand's own graphic language carries the idea, used to resolve a concept, not as texture;
- one accent, meaning the same thing in every frame;
- energy from scale, speed and masks, not from adding weight or effects;
- the grounds the pack lists for stills;
- UI rectangles at the pack's maximum radius or less;
- no page furniture: frame counters, crop marks, chips, decorative HUDs;
- post effects (fringing, grain) only on impacts, if at all;
- sentence case and the pack's punctuation rules for on-screen copy.

## Who wins

1. **The person's explicit ask** for this film beats a default: a partner's palette, an event face,
   a treatment they asked for. Record it in `STYLE.md` as a waiver with their words, so the critic
   does not flag it. Mark geometry has no waiver.
2. **In a recreation**, the reference is the spec for layout, timing and motion; the brand still owns
   identity (marks, faces) unless the person says otherwise, and every off-token colour is declared
   with its source.
3. **The brand pack** beats this skill's defaults.
4. **This skill's defaults** beat habit.

## Where it is checked

- `brand-lint` on every composition (tokens, faces, radius, casing, decorative motifs, contrast).
- `video-gate` and `hyperframes check` before any render (determinism, lint, layout, contrast).
- The critic's Brand area in [review](review.md): identity intact, one accent, every departure
  declared with its source, the final frame proofread at full resolution.
