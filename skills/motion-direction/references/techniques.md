# Techniques

Named moves: what each is, when it earns its place, its timing, its sound, and how to build it in a
HyperFrames composition. Timings assume a 128 BPM grid (a beat is 0.469 s) unless they say seconds;
scale them to your tempo. They are starting points to weigh, not recipes to paste. Before building
one by hand, search the catalog (`hyperframes catalog --query "<the move>"`): a registry component
may already do it.

Build notes use the composition's one paused timeline `tl`, the times from the grid (`T`, or
`timeline.js`), and [motion-presets.js](../scripts/motion-presets.js) as `M`.

## Hook and type

**1. Impact on frame 0.** Frame 0 is a hit: a short inverted flash, the motif slamming from about
1.8× to 1× with a squash, a ring or two rippling out. *When*: films cut to music, and the drop.
*Timing*: flash two or three frames, slam about 0.3 s, rings 0.5-0.6 s a little apart. *Sound*: an
impact with a chord stab. *Build*: the flash is a cut (list it in the grid's cuts and set it, never
tween it); the slam is a `fromTo` on scale with `expo.out`, a squash after contact; keep the flash
within the three-flashes-a-second limit (design-wiki, colour).

**2. The sentence hook.** The claim arrives a word per half beat, each with its own entrance, and the
motif lands as the full stop by about beat 2. *When*: any message of three or four words. *Sound*: a
hit per word, the biggest on the full stop. *Build*: word start times in the beat table; one
`M.enter` per word at its time.

**3. Rise from the baseline.** Letters rise out of a slot at the baseline, slightly stretched, and
settle. *When*: a word's first appearance. *Timing*: about 0.22 s `expo.out`, 30 ms a letter.
*Sound*: a short blip per letter, rising in pitch, panned across. *Build*: clip the line's box at its
baseline; per-letter `fromTo` on `y` (about one cap height) and `scaleY` (1.25 to 1) with a stagger.

**4. Letter drop with squash.** Letters fall in one by one, stretched in flight, squashed on landing.
*When*: a hook's last word; anything with weight. *Timing*: a fall of about 0.13 s, 30 ms apart, each
squash settling in about 0.3 s. *Sound*: a short falling tone per landing. *Build*: per letter, a fall
on `y` with `power2.in`, then a short `scaleY`/`scaleX` squash and settle (a damped spring as a pure
function of time).

**5. Pull-back reveal.** The camera starts inside a detail and pulls back in log space to the whole,
then creeps forward. *When*: a word that turns out to be a sentence, a node that turns out to be a
graph. *Timing*: about 0.6 s `expo.out`, then a creep of a few percent over a beat. *Sound*: none;
the groove enters under it. *Build*: one camera wrapper; scale from `M.logZoom(start, 1, p)` via a
proxy tween, with the transform origin on the detail, measured on the rendered pose.

**6. Fall-away.** Letters drop out of frame under gravity with a little drift and spin; the motif
stays. *When*: clearing a held composition. *Timing*: gone in about 0.35 s, each with up to 90 ms of
seeded delay. *Sound*: one soft falling tone. *Build*: per letter, `y` with `power2.in` (spacing
grows each frame), `x` drift and rotation from `M.seeded("fall-" + i)`.

**7. Flood.** The motif grows until it covers the frame, travelling to the centre; the next section
opens on its colour. *When*: a section change the motif can own. *Timing*: about 0.2 s, `power2.in`
on the radius. *Sound*: a rising noise sweep into the cut. *Build*: scale on a circle (log space);
not a cut, so the next scene is already drawn beneath.

**8. The word that performs itself.** The word does what it says: "stream" spools out behind a
moving point, "branch" forks, "loop" is lapped, "trace" lights letter by letter as a line passes.
*When*: a roll call of verbs or features, one a beat. *Sound*: one designed sound each
([sound](sound.md)).

**9. The motif as cause.** The motif acts and the word reacts: grab and stretch, slice, fall and
flatten, hit and scatter. *When*: the motif is a character, or a cursor drives a product film.
*Timing*: the hit early in the beat; the reaction decays over 0.1-0.3 s. *Sound*: a hit, then a soft
bounce.

**10. Proof caption.** One mono line under the performing word states the real thing: a value, an
API call, a measured number. *When*: any claim a viewer could doubt. *Timing*: starts a moment after
the word, typed at about 12 ms a character. *Build*: large enough to read on a phone and at full
contrast; a typed reveal sets absolute text from the tween's progress, never appends.

**11. Word-by-word on the voiceover.** A line appears word by word from its first spoken word, each
word fading up quickly, so the line lands a little ahead of the voice. *When*: every line a
voiceover speaks, in a voiceover-led film. *Timing*: about 0.05-0.2 s a word and a 0.12-0.3 s fade;
onset within two frames of its word. *Build*: start times from the voiceover's word timings
(`generate_voiceover` writes `<name>.words.json`; `transcribe_audio` for a supplied voice).

## Shape

**12. Many into one.** A crowd (a grid, a tree, scattered items) spirals into one hub with a
shockwave: complexity to clarity. *When*: the end of a montage. *Timing*: outer elements first,
staggered up to about 0.12 s, each about 0.34 s `expo.in`, shrinking as they go; the hub re-forms on
a lively spring. *Sound*: a sweep swelling into the hub, then a pop.

