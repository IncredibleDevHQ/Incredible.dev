# The plan's sections

A plan is a set of JSON files in `/workspace/projects/<slug>/plan/`, one section each. Each is one
frame of the plan's board. Write lengths in `seconds` and the words; never a time range, a word
count or a check result, which are worked out from the sections.

A plan is words, read before anything is built. Say where a thing is and what it looks like in
words a person would use ("the question card, top of the frame, unchanged"). Never give
positions or sizes in pixels, font names or sizes, or colour values: the storyboard has the frame
in front of it and measures those. Say a rule once, where it belongs, and do not repeat it on
every row. A section with a field that runs long, or with pixels in it, is sent back.

| On | The most words a field runs to |
| --- | --- |
| A row of a list or the spine | `text` 80, `detail` 80 |
| A row of the ledger | `claim` 35, `quote` 60 |
| A row of the chapter list | `asks` 40, `ends` 45, `shape` 12, `covers` 80, `handoff` 45, `cue` 25, `turn` 30, `first` 26, `last` 16 |
| A beat | `takeaway` 35, `says` 70, `focal` 20, `change` 80, `result` 45, `enters` 30, `leaves` 30, `claim` 60 |
| A shot | `move` 6, `shows` 60, `on` 16, `sound` 20 |

| File | Board | Board name | `section` | Written by |
| --- | --- | --- | --- | --- |
| `brief.json` | the brief's | Brief | `list` | the brief step |
| `claims.json` | the brief's | Claims | `claims` | the brief step |
| `spine.json` | the plan's | Spine | `spine` | the spine step |
| `chapters.json` | the plan's | Chapters | `chapters` | the chapter-list step |
| `sound-look.json` | the plan's | Sound and look | `list` | the chapter-list step |
| `<chapter>.beats.json` | the plan's | the chapter's name | `chapter` | that chapter's beats step |
| `<chapter>.shots.json` | the plan's | the chapter's name | `shots` | that chapter's shots step |

`<chapter>` is the chapter's name in lower case with hyphens: "Chapter 2" is written to
`chapter-2.beats.json` and `chapter-2.shots.json`.

## A list (the brief, the sound and the look)

```json
{"section": "list", "rows": [
  {"id": "idea", "label": "The one idea", "text": "Search finds the page you mean by comparing where meanings sit, not which words match."},
  {"id": "gap", "label": "The gap it closes", "text": "You type what you want in your own words, and cannot see how search finds a page that shares none of them."},
  {"id": "length", "label": "Length", "text": "5 minutes at 1920 × 1080, led by the voiceover.", "seconds": 300},
  {"id": "source", "label": "Made from", "text": "“How our docs search works”, the Example Studio engineering blog, 2026.", "names": ["Example Studio"], "files": ["/workspace/attachments/how-our-docs-search-works.md"]},
  {"id": "label", "label": "Made up is marked", "text": "Illustrative"}
]}
```

The brief's rows are `idea`, `gap` (what the viewer cannot do or see before the film: the
first line opens it), `for` (who it is for), `length` (with `seconds`, the whole episode), `source` (what it is made from, with `names`: what the voice would call whoever the
facts come from, and `files`: the material's paths), `label` (the one word the picture carries
for made-up material; there whenever the ledger marks a claim illustrative) and `leaves` (what
it leaves out). The sound and the look's rows are `voice`, `music`, `look` and `picture` (the
picture the episode returns to).

## The ledger

One row per thing the film may state as a fact. `status` is `stated` (the material says it;
`quote` gives its own words, word for word, cut with … where it runs long), `illustrative` (made
up to show the idea) or `unconfirmed` (the material does not say it, so the film does not
either). The canvas looks every quote up in the material and marks the ones it cannot find.

```json
{"section": "claims", "rows": [
  {"id": "c1", "claim": "The search turns every passage into 384 numbers before anyone asks a question.", "quote": "we embed each passage ahead of time … into a 384-dimensional vector", "status": "stated"},
  {"id": "i1", "claim": "The query “reset my password” and the page “Account recovery” stand in for a real search.", "status": "illustrative"}
]}
```

## The spine

Three candidates, exactly one `picked`. `text` is the thing the viewer follows, in a sentence;
`detail` is why it would or would not carry every chapter.

```json
{"section": "spine", "rows": [
  {"id": "A", "label": "A · Follow the question", "text": "The query “reset my password” travels through every stage of the search until it comes back as the page “Account recovery”.", "detail": "Every chapter does something to the query, so every beat has the same thing to point at.", "picked": true}
]}
```

## The chapter list

