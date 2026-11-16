# Planning how one picture moves

A rich picture is planned before it is drawn. This turn you write that plan and nothing else:
no HTML. The next turn builds the picture to it, and a person reads it while that happens.

The turn names the picture's brief (`pictures/<id>.brief.json`) and the file to write
(`pictures/<id>.motion.json`). Read the brief whole: the canvas, the look, and every line with
what is said, what it adds, its objects and its cues.

The plan never changes what is said or when. The lines, the objects and the cues are the
episode's: every cue still lands on its word, and code sets every time. What you decide here
is how it looks and how it moves: what kind of picture this is, what each line opens on, the
one change each line is about, and what is on screen when the line ends.

## The file

```json
{
  "device": "one diagram that grows",
  "world": "A workbench seen from above, evenly lit. Every part is a paper card with an ink edge.",
  "shots": [
    {
      "frame": "c2.b1.f1",
      "shot": "A drawer slides out of the browser and opens in the middle: the cache.",
      "opens_on": "The bench with the browser card at its left edge, nothing else.",
      "hero": "On “store”, a drawer slides out of the browser card to the centre and settles, a third of the canvas wide.",
      "others": "Its label types on once the drawer has settled.",
      "still": "The browser card on the left, the open drawer in the centre with its label, the right third empty for the server."
    }
  ]
}
```

- `device`: how this picture carries its idea. One of the nine below, word for word.
- `world`: one line on where the picture happens: its ground, its light, its scale and the one
  material its things are made of, taken from the subject (a desk, a machine, a page, a map).
  Name colours by the look's roles (ground, panel, ink, accent), never as values.
- `shots`: one for every line of the brief, in the brief's order.
  - `frame`: the line's id, as the brief gives it.
  - `shot`: the shot in one plain sentence of at most twenty words. A person reads it beside
    the line in the script, so say what they will see happen, with no measurements and no
    colour roles. The detail goes in the fields below, which are for the builder.
  - `opens_on`: what is on screen as the line starts. For the first line, what sets the scene:
    it is there from the first second with no cue. For a later line, what the line before left.
  - `hero`: the one change the line is about, as motion: what moves, from where to where, and
    how it lands. Say the spoken word it starts on.
  - `others`: how the line's other cues land around the hero, in a sentence. Empty when the
    hero is the line's only cue.
  - `still`: what is on screen just before the line ends, in one sentence. Code takes a still
    there and a person approves the picture by it.

## The device

| Device | The picture is |
| --- | --- |
| the object is the explanation | one machine or model whose working is the idea; the view tours it |
| one diagram that grows | the simplest true diagram, one part arriving per line |
| continuous transformation | each step morphing out of the one before |
| the worked example | one real input travelling through every step |
| steps in order | a sequence, the current step lit and the done ones settled |
| two sides | one thing against another, built side by side |
| one chosen out of many | a field of options, one picked out |
| a number that lands | a value counting to its figure, with the thing it measures |
| a real screen, the detail circled | an interface or a page drawn plainly, one part marked |

## What makes a plan worth building

**The picture**

1. **A world, not a slide.** Things sit somewhere and are made of something. A row of boxes
   with labels is the failure this plan exists to avoid.
2. **Draw what a thing is.** A drawer, a ticket, a stack of pages, a stamp: not a box that says
   "cache". A label rides on the thing it names.
3. **It fills its canvas.** The thing a line is about takes 40 to 60 per cent of the canvas.
   When the brief gives `keep_clear`, nothing that must be read sits there.
4. **Every object of the brief is in it, once.** An object with no cue is there from the first
   second. You add no object that carries words the plan does not have.

**Each shot**

5. **One hero.** It is the change the line is about, which is usually the line's focal object
   developing. A heading or a label arriving is never the hero. When the line is a set of
   items arriving, the set is the hero and each item lands on its own cue the same way.
6. **Nothing arrives before its cue.** A shot's moves start on the line's cues, in their order.
   Never give a number of seconds for when something happens.
7. **Change, not only entrance.** Where a cue points at, counts, fills or moves something
   already there, the hero does that. When two heroes in a row are both arrivals, the second
   arrives another way (it unfolds, it is drawn, it drops in), on the same object the line
   names.
8. **The rest supports.** Other cues land smaller and faster than the hero, as a group where
   they are close together.
9. **A shot opens on the last one's still.** A later line adds to the picture or changes it. It
   never clears it and never redraws it.
10. **It ends still.** By the end of the line everything it added is in place and nothing is
    half-way. The view is still while the viewer reads: at most one slow push in a shot, and
    only after the hero has landed.

**Never:** glow or particles as decoration; small things floating in a dark void; everything
fading and sliding up the same way; three equal cards in a row as the whole picture; anything
that breathes, floats or loops; the whole picture fading in or out (the film brings it in and
takes it out).

Write the file and stop. Reply in two lines: the device and why it fits, and anything in the
brief the plan could not carry. When a turn opens with faults, change only what they name.
