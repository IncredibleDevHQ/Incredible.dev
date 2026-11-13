---
name: episode-plan
description: Plan a 4-10 minute technical explainer (an episode) in words before any picture, from its brief and the spine to each chapter's beats and the shots written from them.
---

# Episode plan

An episode is one technical explainer led by a voiceover: 4 to 10 minutes, one idea, one spine,
a short open and close with three to eight chapters between them. Its plan is written in words
and signed off before a single frame is posed, because a note on a sentence costs seconds and a
note on a built chapter costs an hour.

An episode is not a channel video: no intro sting, no subscribe card, no presenter on camera, no
recording of someone coding. A piece under four minutes goes to `storyboard` and
`motion-direction`; a launch film goes to `launch-film`.

## The levels

Each level is written from the one above it, by someone who has the level above in front of them.
That order is the point: a shot written beside its beat instead of from it is how a plan ends up
with pictures that do not show what the film says.

| Level | What it is | Written from |
| --- | --- | --- |
| The brief | The one sentence the episode proves, the gap it closes for the viewer, who it is for, its length, and a ledger of what it may state, each claim with the material's own words. Signed off on its own | The material |
| The spine | One thing the viewer follows from the first frame to the last: a worked example carried through every chapter. Picked from three candidates | The brief |
| The chapters | 45 to 100 seconds each: one question, the result it ends on, the shape of its argument. Each result raises the next question. The list also names the turn, the one chapter the film pivots on, and carries the film's first and last spoken line | The spine |
| The beats | One change on screen that lands one point, with the passage the voice says over it: `storyboard`'s beat row, without the three fields its shots carry | The chapter's row and the material |
| The shots | One line of script and picture: its seconds, one move, what it shows, its piece of the beat's passage, the words on screen, the sound | The beat |

The voice is written with the beat, by the one writer of a chapter who has the material open.
Its shots cut that passage into lines and change no word of it.

The review calls a shot a frame: a message that names "frame 2B.1" means shot 2B.1.

## Run it with the pipeline

`episode_plan` writes the plan with helpers, in that order: its steps and what each is handed are
code, and every creative call is the helper's. There is no `BRIEF.md` to write first: the brief
is the pipeline's first stage, and the team signs it off on the canvas.

| Stage | Start it | What runs | When it wakes you |
| --- | --- | --- | --- |
| The brief | `run_pipeline("episode_plan", '{"project": "<slug>", "stage": "brief", "material": ["/workspace/attachments/<file>"]}')` | The brief and its ledger of claims, from the material (`max`) | Publish the two sections as a board of kind `brief` under the brief's asset, say the idea in a line, and wait for its sign-off |
| The top layer | `run_pipeline("episode_plan", '{"project": "<slug>", "stage": "top"}')` | The spine, from the brief as signed off (`max`), then the chapter list, the sound and the look, written from the picked spine (`xhigh`) | Publish the three sections as a board of kind `plan` under the plan's asset, say what the spine is and the first and last line, and wait for the top layer's sign-off |
| The chapters | `run_pipeline("episode_plan", '{"project": "<slug>", "stage": "chapters", "chapters": {"Chapter 1": 55}}')` | The top layer is read back as it stands (`low`). For every chapter named: its beats (`xhigh`), then its shots, written from those beats (`xhigh`). Chapters run side by side. Then a first reader goes through the film as a viewer would (`xhigh`), with how each chapter's beats explain counted for it, and each chapter it sends back, three at most, is written once more with its notes | Publish what it lists on the same board (`replaces`), in the order given: a chapter's beats, then its shots. Say what the reader sent back and what it left |
| Only the shots | `run_pipeline("episode_plan", '{"project": "<slug>", "stage": "shots", "chapters": {"Chapter 1": 55}}')` | For every chapter named: its beats are read back as they stand (`low`) and left alone, then its shots are written from them (`xhigh`) | Publish the shots it lists on the same board (`replaces`) |
| Only the reader | `run_pipeline("episode_plan", '{"project": "<slug>", "stage": "review", "chapters": {"Open": 20, "Chapter 1": 55}}')` | The first reader goes through the chapters named as they stand (`xhigh`), and each one it sends back, three at most, is written once more with its notes | Publish what it lists, if anything, and say what it sent back and each chapter's weakest line |

