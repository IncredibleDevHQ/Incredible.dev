# From a beat to a frame

A beat is the story: what is said and what job it does. A frame is how that stretch is shot.
The same beat can be shot several ways: in the published films 25 of 30 common beat subtypes
were shot two or more ways. So a frame is a choice, the plan keeps the other choices, and a
person can take one of them.

## What a frame is

A frame has three parts, chosen separately:

| Part | What it says | Who decides |
| --- | --- | --- |
| Presence | Who has the frame: the `person`, the person with content (`both`), or `content` alone. | The classifier, from the line and from `shows`. A person can override. |
| Layout | How the frame is laid out, picked from the theme's kit for that presence. | The writer suggests a layout. Code checks the presence and theme. A person can override. |
| Picture | What fills the content area: a list, a diagram, code, a recording. | The classifier, from `shows`. |

The three-way presence is the studio's recording switch (person, person with content,
content), and it is the first thing a person changes. The detailed layout is the second.

**Who has the frame is not in the words.** In the published videos the theme's usual layout
matches who had the frame for 71% of beats, and reading the line adds nothing to that. So the
plan does not pretend to know. It works like this:

- The classifier reads one thing from a line: how strongly it is the person's (`p`), as
  against needing something shown.
- The theme sets the bar. A line goes to the person when its `p` clears the theme's
  `person_from`: 0.5 where the presenter often has the frame, 0.9 where a panel is always on
  screen. Otherwise something is shown, beside the person or alone as the theme has it.
- A line that reads as the person's but does not clear the bar needs no picture of its own.
  It **holds** the picture before it. Code marks this for you.
- You may say what you meant: `"wants": "person"` (or `both`, `content`) on a frame. It stands
  when the reading gives it 0.25 or more; under that, the report says it was
  overruled, and the line itself has to change. Writing `shows` on a frame says something must
  be seen, and after that the line no longer reads as the person's.
- A person can override any of it afterwards. See `plan.md`, "When a person changes who has the frame".

## The theme decides the kit

The theme is chosen once, in the brief, and usually once for a whole series. It sets the
stage, the few layouts the film uses, the overlays, the marks and how things move. A frame
picks from the kit; it does not invent. Published films use three layouts in the middle case,
and the top two carry 87% of the running time. Three of the six concept explainers hold one
layout (a panel beside a portrait) for nine tenths of their length.

Set `layout_intent` on a new shot when a layout in the kit fits the line. Keep the lower
edge of a timeline clear with an upper corner window. Give a compact fact its own floating
card. A short viewer question can sit below the presenter as they answer. Keep the same
layout across a held diagram. With narration alone, center a key measurement in a number
spotlight or introduce the next section with a chapter banner. An omitted or incompatible suggestion uses the theme default,
and the person's studio picks take precedence.

## One beat, one to three frames

- Each beat has one frame. Keep that unless a rule below says otherwise.
- **Cut a frame at a sentence start.** 56% of real cuts fall within half a second of one, and
  the picture leads the word.
- **A frame can hold the picture before it.** Set `"hold": true`. In the published films 61%
  of beats begin inside a shot, and about half of all chapter starts have no cut at all: the
  words carry the join. A run of beats over one growing diagram is one picture held, not five
  pictures. What a hold means:
  - It keeps the presence, the layout, the picture and the arrangement of the frame before,
    and there is no transition into it.
  - It may add to the picture: list only the objects it adds, and write cues as usual. A cue
    may move any object of the picture it holds, by the id that object already has.
  - With nothing of its own it is simply the picture staying while the line is said.
  - A frame after a person frame can hold too: the person stays.
- **Words in a frame.** Said to camera: 18 words in the middle case; over 45 is worth a look.
  Beside a picture: 40 in the middle case, 70 at most. Content alone: 20, at most 60. A longer
  stretch over a picture needs the picture to keep changing.
- **Bring the person back for the frame of the story.** When a published film changes layout
  at a beat that turns, guides or closes, two times in three it returns to the person. The
  promise, the chapter's question, a turn, a judgment, the landing and the goodbye are said to
  camera when the theme has a person layout; the material is said beside its picture (a
  mechanism is to camera for 2% of its words).
