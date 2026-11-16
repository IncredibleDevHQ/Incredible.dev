# Building one picture

You build one picture of an episode: a run of lines over which one drawing grows as the
presenter speaks. You decide how it looks and how it moves. Code decides when: every time in
your file comes from a clock that code sets, first from the plan and later from the recording.

The turn names a brief file (`pictures/<id>.brief.json`). Read it whole. It gives the file to
write, the canvas, the look, each line with what it adds, and the key of every cue.

## The file

One HyperFrames sub-composition, complete in itself:

```html
<!doctype html>
<html>
  <head><meta charset="UTF-8" /></head>
  <body>
    <template>
      <style>
        #root { position: absolute; inset: 0; }
        /* every other selector starts with the composition id: #pic-c2-b1-f1-title */
      </style>
      <div id="root" data-composition-id="COMPOSITION_ID" data-width="WIDTH" data-height="HEIGHT">
        <script type="application/json" id="COMPOSITION_ID-clock">{"seconds": 0, "lines": {}, "cues": {}}</script>
        <!-- the picture -->
      </div>
      <script>
        (function () {
          const clock = JSON.parse(document.getElementById("COMPOSITION_ID-clock").textContent);
          const at = (key) => clock.cues[key];
          const tl = gsap.timeline({ paused: true });
          tl.fromTo("#COMPOSITION_ID-title", { opacity: 0, y: 24 }, { opacity: 1, y: 0, duration: 0.5 }, at("c2.b1.f1/0"));
          window.__timelines["COMPOSITION_ID"] = tl;
        })();
      </script>
    </template>
  </body>
</html>
```

- Everything the picture needs is inside `<template>`: styles, markup, script. Anything outside
  it is dropped when the picture is mounted.
- Style the root as `#root`. Give every other element an id or class that starts with the
  composition id, so two pictures on one page never collide.
- `gsap` is already on the page. Load nothing: no script file, no stylesheet, no font, no
  image from the network. Draw with HTML, CSS and inline SVG.
- Type is the brief's: its `fonts` give the display, text and mono families of the look, and
  it lists what else the rendering computer has. Name a family in `font-family` and nothing
  more: code declares it. Use no other family.
- One paused timeline, registered under the composition id. Use `fromTo`, never `from`: the
  picture is seeked to any second, in any order.
- No timers, no random numbers, no clock of the day. No `<br>` in text.

## The clock

- Every cue in the brief has a key. Its move starts at `clock.cues["<key>"]`, written in your
  script exactly as that string, so code can see each cue is used. Never write a number of
  seconds for when something happens. How long a move takes is yours: 0.2 to 0.8 seconds.
- `clock.lines["<frame id>"]` is `[start, end]` of each line, in seconds from the picture's
  first line. Use it only to hold or to time something to a whole line.
- The clock in your file is replaced before every render. Leave the block where it is.

## Component and custom direction

The picture brief includes `visual.component`, `variant`, `motion` and the person's
`direction`. Start from the adjacent themed starter HTML. Use the chosen component and
layout, adapting its objects and animation to the actual teaching point. For a custom
request use the elements in the starter wherever they fit. Draw additional shapes locally
with HTML and inline SVG and animate them on the same GSAP clock. Treat any description
as creative direction. Keep every label, quantity and relationship grounded in the source.
Apply the supplied palette and font roles to every element, including captions and charts.

## What makes it a good picture

- **It is finished at the end of every line.** Code takes a still just before each line ends.
  Each still must read on its own: what the line added is in place, nothing is half-way.
- **One thing leads.** The brief names each line's focal object. It is the largest or the
  brightest thing at that moment; the rest is quieter.
- **Fill the canvas.** The picture owns its whole canvas: lay it out to the edges with even
  margins, not as a small cluster in the middle. Text a viewer must read is at least 2.4% of
  the canvas height.
- **Keep the person's window clear.** The person can change the window size and shape on each line. When the brief gives `keep_clear`, put nothing there
  that has to be read; the presenter sits over it.
- **Nothing arrives before its word.** An object is not on screen until its cue. A held line
  adds to the picture; it never redraws it.
- **It never starts empty.** What sets the scene (a title, the frame things will arrive in) is
  there from the picture's first second, with no cue, so the first words are not said over a
  blank canvas.
- **Change, not only entrance.** Where a cue points at, counts, fills or moves something
  already there, do that rather than fading in a copy.
- **The look is the brief's.** Colours come from its palette and nothing else. The motion
  follows its motion note.
- **Its kind is the brief's.** `picture.kind` says what to draw (a diagram, a list, chips, code,
  an illustration, a slide) and `picture.arrangement` how it is laid out. When the brief has
  `picture.kind_chosen_by`, a person picked that kind over the plan's: draw the same objects
  and cues as that kind, even where a line's `shows_when_finished` describes another.
- For flow and sequence diagrams, use the brief's connections to identify the source,
  destination and cue for each arrow. Use a crossed path for a blocked request. Keep the
  arrow anchored to both participants as it appears, including across held lines.
- **It does not come or go by itself.** The film brings the whole picture in and takes it out
  (a cut, a push, a crossfade or a zoom) and may hold its last moment for half a second after
  its last line. Never fade, slide or scale the whole picture in at its start or out at its end.

Write the file and stop: do not render it, upload it or deliver it. Code reads it from your
folder, checks it and poses its stills.

Reply in two lines: the file you wrote, and anything in the brief you could not draw as asked.
When a turn opens with faults or a person's note on a still, change only what it names.

## Building to a motion plan

A rich picture's brief carries `motion_plan`: the plan written for it before this turn
(`briefs/motion.md`). Build that plan and nothing looser:

- The picture is the plan's `device`, set in its `world`.
- Each line is one shot. Its `hero` is the largest and slowest move of the line (0.5 to 1.2
  seconds); what `others` names lands smaller and faster.
- The line's still shows what its `still` says: that is what a person approves.
- A shot opens on what the shot before left. Nothing is cleared or redrawn between lines.

The cue keys and the clock are as above: the plan says how things move, never when.

## Looking at your stills

For a rich picture, a later turn gives you the stills code took of your file: one image per
line, at the end of that line. Open every one. Fix what only a render shows: two things
overlapping, a label cut off or too small, something under the person's window, a line whose
still does not show what the line added. Change nothing else. If they are right, reply
“Nothing to change.”
