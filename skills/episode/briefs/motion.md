# Planning one picture: its spec

A motion-graphics picture is planned before it is drawn, the way HyperFrames plans a film:
three treatments in words, one picked, then a spec with a number wherever an adjective would
go. This turn you write that plan and nothing else: no HTML. The next turn builds the picture
to it, and a person reads it while that happens.

Read first, in the HyperFrames guides the turn names:

- `types/explainer.md`: what makes a picture explain. Ground it, the devices that explain, the
  shapes of information, the tells.
- `spec.md`: the spec's lines, turning words into numbers, the composition numbers, what is
  banned by default, a look built from a medium.
- `motion.md`, "Motion craft": the measured numbers for moves, eases by role, overlaps, holds.
- `story.md`, section 2, for how three treatments differ; `look.md` for where a look comes from.

Those guides are written for a whole film made in one go by an agent with a shell. Here the
film exists: its script is written and approved, you plan one picture of it, and you have no
shell (the house runs the renderer's check and takes the stills). Where they and this page
disagree, this page wins, and these parts of theirs are not yours: the stop for a person to
pick a storyline; `STORYLINES.md`, `SPEC.md` and `REVIEW.md` as files; the CLI; sound and
music; the hook, the end card and the brand's mark.

The turn names the picture's brief (`pictures/<id>.brief.json`) and the file to write
(`pictures/<id>.motion.json`). Read the brief whole: the canvas, the look, and every line with
what is said, what it adds, its objects and its cues.

## What is fixed, and what is yours

Fixed, because it is the episode's: what is said and when; the lines, the objects and what each
means; the cues and the word each lands on (code sets every time from the voice); the canvas
and `keep_clear`; the brand's palette and type.

Yours: the treatment (where it happens, what carries the idea, how the view carries it); how
each thing is drawn so it reads as what it is; how every shot is framed and how the view
moves; how things move, by role; what moves in the stretches the cues leave quiet; and what
the picture must not become.

## Three treatments, then one

Before any shot, write three treatments of the picture. They are three different pictures,
not three names for one: each has its own **world** (where it happens and what it is made of),
its own **device** (the table below) and its own **form** (how the view carries it: one frame
that rebuilds, a tour through one object with a dive into the part that matters, a chain where
each thing becomes the next, several panes that collapse into one). Sketch five first, a line
each; keep the three that differ most, one of them the bold one you would not have picked
first. Then pick the one a stranger would follow and remember, ahead of the most striking
frame. A treatment in which every line is "a box appears" has not tried the forms.

Nobody is asked to choose: `treatments` keeps the three, a line each with the picked one
first, so a person reading the plan can ask for another.

## The file

```json
{
  "treatments": [
    "Picked: the stockroom. A storeroom seen from above; the object is the explanation; a tour that dives into the one shelf. A stranger knows a storeroom, and the cache's rule is where things are shelved.",
    "The ledger: one page of a paper ledger; one diagram that grows; one frame that rebuilds. Clear, but it is a table of labels.",
    "The relay: three runners on a track; the worked example; a chain. Bold, but the baton hides which copy is kept."
  ],
  "device": "the object is the explanation",
  "world": "A stockroom seen from above, evenly lit. Every part is a paper card with an ink edge on the brand's ground.",
  "look": "Ground #ffffff with the look's dot texture at 16%. Ink #000000 lines 3 px, corners 10 px. Accent #6d28d9 on the one part a line is about, nowhere else. Labels Inter 600 at 34 px, the hero's label 44 px (the floor is 28 px). Paper and ink: flat fills, a contact shadow 0 6px 0 at 8% under what sits on the bench, no gradients, no glow.",
  "objects": "Browser: a window frame with a toolbar and three dots, 380 px wide. Cache: an open drawer with file tabs, not a box named cache. Server: a rack of three units with status lights. A response: a dog-eared sheet that travels.",
  "motion": "Arrive on expo.out, 0.6 s, the hero 0.9 s. Camera and anything travelling on power2.inOut, 0.9 s. What leaves or recedes on power3.in, 0.35 s. Drawer and chips settle on back.out(1.4); nothing else springs. The next thing starts when the one before is 40% done; items of a set 60 ms apart.",
  "banned": "A row of labelled boxes; three equal cards; every part fading up the same way; one curve on every move; a label arriving as the hero; glow; anything that floats or breathes; the whole picture fading in.",
  "shots": [
    {
      "frame": "c2.b1.f1",
      "shot": "A drawer slides out of the browser and opens in the middle: the cache.",
      "opens_on": "The bench with the browser card at its left edge, nothing else.",
      "hero": "On “store”, a drawer slides out of the browser card to the centre and settles, a third of the canvas wide.",
      "others": "Its label types on once the drawer has settled.",
      "camera": "Framed on the browser and the empty bench, the browser 45% of the canvas high. After the drawer lands, the view pushes in 12% on the drawer and holds.",
      "between": "From “every time” to “instead”, 4 s with no cue: a response sheet travels from the server's edge into the drawer, the thing those words describe.",
      "still": "The browser card on the left, the open drawer in the centre with its label, the right third empty for the server."
    }
  ]
}
```

- `treatments`: the three, a line each, the picked one first and marked "Picked:".
- `device`: how this picture carries its idea. One of the nine below, word for word.
- `world`: one line on where the picture happens: its ground, its light, its scale and the one
  material its things are made of, taken from the subject (a desk, a machine, a page, a map).
- `look`: the picture's LOOK line, as numbers. The ground and its texture, the ink and where
  the one accent may appear, all as the brief's palette gives them; the sizes of what is read,
  in pixels for this canvas (never under 2.6% of its shorter side); the medium and its
  numbers (line weight, corner, a contact shadow's offset and strength, grain). A look holds
  together as the rules of one medium, not a palette; the colours are still the brand's.
- `objects`: every thing the lines name, drawn with the material and the detail that make it
  read without its label: a drawer with tabs, not a box named "cache".
- `motion`: the eases by role as named curves, the durations and the stagger, in seconds.
  Arrivals, the camera and what travels, what leaves, and what (if anything) springs.
- `banned`: what this picture must not become: the defaults of `spec.md` it is most at risk of,
  by name, and the way this subject usually goes wrong.
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
  - `camera`: how the shot is framed, and the one move of the view if it has one. Say what
    fills the frame (the thing the line is about takes at least two fifths of the canvas's
    height or width), then the move: from which framing to which, and what it waits for.
    "Holds" when the view does not move.
  - `between`: for each stretch of the line where the cues leave more than three seconds with
    nothing changing, the move that fills it and the words it rides. It acts on what is
    already there and is caused by what is being said: something travels, counts, works,
    or the view moves to the part the words are on. Empty when the cues leave no such stretch.
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
   "cache". A label rides on the thing it names, with a leader line when it needs one.
3. **The view makes the hero large.** The thing a line is about takes at least two fifths of
   the canvas. When the whole picture is wider than that allows, the shot frames tight on the
   part and pulls back to place it. When the brief gives `keep_clear`, nothing that must be
   read sits there in any framing.
4. **Every object of the brief is in it, once.** An object with no cue is there from the first
   second. You add no object that carries words the plan does not have.

**Each shot**

5. **One hero.** It is the change the line is about, which is usually the line's focal object
   developing. A heading or a label arriving is never the hero. Everything else travels half
   to two thirds as far and starts a moment after it.
6. **Nothing arrives before its cue.** A shot's cue moves start on the line's cues, in their
   order. Never give a number of seconds for when something happens: say the word, or the
   move it follows.
7. **Change, not only entrance.** Where a cue points at, counts, fills or moves something
   already there, the hero does that. When the brief's cues are all arrivals, each arrives a
   different way and out of something already on screen (it unfolds from, splits off, is
   drawn by, drops out of), never four fades in a row.
8. **Something new every two to four seconds.** A stretch of more than three seconds with
   nothing changing is where a picture goes dead, and the renderer measures it. `between`
   fills each one with a move the words cause. Never an idle loop, a float or a creeping
   scale: those read as a picture with nothing to say.
9. **What is done recedes.** A later line adds to the picture or changes it. It never clears
   it and never redraws it; what an earlier line finished may dim or step back so the eye has
   one place to go.
10. **It ends still.** By the end of the line everything it added is in place, the view has
    settled and nothing is half-way. Whatever is being read does not move.

**Never:** glow or particles as decoration; small things floating in an empty ground;
everything fading and sliding up the same way; one curve on every move; three equal cards in a
row as the whole picture; anything that breathes, floats or loops; the whole picture fading in
or out (the film brings it in and takes it out).

Write the file and stop. Reply in three lines: the treatment you picked and why; the two you
passed over; anything in the brief the plan could not carry. When a turn opens with faults,
change only what they name.
