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

## What makes it a good picture

- **It is finished at the end of every line.** Code takes a still just before each line ends.
  Each still must read on its own: what the line added is in place, nothing is half-way.
- **One thing leads.** The brief names each line's focal object. It is the largest or the
  brightest thing at that moment; the rest is quieter.
- **Fill the canvas.** The picture owns its whole canvas: lay it out to the edges with even
  margins, not as a small cluster in the middle. Text a viewer must read is at least 2.4% of
  the canvas height.
- **Keep the person's window clear.** When the brief gives `keep_clear`, put nothing there
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

Reply in two lines: the file you wrote, and anything in the brief you could not draw as asked.
When a turn opens with faults or a person's note on a still, change only what it names.

## Looking at your stills

For a rich picture, a later turn gives you the stills code took of your file: one image per
line, at the end of that line. Open every one. Fix what only a render shows: two things
overlapping, a label cut off or too small, something under the person's window, a line whose
still does not show what the line added. Change nothing else. If they are right, reply
“Nothing to change.”