- **The presenter is not away long.** In concept explainers the person is off screen for ten
  seconds at a time in the middle case and about a minute at most.

## Pictures: cheap ones are first-class

Fourteen picture types in four groups (`types.md`). A film does not need motion graphics in
every frame. A list that builds, three chips, one number on a card or a plain slide carry a
line as well as a diagram does, and cost a tenth of it. Reach for a diagram when the line is a
mechanism, a comparison or a structure, because those have parts and relations to show.

| The beat | A picture that fits |
| --- | --- |
| Definition | A term and one line; a slide; chips |
| Mechanism | A diagram that grows: a pipeline, a hub, a loop |
| Worked example | The same diagram with the case's own labels; a chat or a screen mock |
| Contrast, options | Two sides; a row of comparison cards |
| A list, an agenda, a recap, advice | A list or chips, one per phrase |
| Evidence | One number card; a bar that counts up |
| Code | Typeset code with lines that light |
| Demo | A recording |

## Designing a built picture

For each frame that shows content, write four things.

- `shows`: one or two plain sentences saying what the viewer sees when the frame has finished.
  Name the things and where they sit ("the request on the left, three specialists in a row on
  the right, a router between them"). No colours, fonts or pixel sizes: the theme draws.
- `objects`: the things on screen. Each has an `id`, `what` (a few words describing it),
  `words` (the text it carries, six words at most, never the spoken sentence) and a `state`
  (`plain`, `active`, `good`, `bad`, `dim`). The classifier gives each its type.
- `focal`: the id of the one object the eye should follow. One per frame.
- `cues`: what happens, and on which spoken word. See `motion.md`.

Rules:

- **A picture holds what the line names, nothing else.** If the voice names three parts, the
  picture has three parts.
- **Keep one picture and grow it.** The next beat adds to the diagram, lights a part of it or
  changes a state. A new picture for every beat is a slide show.
- **The case wears the diagram.** When the beat is a worked example, reuse the mechanism's
  picture with the case's own labels.
- **Words on screen are labels.** Six words at most. The digits of a figure go on screen; the
  voice spells it out.
- A recorded picture (a terminal, a product screen, a page) lists no objects. Say in `shows`
  what the recording must show, and add cues only for what is laid over it.

## Overlays on the person

A person-only frame may carry one overlay object and no picture: the name (once, at the first
appearance, four to eight seconds), a new term the moment it is first said, a link pill at the
ask. An overlay is an object with a cue, like any other. The overlay types (name block, term,
link pill, and the rest of the "on the person" family) exist only on person frames; inside a
built picture a label is a keyword, a callout or a chip.

A recorded picture (a terminal, a product screen, a page, an output) lists nothing that is
built. It may carry objects laid over it (a callout, a keyword), with cues. When the notes
say a demo exists but not what was typed or what came back, plan the recording and say in
`shows` what it must show; never write the demo's text yourself.

A held frame and a person frame need no `shows` and no `focal`.

## What a person may change, and what follows

Every frame keeps `options`: the theme's layouts ranked for it, for a person to pick from.

### Data for visual components

Put structured facts on the objects they describe so the component classifier and builder
can reuse them without a separate model call. Keep the visible label in `words`. For a chart
point give its numeric `value`, common measurement `unit`, and optional `series`. A sequence
message names its participants in `from` and `to`. A directed edge uses the same fields;
a child node may name its parent's ID in `parent`, and a step its lane in `owner`. Only
supply measurements, relationships, and message directions supported by the source.


## Illustrated scenes

Use the reusable illustration component for recognizable subjects. Set each object's `asset`
to phone, satellite, cloud, pin, browser, server, storage, document, person, shop, bank or
object. Keep the same ID when a subject returns. Write a compact `words` label.
On a frame use `camera: "overview"` for relationships, `"focus"` to inspect its `focal`
object, and `"reset"` to return to context. `visible` lists the supporting object IDs the
shot needs. Include the target of every cue. Omit background detail when it adds clutter.
The renderer measures the presenter exclusion area and label bounds, uses a readable grid
or a hero with supporting subjects, and limits artwork scaling inside each slot.
Zoom should answer a visual question, with a reset before another overview or comparison.
Choose another frame or a content-only layout when a readable scene cannot fit.
