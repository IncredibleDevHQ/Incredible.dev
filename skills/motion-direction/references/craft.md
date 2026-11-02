# Craft

The motion canon as checks you can run on a composition or its frames. Named moves are built in
[techniques.md](techniques.md); sound is in [sound.md](sound.md); brand departures in
[brand-in-motion.md](brand-in-motion.md). HyperFrames mechanics (seek-safety, sub-compositions,
motion blur) are in the vendored skills and are linked, not repeated.

Each point is a default to weigh unless it names its evidence. The twelve principles of animation
(Thomas and Johnston, *The Illusion of Life*, 1981: squash and stretch, anticipation, staging,
straight ahead and pose to pose, follow through and overlapping action, slow in and slow out, arcs,
secondary action, timing, exaggeration, solid drawing, appeal) are the older canon most of this
restates for interface and type.

## Motion

- **Nothing moves linearly except a constant drift** (a slow pan, stripes, travel down a tunnel).
  Everything else has an ease. *Check*: search the composition for `ease: "none"` and `linear`.
- **Choose the ease by the move's role.** In GSAP, `power1` is a quadratic curve, `power2` cubic,
  `power3` quartic and `power4` quintic (GSAP eases docs, <https://gsap.com/docs/v3/Eases/>); invert
  the curve you actually used when you assert where a tween is at a given time.

  | Role | Curve | Typical duration |
  | --- | --- | --- |
  | Arrival, a slam | `expo.out`, `power3.out` | 0.2-0.6 s |
  | Departure, anything accelerating into a cut | `power2.in` to `power4.in`, `expo.in` | 0.12-0.35 s |
  | Camera travel, morphs, wipes | `power2.inOut` to `power4.inOut` | 0.15 s to a beat and a half |
  | A landing or a pop | a spring (below), or `back.out` with a small overshoot | settles in 0.3-0.8 s |
  | A deliberate overshoot | `back.out(1.2-1.7)` | 0.2-0.4 s, rarely more than once a beat |

- **A fade-out that overlaps the next beat eases out, not in.** An ease-in exit keeps the outgoing
  element mostly opaque for the first half of its exit, exactly while the incoming one rises, which
  reads as two things at once; an ease-out exit is mostly gone by mid-exit, so the next can start
  halfway through.
- **Springs by role.** A spring's overshoot is exp(−ζπ / √(1 − ζ²)) for damping ratio ζ (Wikipedia,
  "Overshoot (signal)"): ζ 0.7 overshoots about 4.6%, ζ 0.35 about 31%, which reads as a bounce.
  Use ζ ≥ 0.7 for UI, cameras and product surfaces; a lower ζ only for the motif's pops, at most one
  a beat. Settling to within 2% takes about 4 / (2π f ζ) seconds for a spring of frequency f.
  `MotionPresets.overshoot(zeta)` computes it. In GSAP, compute a true spring as a pure function of
  time inside one tween (a damped cosine written to absolute state), never by accumulating.
- **Exits are faster than entrances.** A response should feel immediate; a meaningful transformation
  can take longer. Do not delay a clicked result behind a slow flourish.
- **Overlap.** Secondary elements trail the lead by one to three frames; a per-letter stagger of
  roughly 15-35 ms keeps a word reading as one gesture when the whole stagger stays under about 0.2 s.
- **Every change has a visible cause.** The motif, a cursor or a hand pushes, pulls, slices or drops,
  and the thing reacts on contact. Frame 0 and the downbeat are the only uncaused events.
