# From notes to a script

The numbers on this page were measured on 43 published technical videos (87,740 spoken words,
2,449 beats), and where it says so, on the eight explainers among them. They are the middle
case, not a law. The checks hold the ranges.

## What the notes give you, and what you add

In a published explainer about half the words restate the material: definitions, mechanisms,
steps, lists, differences, numbers, advice. The other half was written for the script:

| Words | Share | Where they come from |
| --- | --- | --- |
| The material | 46 to 55% | The notes. Reworded for the ear, never changed in substance. |
| A made-up case | 0 to 35% | You. One concrete case, plus an analogy or two. Marked `made_up`. A video that walks one case through every chapter spends a third of its words on it; one that explains a single mechanism, under a tenth. |
| The frame and the turns | 25 to 42% | You. The opening, the questions, the so-whats, the signposts, the recap, the landing, the ask. |

So a script that only restates the notes is half a script. And a fact that is not in the notes
is not yours to add: if the route needs one, say what is missing in your report.

## The brief

- `idea`: the one sentence a viewer should leave with. A claim, not a topic. "Caching" is a
  topic; "a cache is a bet on what you will ask for next" is an idea.
- `gap`: what the viewer does not know or cannot do before watching. The video exists to close
  it, and the first chapter's question comes from it.
- `for`: who it is for, in a few words.
- `seconds`: the length. `presenter`: `on` or `off`. `theme`: one id from the themes list.
  `series`: `none`, or the series' name and this video's place in it.
- `case`: the one concrete case the video sets up and returns to: `{"text": ..., "from":
  "notes" | "made up"}`. Every tutorial explainer measured carries one, and four of the six
  concept explainers. Pick a case from the viewer's own world on which every chapter's answer
  can be shown: a support request, one prompt, one image. If the notes hold a real one, use
  it. One case, carried, beats three unrelated examples.
- `voice`: `{"sentence_words": 8 | 12 | 18, "person": "you" | "we" | "I"}`. Sentence length
  is a voice a series keeps: short lines (8 words in the middle, a third of them under six), a
  walk-through (12, many sentences opening on So, And, But), or an essay (18). Pick one and
  hold it for the whole script. A presenter who made the thing says "I": note who they are in
  `presenter_is`.

The word budget follows from the length: the brief's seconds, less a five-second end card,
times 2.6 words a second. 360 seconds is about 920 words; 545 is about 1,400. The script must
land within 15% of it; the reading of your material states it. Settle the length in the script: a line
cut after its frame is designed takes its cues with it.

## From a route to chapters

The classifier names the route from the material. Each route has a usual spine:

| Route | Chapters, in order |
| --- | --- |
| What, why, how | Introduction · Concept (what it is) · How it works · a chapter on using it (Options compared, Advice or a Demo) · close |
| Options | Introduction · Worked example (the case) · Options compared, one chapter per option · How it works (how they combine) · Advice (how to choose) · close |
| Problem, fix, proof | Introduction · Problem · Concept (the fix) · How it works · Demo or Feature tour · Advice · close |
| Questions | Introduction · a chain of Concept and Questions chapters · Recap · close |
| Series | Introduction · Series recap or map, one short chapter per episode · the chapters that cut across them · Recap · what comes next |

Rules for the spine:

- **A chapter answers one question**, and each question is raised by the answer before it.
  Write the question first. If you cannot say it in twelve words, it is two chapters.
- **Four to nine chapters** for four to ten minutes, and up to twelve when a series adds one
  short chapter per episode. A core chapter runs 40 to 140 seconds and four to ten beats. An
  introduction, a recap, an outro or an episode's chapter runs 15 to 50 seconds.
- **An introduction's question is about the video**: "What will you understand by the end?".
  An outro's question is its own landing. The one-question check is for the chapters between.
- **Open on an Introduction or a Demo first, and get to the substance by the third beat.** The
  middle published explainer spends 19 words before its first explaining beat. Half of all the
  videos open with no hook at all; the common openings are a plain promise of what the viewer
  will understand, or the thing working. Do not force a clever hook. Never open on a greeting
  and a name alone.
- **An option's chapter ends on its cost.** That cost is the turn that raises the next option.
- **Close in three beats:** the landing (the idea in one line, often returning to the case or
  to the opening), then the ask, then the goodbye. About 60 words. The landing comes before
  the ask. An Outro can be its own chapter or the last beats of an Advice or Recap chapter.
- **The agenda is a beat, not a chapter**, and only when there are parts worth naming.
- With a series: one short chapter per episode (25 to 120 words), never a list of all of them
  in one breath. Give it `wants: series`. Such a chapter explains something, so its words read
  as a concept or a mechanism; the classifier is asked separately whether it is about another
  episode.