**13. Stretch into a pill.** Round elements riding a fast turn stretch along their path in proportion
to their speed, then relax. *When*: shape play with nodes and lines. *Build*: two springs per element,
a fast one on the leading edge and a slow one on the trailing edge, so it stretches in flight and
relaxes on arrival.

**14. Card into tile grid.** A hero card squeezes into a square, splits into columns and becomes a
grid of lit tiles; its frame becomes the grid's frame. *When*: carrying one chapter into the next
without a cut. *Timing*: the squeeze in about 0.1 s, the split by about 0.15 s, the grid settled by
about 0.3 s. *Sound*: one hit on the split.

## Camera

**15. Whip pan.** The camera yaws away so fast the frame streaks; the next shot starts mid-whip from
the other side. *When*: between two setups, on a beat. *Timing*: the last ~0.13 s before the beat
(`power4.in`) and the first ~0.15 s after (`power4.out`). Not a listed cut, so blur spans the join.
*Sound*: a noise sweep across the stereo field, peaking on the beat. *Build*: blur the whip with the
motion-blur component; a whip that carries copy stays sharp.

**16. Orbit.** The camera circles a centred subject drawn far to near over a floor, for parallax.
*When*: showing that a flat thing has depth; revealing a diagram. *Timing*: about 1.5 beats
`power2.inOut`. *Build*: CSS 3D (`perspective` on the wrapper, `rotationY` on the stage) or the
Three adapter (`hyperframes-animation`, `adapters/three.md`); the subject stays centred.

**17. Ring of stages.** A product lifecycle as a ring: items evenly spaced, a camera at a fixed
elevation orbiting, cards floating above the ring and facing the lens. *When*: the one diagram a
film returns to per chapter. *Build*: the ring in 3D; to fit a reference, two opposite items on a
circle are conjugate semi-diameters of the projected ellipse, so elevation = asin(minor ÷ major).

**18. Dolly zoom.** The camera pulls back while the lens tightens; the subject keeps its size and the
world swings. *When*: once a film at most, at the camera's peak, over a background that visibly
swings. *Sound*: two tones gliding apart.

**19. Rush in.** At the end of a camera move the motif grows exponentially toward the centre and
floods into the next section. *Timing*: the last quarter beat, `power2.in`. *Sound*: a rising sweep
onto a hit.

**20. Fly through a word.** A word grows in, then the camera accelerates into one letter's counter
until it becomes the next beat. *When*: "scale", "zoom", "go deeper", once a roll call. *Timing*: the
grow about 0.16 s; the fly-through in the beat's last ~0.2 s, after the word was legible for a while.

**21. Telescoping pull-back.** The camera pulls back so fast that the hero card becomes a small pill
inside nested frames, which telescope in; then everything drops away and the pill becomes the motif.
*When*: closing a chapter card into the motif.

**22. One camera over real UI.** A close-up that reads as a graphic (a glowing line, a shape) turns
out, as the camera pulls back, to be part of the real product's chart or screen. *When*: revealing
that the abstraction is real data. *Build*: draw the surface in its own coordinates and move one
camera over it, with the scale keyed in log space.

## Colour, build and drop

**23. Wipe and invert.** The ground flips light to dark (or steps through the brand's tints) behind a
hard, slightly tilted edge. *Timing*: 0.15-0.3 s. *Build*: the new scene fully drawn behind a
`clip-path` that sweeps; hard-edged and fast, not a dissolve.

**24. Wall montage.** Earlier moments play at once as live tiles; the grid doubles each beat, then
shrinks and collapses into the motif. *When*: a reel's build bar. *Sound*: a stab and a tick per
grid, a riser into the drop.

**25. The build and the drop.** The last bar escalates, breathes for half a beat, and lands the
biggest hit on the final card. *Sound*: a riser, the groove thinning, a reverse swell ending exactly
on the downbeat, then the biggest impact and a held chord.

**26. The final card resolve.** The headline slams in on the drop; a beat later the motif lands as
its full stop and bounces once or twice; the logo rises behind a mask over a slow push, then holds.
*When*: every branded film's last bar. *Timing*: the slam about 0.5 s; the logo hold about 1-1.5 s on
a reel and 2.5-3 s on a long film.

## Finish

**27. Beat punch and push.** A held shot gets a small scale punch on the beat, decaying in about a
tenth of a second, and a slow push across the beat. *When*: roll calls; the push alone on final
cards. *Sound*: none of its own; it rides the kick.

**28. Impact envelope.** One list of hits drives a short decaying camera shake and any brief colour
fringing, so picture and sound peak together. *Sound*: an onset within a few milliseconds of each
hit ([sound](sound.md), the sync check).

**29. Halo under the body.** A card goes white-hot while its word stays readable: draw the glow as a
halo shape behind the card, then the card body and its label on top, so the glow shows only around
it. Additive glow over a pale body clips it and floods the label. *When*: a hero card's moment. A
brand decision: glow must be allowed by the pack (brand-in-motion).

**30. Number build.** A metric counts up or a chart builds once, with purpose, then holds still and
readable. *Build*: write `Math.round(value)` from the tween's own progress (never increment in a
callback); format with the unit; hold long enough to read. A number still moving when the viewer
needs to read it is a defect.
