---
name: gif-edit
description: Edit animated GIFs and screen-recording GIFs with ffmpeg and sharp (reframe to exact dimensions, swap on-frame text, retime, trim or reorder the loop, add a zoom-and-pan camera, encode small). Still images go to image-ops.
---

# gif-edit

A GIF is the format where the obvious approach is usually wrong: frames animate, so a decision that
looks right on the settled frame breaks during the build-in. Work from frames, check across the
whole timeline, encode last.

A mechanical change (resize, retime, trim, text swap) is: make it, check the encoded file, deliver.
The camera and size work in [references/camera-retime-size.md](references/camera-retime-size.md) is
for screen recordings that need it.

```bash
cd /workspace/projects/<slug>
ffprobe -v error -select_streams v:0 -show_entries stream=width,height,nb_frames,avg_frame_rate in.gif
mkdir -p frames && ffmpeg -i in.gif -fps_mode passthrough frames/f-%04d.png   # edit frames, not the gif
ffmpeg -framerate 20 -i frames/f-%04d.png -filter_complex \
  "[0:v]split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer" renders/out.gif
```

## The traps

- **Never judge a crop on the settled frame alone.** A crop that frames the headline at rest can be
  full of graphic mid-build. Sample start, build and settle before committing.
- **Never `fillborders=smear` over animated content.** Smear replicates edge pixels; a moving graphic
  touching that edge drags into vertical streaks. Crop to the true target aspect instead.
- **Crop to the target ratio, then scale both axes by the same factor.** Stretching to hit exact
  dimensions distorts type. If the crop clips something important, that is a composition question
  for the person, not a scaling one: ask.
- **Open the loop on real content.** Previews and some email clients show only frame 0, so an
  animation that fades in from blank reads as an empty asset. Rotate the loop to open on the settled
  state (`frames[k:] + frames[:k]`).
- **To slow motion down, add real frames; do not lower the frame rate.** Dropping fps reads as
  choppy. Re-extract more source frames and keep playback at a normal rate. Do not interpolate:
  `minterpolate` ghosts hard-edged UI type and the cursor.
- **Hold before you cut, and trim to still water.** A hold is the last frame repeated; a trim ends
  the clip where motion settles, not where the task finished. Find the still water, end there, then
  add the hold.
- **Keep the build-in, rest on a clean frame.** Assemble `[intro frames] + [one clean end frame
  repeated]`. Both must use identical crop and scale geometry or the headline jumps at the join, and
  only ever erase a region on the static end frame.
- **Re-typeset text; never upscale it.** Scaled raster type is what "grainy" means. Remove the old
  text region and set the copy fresh at final size in the brand's fonts
  (`var(--brand-font-display)`, `var(--brand-font-text)` from `/workspace/brand/tokens.css`), rendered
  with `node /workspace/tools/html2png.mjs <page.html> --out <dir> --size WxH --require-font <family>`,
  which fails rather than ship a fallback font. Match the source's own alignment.
- **Gradient banding is the format, not your work.** 256 indexed colours cannot hold a smooth
  gradient; the source has the same dithering. If someone wants it truly smooth, offer MP4 or
  animated WebP beside the GIF they asked for.

## Removing something from the frame

In order of preference: crop it out (no seam), reframe so it never enters, cover it only when the
background behind it is flat. Painting over a gradient seams; painting over a moving element has to
be redone per frame.

## Delivering

Check the encoded GIF itself, not an extracted PNG: `ffprobe` its dimensions, frame count, rate and
duration, look at an early and a late frame (`visual-verify`), then deliver with `upload_files`.
Quote the numbers that matter to the ask (size in MB, magnification, duration) in plain words.