- **Zoom and grow in log space**: z = exp(lerp(ln z0, ln z1, p)). A linear zoom from 10× to 1×
  spends its first half on only about a quarter of the perceived change. Smooth zoom-and-pan paths
  are worked out in van Wijk and Nuij, "Smooth and efficient zooming and panning" (IEEE InfoVis 2003;
  the basis of d3's `interpolateZoom`, <https://d3js.org/d3-interpolate/zoom>).
  `MotionPresets.logZoom(from, to, p)` does the first part.
- **Throws and falls follow gravity**: the spacing between frames keeps growing. Give each falling
  element its own small delay, drift and spin from a seeded hash (`MotionPresets.seeded(key)`), never
  from `Math.random` (`video-gate` fails it).
- **No idle motion.** No floating, breathing or glow pulses that are not events. A shot held longer
  than about half a beat gets a slow push (a few percent of scale per beat) or a small punch on the
  beat, or the next idea comes on. `video-score` reports runs where nothing changes.
- **Match velocity across a hard cut**: the outgoing element accelerates into the cut and the incoming
  one decelerates out of it, so the motion carries across.

## Type in motion

- **A word performs itself or carries the message**, never a caption naming the section.
- **Big when it is the point**: a hook or final headline can span most of the frame width; proof the
  viewer must read is never small and soft. The legible floor is checked by `video-score`
  (`hierarchy.illegible`) on the rendered frames.
- **The legibility window.** A word the viewer must read spends time settled (at its final size and
  position, barely moving) for its reading time; the reading speed is in
  [directing](directing.md#pacing-by-attention-job).
- **Entrances start partway in.** No entrance starts from nothing on an empty frame: letters can rise
  from a baseline mask with most of their height already visible, or a line can start partly drawn.
- **Mono is for literal values**, typed or decoded at a steady rate (roughly 12-20 ms a character),
  starting a moment after the headline so it reads as a second beat.
- **Small text that must stay sharp over moving footage** is not motion-blurred; blur the approach,
  land sharp, hold (`hyperframes-animation`, motion blur).

## Camera

- **Real moves**: push into a detail, whip on a beat, orbit a centred subject, fly through depth. A
  camera that only drifts reads as a diorama.
- **A camera move is built, not described**: the storyboard ships its start and end framings and
  names the one wrapper that owns the transform (`storyboard`, camera). One owner per property; two
  rigs writing the same property is jitter.
- **Shake only on impacts**, decaying in a fraction of a second; 2D frames carry no handheld wobble.
- **A dolly zoom** (pull back while the lens tightens) is once a film at most, and only over a
  background that visibly swings.
- **The camera holds still while the viewer reads.**
- **Which moves blur**: blur the beats that snap (a slam, a whip, a spin, a scale punch), one to three
  in a composition; never text being read, slow drifts or a whole scene. Two routes, the `motion-blur`
  registry component per element and the engine's render option for the whole frame, are compared in
  `hyperframes-animation` (`references/motion-blur.md`), measured there against an After Effects
  export.

## Transitions

- **Continuity by default; a hard cut when the cut says something**: a change of state, a change of
  mode, the product's entrance, the end card. Spend the hard cuts where they mean something.
- **The carrier.** When a beat's result becomes the next beat's subject, one populated element lives
  outside the scene containers on its own track and crosses the cut. It is built once at its detail
  size, has one transform owner, does not re-enter, and is bounded to one or two a film. Where nothing
  genuinely spans the cut, name the semantic handoff (a question answered by its result, a match cut,
  a kept direction of motion) instead of inventing a morph (`storyboard`, handoff sheet).
- **A hard cut is a set, never a short tween.** A 0.05 s "cut" at 30 fps still lands one frame
  mid-blend, and between opposite grounds that frame is flat grey. Use a zero-duration set at the cut
  time (not at time 0: `video-gate` explains why).
- **Dissolve only between scenes that share geometry.** A light-over-dark dissolve has a mid-grey
  midpoint, and a dissolve between two different layouts double-exposes them. A re-layout gets a cut.
- **On a dissolve, the headline does not fade on its own**: the crossfade is its entrance. Give it a
  small drift only; fade only secondary content, a moment in.
- **Overlap moves; sequence copy.** Start the incoming reveal as the outgoing element leaves. Copy is
  the exception: outgoing copy clears before the next copy appears, so two blocks of text never
  compete at reading pace.
- **One clip, stacked wrappers, when scenes crossfade.** If a strip through a crossfade shows a dip to
  black, the scenes are separate clips handing over at a boundary; put them in one clip as stacked
  wrappers driven by opacity, with the carrier on its own track.
- **z-order is a requirement.** Foreground never shows the background through it: dim a node's fill,
  not the node group's opacity, or a line behind it shows through.
- **Entrances use `fromTo`**, never a bare `from` paired with a CSS starting state (`hyperframes-core`).
- **One primary transition and one or two accents for the film**, chosen for what the content is
  doing; the same transition at every cut is a slide build.

## Composition

- **The hero is big**: a large share of the frame. A small thing alone on an empty ground for more
  than a moment is dead air: scale it, push the camera in, or bring the next idea on.
- **Two attention demands at most a frame**; one is the good frame (design-wiki, hierarchy).
- **One focal element** at full contrast and size; the background never competes.
- **Title-safe**: keep hero ink well inside the edges unless cropping is the idea; check the vertical
  cut against the platform's overlay (design-wiki, platforms).
- **Every element has a role** before any animates: the focal object (shows the work and keeps
  developing after it arrives), supporting content (arrives when it explains), the carrier, ambient
  context (moves out of phase, if at all), and static anchors (do not move just because everything
  else does). A scene whose every tween is an entrance is a slide.
- **States are the deliverable.** A block that animates between states (empty to full, running to
  done, fail to pass) shows both, and the change is driven by the timeline.
- **The final card is a poster**: the headline, the motif as its punctuation, one signature, one next
  step if the format allows, nothing else.

## Rhythm

- **Three rates or more**: a cut per beat somewhere, a move per bar somewhere, a quick flurry
  somewhere, and one breath before the drop.
- **Escalate before the drop**: density rises through the last bar, then everything collapses into
  the motif.
- **Breathe**: half a beat of thinned picture or near-silence before the biggest hit.
- **Voiceover-led films hold to read**, and declare those holds in `AUDIT` with their reason.

## Loops

- **The last frame is the first frame, velocity included**: every position and speed, or the loop
  stutters. *Check*: compare frame 0 with the frame one period later, and the step from the last frame
  to frame 0 with the step from frame 0 to frame 1.
- **A loop is a whole number of bars** (7 bars at 120 BPM is 14 s).

## Polish and determinism

- **Seek-safety is a hard floor**: no clock, randomness, timers or wall-clock animation; one paused
  timeline; callbacks write state derived from time and never accumulate; measure layout once, after
  fonts load, then bake it (`video-gate` scans for all of these; `hyperframes-core` has the rules).
- **Snap emitted times to frames** and back off half a millisecond, so an event never rounds past its
  frame (`MotionPresets.onFrame`).
- **Prove a hold is a hold**: sample frames across it and diff them; video encoders have a noise
  floor, so compare against a moving reference rather than testing for exact zero.
- **Proofread the first and last frames at full resolution**: typos, counters, half-faded copy.
- **Post effects on purpose only**, in a handful of short windows, never as a constant filter unless
  the brand declares it.
- **Encode for delivery** as the platform asks (design-wiki, platforms); HyperFrames' `--quality
  delivery` is the final, `draft` is for iterating.