## Beats

A beat is one to three sentences that do one job. The middle beat of an explainer is 24 words
and nine and a half seconds; there are five to seven a minute. Six minutes is about 920 words
and 34 beats.

**Every chapter type has a recipe**: the beats it is usually made of, in order. The recipe is
in `types.md`. Start from it; vary it; do not let one job carry more than half a chapter.

| Chapter type | Its beats, in the usual order |
| --- | --- |
| Introduction | promise (or hook) · definition in one plain line · agenda (if there are parts to name) |
| Demo first | proof first · what you just saw (definition) · promise |
| Concept | the question · definition · worked example or analogy · so-what |
| How it works | signpost · mechanism · worked example · mechanism · so-what |
| Options compared | signpost · definition (name the option) · mechanism · worked example on the case · so-what · the turn (its cost) |
| Worked example | the case set up · the obvious answer · the turn |
| Story | story · first attempt · the turn · story |
| Problem | need · worked example · evidence · the turn |
| Advice | advice, one tip per beat · principle · contrast |
| Questions | the doubt, voiced · the answer (a principle, evidence or a contrast) |
| Recap | recap · landing |
| Outro | landing · ask · sign-off |

**What a six-minute explainer holds**, counted in beats: definition 3 to 4, mechanism 3 to 4,
worked example 3, signpost 2, contrast 2, so-what 2, principle 1 to 2, advice 1 to 2, a
question 1 to 2, promise 1, a turn 1, recap 1, ask 1, sign-off 1, and one or none of: agenda,
analogy, first attempt, objection, evidence, milestone, bridge, landing (always one).

**The share of words by job**, in the six concept explainers as the classifier reads them:
explain 53% in the middle case (34 to 72), turn 15% (7 to 21), close 10%, open 7%, guide 6%,
prove 4%. Explaining is the body of the video. The core chapters are mostly mechanism and the
worked example, and that is where the words go.

**Density:**

- A beat that turns (a question, a problem, a so-what, a rule) about once a minute in the
  middle case, and never two and a half minutes without one. An explainer with no turns is a
  lecture. But a turn is short, 20 words in the middle case, and it is not a habit: do not
  close every chapter on a so-what and a turn, and do not answer a doubt nobody has.
- A beat that says where we are (a signpost, a bridge, a milestone) about every minute and a
  half.
- The case, an analogy or a demo at least every three minutes.

**Moves that recur in the published scripts:**

- Describe first, name after: "...and that sequence of actions is the trajectory." A new term
  is glossed in the sentence that introduces it.
- Announce the count before a list: "three ways", "two questions".
- A chapter opens on a signpost plus its question, and closes on a milestone or a bridge:
  "that tells us what to check; next, how."
- Define, then show on the case, then explain the mechanism. Not three definitions in a row.
- The recap repeats the agenda's steps in the same words.

**Write for the ear.** One idea a sentence. Figures spelled out in `says`; the digits go on
screen. No "according to". No sentence that only works when read.

## Fields you write on a beat

- `wants`: the job you mean it to do, as a subtype id (`definition`, `so-what`).
- `says`: the narration, exactly as spoken.
- `uses`: the material ids the beat rests on. Empty for a frame or turn beat.
- `made_up`: `true` on every beat of the invented case and on every analogy.

## What the classifier needs to hear

It reads each passage cold, with one sentence either side. The opening words decide most.

- A definition names the thing: "An agent team is the work carved up..." reads as a
  definition; the same content starting from a detail reads as a mechanism.
- A so-what starts from what was just explained: "So that's the gain: ..." or "This means
  ...". Restate anything concrete and it reads as explaining.
- A turn is short and breaks something: "But apps grow."
- A recap says it is one: "To recap", "So, three things". Without that it reads as the
  mechanism or the agenda it repeats.
- An ask requests an action. "Try it on your own model" reads as advice; "subscribe, and tell
  me what you built" reads as an ask.
- A landing is one line that returns to the opening or to the case, just before the ask.
- Rules said as commands read as advice; said as statements they read as principles.

## When the classifier reads a different job

It reads the words cold, like a viewer. Three cases:

1. It is sure and differs from `wants`. The words do another job than you meant. Rewrite them
   so the job is plain: a so-what starts from the thing just explained and says what it buys;
   a turn is short and breaks something; a signpost carries no content.
2. It is unsure and your `wants` is among its top three. Your intent stands, flagged. A
   plainer line would settle it.
3. Its reading is better than your intent. Accept it, and check the chapter's recipe again.

Two readers working apart agreed on the subtype for 85% of the words of the same transcripts,
so one disagreement in six is normal and is not a reason to bend a good line.
