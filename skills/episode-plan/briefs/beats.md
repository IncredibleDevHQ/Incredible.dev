# One chapter's beats

The plan's top layer is signed off. You write the beats of one chapter from its row in the
chapter list, and with them every word the voice says in it: you are the one writer of this
chapter with the material open. Its shots are written from your beats next, by someone who has
only the plan and cuts your words into lines without changing one, so what a beat leaves open
stays open on screen.

## Read

- The plan's top layer, as your brief lists it. Your chapter's row is your contract: its
  question, the result it ends on, its shape, what it covers, its seconds and its handoff. Read
  the rows before and after it, so you know what the viewer has just seen and what comes next.
- `brief.json`, `claims.json` and the material the brief's `source` row names. Take your facts
  from the ledger and the material, word for word where it is a number or a name, and stay
  inside what your row `covers`: the other chapters are being written from the same material at
  the same time. A fact the ledger marks `unconfirmed` stays out.
- [../../storyboard/references/beats-and-handoffs.md](../../storyboard/references/beats-and-handoffs.md):
  the beat row. An episode's beat is that row without its exact on-screen words, read window and
  sound accent, which its shots carry.
- [../references/sections.md](../references/sections.md) for the form of what you write.

## A beat

A beat is one change on screen that lands one point. Two to five to a chapter, 10 to 30 seconds
each, adding up to the chapter's seconds exactly.

- `takeaway`: the one point, as a full sentence the viewer could repeat. It explains: it says
  how or why, not only that something was reported. "The team reported it worked" is a result;
  "each helper reads in its own window, so together they read more than one could hold" is the
  explanation. Give the reason, then the number that backs it. Who said it and what is made up
  go in `claim`, never in the takeaway.
- `technique`: how the beat makes that point land. One of these, written exactly so.
  - To make it concrete: worked example (the spine's own values go through the mechanism, and
    the voice says what happens to them) or analogy (a thing the viewer already knows stands
    in for the one they do not, and the beat shows where the likeness holds).
  - To show it happen: demonstration (the mechanism runs on screen while the voice says why
    each step is there), cause and effect (this, so that) or build-up (one layer at a time,
    each resting on the last).
  - To set it against something: contrast (before and after, the naive way and the real one)
    or counterexample (where the simple version breaks).
  - To weigh it: number made visible, or question and answer.
  - To land it: callback (an earlier picture returns) or distillation (the idea in one line).

  The passage and the change must do what the name says: an analogy has the other thing in
  it, a worked example has its values, a demonstration has something running. A beat that
  only states a rule does none of these: put the example through it, or say what it is like.
  Vary them. A chapter of four beats or more does not land over half of them the same way,
  and a chapter that explains how something works makes it concrete at least once.
- `says`: the passage the voice says over the beat, word for word. See "The voice" below.
- `focal`: the one object to watch.
- `demands`: each separate thing the viewer must work out, listed. One or two. A third means two
  beats.
- `change`: what develops on screen, concretely, start to end. This is the field the shots are
  written from. "The title appears and the cards fade in" is not a change: say what turns into
  what, what moves where, what is counted, sorted, split or joined.
- `result`: what is on screen when the beat ends, that was not there when it began.
- `enters` and `leaves`: the object that crosses into the beat and the one that crosses out. Use
  the spine's example wherever it can carry the cut. Where nothing spans it, write
  "semantic handoff" and say what it is.
- `claim`: the rows of the ledger the beat states, by id ("c4, c5"), and anything on screen
  that is illustrative; nothing when it states no fact.

Write a beat in words. No positions or sizes in pixels, no fonts, no colour values: say what the
thing is and what it does, and the storyboard will measure where it sits.

## The voice

`says` is narration, written to be heard once by someone who has not read the material.

- It lands the takeaway by the end of the beat, in the viewer's words. Where the picture shows
  a thing, the voice says why it matters; it does not read the picture out.
- The example before the rule. Say what happens to the spine's example, then the rule it
  shows, in the same breath or the next. "The model converts text into a vector" reports;
  "“reset my password” goes in, and what comes out is a position on a map" teaches. A
  sentence about the system is a claim. The same sentence about the example is an
  explanation.
- A word the viewer does not own is made concrete the first time it is said: what it is like,
  or what it does to the example. The brief's `for` row says what they already know.
- Whole sentences someone would say aloud to a colleague, one idea each, with the plain words
  and contractions of speech. A sentence under six words is a question or a punch, not the
  norm: a chapter keeps two, or one in three of its sentences, whichever is more. A run of
  them is captions read aloud.
- Vary the stride. Most sentences run ten to twenty words; where a point lands, a short one.
  A chapter of six sentences or more with none under nine words is a lecture.
- It explains; it never credits or disclaims. No line points at the material ("the article
  says", "according to"), and the chapter names where its facts come from once at most. Nothing
  spoken says a thing is made up: the picture carries the brief's `label` for that.
- Write a figure the way the voice says it: "three hundred and eighty-four", "twenty
  twenty-five", "ninety percent". Then it is said one way through the film, and its time is
  counted right. A number that is part of a name stays as the name is written. Say only the
  figures the viewer must hear, rounded where the picture shows the exact one: the digits
  belong on screen.
- A name that is also an everyday word is said with its noun ("the Research feature"), so it
  cannot be heard as the word.
- It fits. A voice reads about 2.2 words a second, a shot carries 26 words at most, and each
  shot's line needs half a second of air, so a 12-second beat holds 25 words at the very most.
  Aim for two thirds of what would fit: the picture needs room, and a tight passage is a better
  passage.
- A beat with nothing to say stays silent: `says` is an empty string, and its change carries it.
  Where the example runs or the diagram builds, let the picture work: the script should feel
  shorter than the film.
- The open starts on the chapter list's `first` line and the close ends on its `last`, word for
  word. They were signed off with the list.

## From the row to the beats

- The first beat starts from the chapter's handoff: its `enters` is that object, as the row says
  it arrives.
- The passages read aloud, one after another, answer the chapter's question. Read them that way
  before you report: if they sound like labels, you have a list, not an argument.
- Where your row's `covers` says the brief's idea is first said, say it outright, for the ear.
  The brief's sentence was written to be read: keep its nouns, and make it a line someone
  would say. Later chapters call those nouns back; they do not repeat the sentence.
- If your row carries the film's `turn`, one of your beats is it. Show it happen: the picture
  does it, and the voice does not announce it. Give it room: a short line before it, and a
  moment after in which nothing new is said.
- Finish one subject before the next begins. A chapter that leaves a subject and comes back to
  it two beats later has its beats in the wrong order, or carries a subject too many: say so
  in your report, and write the chapter its question asks for.
- The last beat's `result` is the chapter's `ends`, on screen.
- The chapter follows its `shape`. Build the opposing case at its strongest before you show
  where it breaks.
- Number the beats with the chapter: 2A, 2B, 2C for chapter 2; O1, O2 for the open; C1, C2 for
  the close.

## Report

The chapter in a line. Then your file as JSON, whole. If the row asks for something the material
does not support, say so in the report and write the beats the material does support.
