# Motion: cues and moves

These rules come from two places that have been used to build motion, with the source after
each rule: **HF** is HyperFrames (its story, film and motion guides and its page on
explainers), **Product** is this product's own motion-direction and storyboard guidance.

A plan does not animate. It says, for each built frame, **what changes and on which spoken
word**. The builder turns that into tweens. Write no eases, no milliseconds, no pixels.

## A cue

```json
{"at": "router", "object": "o2", "does": "draws itself between the request and the three specialists"}
```

- `at`: a word or short phrase that is in the frame's `vo`, exactly as spoken. The cue lands
  on the first word of the phrase, at its first occurrence in the frame, a fifth of a second
  early so the change has landed when the word is said. Code puts the cue on the clock,
  and the check's report prints where every cue lands.
- `object`: the id of the object that changes.
- `does`: what happens, in plain words. The classifier names the move.

## The moves

| Move | What it is | Source |
| --- | --- | --- |
| Reveal | Something that was not there arrives: draws itself, types on, pops in, grows. | HF |
| Count | A value changes in place: a number counts up, a bar fills. | HF |
| Emphasise | Something already there is pointed at: a glow, a ring, a lit line, the rest dimming. | HF |
| Morph | Something already there becomes something else or moves: a state, a label, a regrouping, a token travelling a path. | HF |
| Camera | The view moves: a push in on one part, a pan to the next station, a pull back. | HF |
| Carry | An object from the frame before crosses the cut and becomes part of this picture. | Product |
| Hold | Nothing new: the finished picture stays still to be read. | HF |

There is no exit move. In a narrated frame the transition is the exit (HF).

The classifier reads the move from the verb in `does`. Verbs that read as meant: *pops in,
draws itself, types on, appears* for a reveal; *turns into, changes to, moves to, travels
along* for a morph; *lights, glows, is ringed, the rest dim* for an emphasis; *counts up,
fills to* for a count; *stays from the frame before* for a carry. "Lands" reads as a morph.

## The rules

**When things happen**

1. Reveal each part when the voice names it, never before. One window per spoken cue. (HF;
   Product: the picture changes on the word that names the change.)
2. At the start of a frame show only what the first words name. Nothing dumped in the first
   quarter; the rest arrive across the back half. (HF)
3. Copy lands on or just before its word. (Product)
4. End each picture on a still moment long enough to read: a second after the last change,
   and 0.3 seconds a word plus half a second for any line of text. When a line ends on the
   very thing it shows, the still moment comes from the next frame holding the picture.
   (HF; Product)

**What changes**

5. The unit is a change, not a slide. A frame whose every cue is an arrival is a slide. Let
   something already on screen change state, be pointed at, or travel. (Product; HF calls the
   failure "front-loaded, then frozen".)
6. One focal object, and it keeps developing. Support arrives when it explains. Anchors stay
   put. (Product; HF: one focal element and two to four moves a frame.)
7. One diagram that grows, each label arriving with its part. Never the whole diagram at
   once. (HF)
8. Every change has a visible cause: a line is spoken, a token arrives, a step completes.
   (Product)
9. A number and its bar or ring land together. Data never overshoots. (HF)
10. Code owns its motion: lines type, light, diff or scroll. A diagram of behaviour needs at
    least three changes. (HF)

**How much**

11. Cues by the beat's job, in the middle case: a mechanism four, a list three, a contrast
    three, a worked example three, code three, a definition two, a so-what two, a signpost
    one. Nine in one frame is the most a viewer follows. (Counts from the study; the only
    numbers on this page that are.)
12. Cues are at least a second apart: with a presenter recording, each cue is a
    step advanced by hand. Things that arrive faster than that are one cue that lands as a
    group, the most important first: a list at about one item a second, three to six items,
    the last holding a second or two. (HF)

**What must not move**

13. No idle loops, floats or creeping scales to fake life. A hold longer than three seconds
    is where a picture goes dead: give it a change the words cause (something already there
    travels, counts or works, or a camera cue takes the view to the part being talked about).
    The builder fills what the cues leave; a plan that spreads its cues leaves it less to
    fill. (HF: something new every two to four seconds)
14. The camera is still while the viewer reads, and moves once the content has landed. A
    camera cue is a change like any other: use one where a line dwells on one part of a
    picture that is already drawn. (HF; Product)
15. A title card moves once. A pinned anchor never moves. (HF)
16. No blur on text that is being read; three seconds on screen must read in two. On-screen
    text is short copy, never the spoken sentence. (HF)

**Between frames**

17. Two or three kinds of transition in a video, one of them for most of the joins, 0.3 to
    0.5 seconds. (HF)
18. The transition follows from how a frame relates to the one before. The classifier reads
    the relation; code picks the transition: the same picture goes on (none), the next step
    (push), a deeper layer (crossfade), into a detail (zoom through), a new topic (cut), the
    person and the content swap (cut). (HF)
19. The same transition at every join is a slide build. Where one object can cross the cut,
    carry it. (Product)

## One style for the whole video

The theme names a motion style: how an object arrives, how its moves ease by their role (an
arrival on a long tail, the view both ways, what leaves accelerating), the primary transition,
how the active object is marked. A frame never picks its own style (HF: one video direction
with a motion grammar and a negative list).

## How motion fails

The checks look for these in the plan, before anything is built:

| Failure | In the plan it looks like |
| --- | --- |
| A slide | 18 words or more over a built picture with one cue or none |
| Every change is an entrance | four or more cues, all reveals |
| Front-loaded | more than a third of the cues in the first quarter of the words |
| Dead air | twelve seconds of voice with nothing changing on a built picture |
| Cues too fast to advance | two cues under a second apart |
| A cue on nothing | `at` is not in the frame's words, or its object is not in the frame |
| A slide build | more than three kinds of transition, or one kind at every join |