One row per part, in order: the open, the chapters, the close. `shape` is the form of its
argument, in a few words. `covers` is its share of the material: which part it uses, which
claims are its to make, and what it leaves to the chapters beside it. `handoff` is what crosses
the cut into the part (every row after the first has one). The first row carries the film's
first spoken line (`first`) and the kind of hook it is (`hook`: question, surprising number,
counterintuitive claim, shared pain, metaphor, scenario or stakes); the last row carries its
last spoken line (`last`) and how that line lands the idea (`landing`: callback, distillation,
generalization or invitation). Exactly one chapter between them carries `turn`: the moment the
film pivots on, as the viewer sees it happen. `asks` is one question.

```json
{"section": "chapters", "rows": [
  {"label": "Open", "title": "The question", "seconds": 20,
   "asks": "You typed “reset my password”. The page is called “Account recovery”. How did search find it?",
   "ends": "The mismatch is on screen: not one word in common.",
   "shape": "A question, asked with the real input",
   "covers": "The question only: the three words typed and the page that answers them.",
   "cue": "Key clicks, then a rising tone",
   "first": "You type three words into a docs search.", "hook": "scenario"},
  {"label": "Chapter 1", "title": "Matching words", "seconds": 55,
   "asks": "Why can't search just match the words?",
   "ends": "Word matching puts “Password policy” first and never sees the right page.",
   "turn": "The ranked list comes back with “Password policy” on top, and “Account recovery” is not on it at all.",
   "shape": "The naive version, then where it breaks",
   "covers": "Keyword search: the question split into words, the index of pages by word, and the ranked list that misses the right page.",
   "cue": "The pulse thins, then drops out",
   "handoff": "The query chip leaves the search box and arrives above the word index: no cut."},
  {"label": "Chapter 2", "title": "Meaning as a position", "seconds": 65,
   "asks": "If not words, what can search compare?",
   "ends": "On a map of meaning, the question lands next to “Account recovery”.",
   "shape": "One diagram that grows",
   "covers": "Embeddings: text into numbers, numbers as a position, and the docs placed on the same map ahead of time. Finding the nearest passage is the next chapter's.",
   "cue": "A pad lifts, with a chime on the join",
   "handoff": "The query chip leaves the failed list and arrives at the mouth of the model: no cut."},
  {"label": "Close", "title": "The answer", "seconds": 30,
   "asks": "So what comes back to the search box?",
   "ends": "“Account recovery” sits at the top of the list.",
   "shape": "A before and after",
   "covers": "The whole trip in one picture.",
   "cue": "The pulse resolves",
   "handoff": "The ranked list rises into the search box: no cut.",
   "last": "Search doesn't look for your words. It looks for your meaning, nearby.",
   "landing": "distillation"}
]}
```

## A chapter's beats

The beats of one chapter, in order, adding up to its `seconds` in the chapter list. A beat has
no shots in this file: they are written from it afterwards, in their own. `says` is the passage
the voice says over the beat, word for word, with each figure written the way it is said (an
empty string for a beat that plays in silence);
`technique` is how the beat makes its point land: worked example, analogy, cause and effect,
contrast, counterexample, build-up, demonstration, number made visible, question and answer,
callback or distillation.

```json
{"section": "chapter", "title": "Meaning as a position", "beats": [
  {"id": "2A", "title": "Text becomes numbers", "seconds": 16,
   "takeaway": "A model turns any piece of text into a long list of numbers.",
   "technique": "demonstration",
   "says": "Modern search hands your question to a model that reads it whole. What comes out is a row of three hundred and eighty-four numbers.",
   "focal": "the model the chip passes through",
   "demands": ["the chip going in", "the numbers coming out"],
   "change": "The chip goes into the model. A row of numbers comes out the other side and keeps unrolling while a counter runs up to 384.",
   "result": "The question is now a row of 384 numbers.",
   "enters": "the query chip", "leaves": "the query, as a row of numbers",
   "claim": "Needs a source: 384 is the output size of one common small embedding model."}
]}
```

## A chapter's shots

Every shot of the chapter, each naming its `beat`. The shots of a beat add up to that beat's
`seconds`, and their `vo` lines add up to its `says`, word for word. `at` is when the words on
screen land, in seconds from the shot's start; leave it out when they are there from the start.

```json
{"section": "shots", "shots": [
  {"beat": "2A", "id": "2A.1", "seconds": 8, "move": "Transform",
   "shows": "The chip enters a box labelled as the model.",
   "vo": "Modern search hands your question to a model that reads it whole.",
   "on": "embedding model", "at": 2, "sound": "a soft whirr"},
  {"beat": "2A", "id": "2A.2", "seconds": 8, "move": "Count up",
   "shows": "A row of numbers unrolls from the box while a counter runs up.",
   "vo": "What comes out is a row of three hundred and eighty-four numbers.",
   "on": "384 numbers", "at": 3, "sound": "a run of soft ticks"}
]}
```