`material` is the paths of what the episode is made from (the post, the docs, the notes), as the
thread attached them. `chapters` is each chapter's name in the chapter list with its seconds; the
sign-off message gives both, so copy them. `notes` is optional at every stage: anything the
writers should know that the material does not say, or, for a part being written again, what the
person asked for and the row it is on. `"review": false` leaves the first reader out of the
chapters stage: pass it when a person asked for the rewrite, because they are its reader. Start
a stage, say what runs and when it lands, and end your turn.

Each section is checked as it comes back, and a writer whose section does not pass gets it back
once with what is wrong. The result says what is left: `open` (what still does not pass: say it,
never hide it), `bare` (a chapter with beats and no shots: run the shots stage for it), `failed`
(run the chapters stage for it again) and `reader` (what the first reader sent back, each
chapter's weakest line, and what it left for the team). What the checks find by reading the
words (a figure left for the voice to read, one way of explaining on most of a chapter's beats)
is in `open` like the rest, and does not hold a chapter's shots back.

A helper that goes quiet is stopped after a few minutes and its step is given to another, once;
a chapter that still does not come back is in `failed`. The reader's verdict is also a file,
`plan/reader.json`, and a note to you the moment it reports: after a run that was stopped
during the rewrites, read that file, and run the chapters stage for each chapter it sent back
that was not written again, with its lines as `notes` and `"review": false`. A run that fails
or is interrupted continues with `resume_task` and its id.

## The boards

The brief and the plan are two boards, each under its own asset, and each has one frame per
section: a JSON file whose form is in [references/sections.md](references/sections.md). The
canvas works out every number from the sections: the clock, the word counts, whether each line
fits its shot, and whether each quote in the ledger is in the material. So a section carries
lengths in seconds and the words, never a time range or a count.

Shots reach the plan's board only under beats that are already on it. Publish a chapter's beats,
then its shots, under the same frame name; shots with no beats to go under are refused. A beat
whose words change keeps its old shots marked out of date, and the plan cannot be signed off
until they are published again.

## Notes

Read them first, as `canvas` says: each note names the row it is on. Change only what was
asked, publish with `replaces` and `answers`, and say what you left as it was.

| The note is on | Do |
| --- | --- |
| A row of the brief or its ledger | Edit that file yourself (`edit_file`) and publish it again on the brief's board |
| A shot's picture, words on screen or sound, or the wording of a row in the top layer | Edit that file yourself and publish it again |
| What the voice says on a shot | The words are its beat's: change the beat's `says` in the beats file and the shot's `vo` to match, and publish the beats, then the shots |
| A beat, or a chapter as a whole | The chapters stage again for that chapter, with `notes` (the person's words and the row) and `"review": false`. Its beats change first, then its shots are written again from them |
| "Write only the frames of “Chapter 4”, from its beats as they stand" (its beats are on the board, and its shots are missing or out of date) | The shots stage for that chapter: the beats stay as the team left them |
| The spine, the turn, the first or last line, or the shape of the chapter list (a chapter added, dropped or moved, a question changed) | The top stage again with `notes`, then the chapters stage for every chapter whose row changed |
| The idea, the gap, the length or a claim, after the plan is written | The brief first: edit it, publish it, and wait for its sign-off. Then the top stage again with `notes` |
| "Write “Chapter 2” in full now" | The chapters stage for that one chapter, before the rest |
| "Have a reader go through it again" (after edits by hand, or a plan written without one) | The review stage, for every chapter of the plan |

## Sign-off

The work is signed off three times, and each reaches you as a message:

1. "Approved “Brief”. Go ahead with “Plan”." Run the top stage. Before this message, nothing of
   the plan is written.
2. "Approved the top layer of “Plan”. Write its chapters in full: …" names the chapters still to
   write. Run the chapters stage for exactly those. Where it says "Write only the frames of …",
   run the shots stage for those.
3. "Approved “Plan”. Go ahead with “Storyboard”." The storyboard is made from the plan as it
   stands in the project folder: pose one chapter first to set the look, following `storyboard`,
   and take each beat's words, timing and sound from its shots.

## Without the canvas

Without `canvas_` tools, attach the brief's two files with `upload_files`, say the idea in a
line, and ask for its go in the thread before you run the top stage. Do the same with the plan's
top layer before you run the chapters stage.
