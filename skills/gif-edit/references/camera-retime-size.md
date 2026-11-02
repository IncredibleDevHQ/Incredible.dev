# Camera, retiming, size and encoding

## The camera: the answer to "it's really small"

Legibility is the most common complaint about a screen-recording GIF, so offer the camera up front.
A dense UI downscaled to GIF width is unreadable; the fix is a keyframed zoom and pan inside the
window.

- **Keep the composition intact.** Zoom `z` crops `(W/z × H/z)` of the window content and scales it
  back to the window's size, composited onto the plate at the same position with the same mask. The
  window never moves on the ground; only its content magnifies, which reads as a camera rather than a
  scaling animation. Per frame: sharp `extract()` then `resize(W, H, { kernel: "lanczos3" })`.
- **Keep the camera in its own module** (`camera.mjs` exporting `KEYS`, `cameraAt(t)`, `cropAt(t)`
  and the clip bounds, with commented beats). Every revision becomes a keyframe edit, and every audit
  reads the same numbers. Keep the previous version beside it (`camera.rev2.mjs`): "use the version
  before this" is a common note.
- **Track the cursor with a motion diff, not a detector.** A per-frame binary diff at quarter
  resolution (`|dGrey| > 26`) and an integral image find the peak 9×9 window in O(1) per position. A
  still cursor produces no diff, so hold the last position forward, then reject jumps by continuity (a
  peak far from the last accepted one counts only if the next peaks stay near it), which drops UI
  changes like a panel opening. Validate by drawing crosshairs on about 20 sampled crops and looking.
- **Never hard-lock the cursor to centre.** It tracks every twitch and reads as seasick. Frame the
  region of interest and hold.
- **The clamp trap.** If a keyframe's centre falls inside the clamp band (`cy < cropH/2 + topMin`),
  the crop pins to the limit and the move produces no travel. Print the resolved crop rect per
  keyframe and assert it changes.
- **Crop out the browser chrome before magnifying it,** or the camera magnifies a dev URL. Find the
  boundary by scanning row means: the chrome band reads uniform with URL text as a dark spike, then a
  divider row, then content. Bounding the bottom too can keep an account email in a sidebar out of
  frame. Report `min(crop.top)` and `max(crop.top + crop.height)` across all frames.
- **Set a zoom floor.** If legibility is the complaint, keep even the establishing shot at about
  1.45× or more; a 1.0× context shot reproduces the original problem.
- **Quote the magnification.** Content scale is `outputWidth / (windowWidth / z)`, so `z` is the
  magnification against the no-zoom version. Report it ("1.5× to 1.9× larger on screen") and back it
  with a stacked before/after crop of the same UI row at the same physical size.
- **Review a dense strip through each move.** A sparse filmstrip hides a broken transition; six
  frames through each move show the handoffs.

## Retiming

- **Half speed means twice the real frames, never twice the delays.** Stretching each delay halves
  the speed but halves the playback rate too, and reads as choppy. Re-extract from the source at
  twice the content rate.
- **Pick a rate pair that divides the source evenly.** From a 60 fps source, sample content at
  30 fps and play back at 15 fps: exactly half speed, every frame a real source frame, even cadence.
  60 → 40 samples unevenly (alternating 1- and 2-frame gaps), and slow motion is where the eye has
  time to see the wobble.
- **Key the camera in content time.** With `cameraAt(contentT)` and `contentT = frameIndex /
  contentFps`, a speed change needs no camera edits.
- **"Clip right before <UI event>": find the frame by difference, not by eye.** Probe the source at
  native fps around the moment, resize to about a quarter, and compute the mean absolute difference
  against a clean reference frame: it stays near zero, then jumps when the panel opens. Cut at the
  last clean timestamp, then audit that no delivered frame approaches the opened state and the last
  frame matches the clean one. If a trim kills a camera beat, rework the tail into a push and hold on
  the thing about to be clicked.

## Size: a moving camera defeats frame differencing

Every moving frame is new data, so a camera and a slower retime both grow the file. Levers, in
order of value:

1. **Mostly holds.** Tighten moves to about 0.4 s and hold the rest. Print the moving-frame count.
2. **Palette.** `palettegen=max_colors=128` is usually indistinguishable from 256 on UI text; 64 is
   often fine on a small email version. `stats_mode=diff` spends the palette on what moves.
3. **Dither.** `paletteuse=dither=bayer:bayer_scale=3` compresses better than error diffusion on
   flat UI; `diff_mode=rectangle` re-encodes only the changed region of each frame.

`gifsicle` is not installed, and the sandbox has no network at run time, so do not plan on lossy
GIF compression. Once holds and palette are exhausted, the honest remaining levers are width and
clip length: say so rather than degrading quality to chase a number.

## Encoding an animation you rendered

For a GIF or WebP made from your own HyperFrames or HTML render:

- **Render at a rate GIF can hold.** GIF delays are whole centiseconds, so 30 fps rounds to 3 cs and
  a 12 s loop plays in 10.8 s. Render the master at 50 or 25 fps (`hyperframes render` takes a
  rational `--fps 25/2`, not a decimal). When the GIF runs slower than the master, decimate exactly
  2:1 (25 → 12.5); 30 → 25 drops one frame in six and hitches on steady motion.
- **Slowness is motion per frame.** A seamless loop needs every element to finish whole cycles, so
  slowing it lengthens the loop and the file grows about linearly; once motion is slower, halving the
  GIF's fps buys size back and still steps less per frame than before.
- **Line art on transparency: matte the antialias.** 1-bit alpha makes `alpha_threshold` choose
  where the staircase falls. Composite over a matte near the destination ground, keep the blended
  edge opaque, keep transparency only outside the line, and sweep the threshold (128 beads a thin
  stroke). Set the matte source's `r=` to the clip's rate, because `overlay` inherits its first
  input's.
- **Ship an animated WebP beside a transparent GIF:** true 8-bit alpha, smaller. Put `format=rgba`
  before the scale, or the alpha plane rounds into a faint box.
- **Capture a plain HTML animation (not HyperFrames) on a virtual clock.** Real-time screenshots race
  the tweens and collapse a smooth animation into a few distinct frames. Before the page's scripts
  run, replace `requestAnimationFrame`, `setTimeout` and `performance.now` with a clock you step one
  frame per screenshot. HyperFrames compositions are already seekable; render them with `hyperframes`.
