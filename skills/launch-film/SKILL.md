---
name: launch-film
description: Direct and produce a 30 s to 3 min launch film, teaser or recreation with helpers, from brief and storyboard approval through parallel acts, reviews, the final render and cut-downs.
---

# Launch film

You are the director and the producer. You own the idea, the plan and the contract; the reviews;
and what the person sees and when. Helpers own the acts, and a helper with the critic brief judges
them. The picture is a HyperFrames composition directed with `motion-direction`; the sound is made
with `sound`; the storyboard follows `storyboard`. This skill is how a big film gets made by a team,
in phases the person can see, approve and steer. A piece under about 30 s that nobody asked to
storyboard goes straight to `motion-direction`.

Helpers are one worker at three efforts (`low`, `xhigh`, `max`), plus `high`, a general helper for
research and ordinary work; the role is the brief you send ([briefs/README.md](briefs/README.md)). How to run them, with the failure
each rule prevents: [orchestration.md](orchestration.md). The board: [references/storyboard.md](references/storyboard.md).

## Two ways to run production

| | `run_pipeline` with `launch_film` | By hand (`start_task` per job) |
| --- | --- | --- |
| Use when | The approvals in sections 1-4 are done: BRIEF.md, the approved board and animatic, a frozen `timeline.js` | The concept and board phases; a short film; a recreation's breakdown; anything that does not fit the pipeline's shape |
| What it runs | Plan (`max`) → lead act (`max`) → the other acts built in parallel (`xhigh` or `max`, at most `builders_at_once`, default 3), every act reviewed (`xhigh`) as it lands and given one fix pass (`xhigh`) if its review does not pass → assembly (`xhigh`) → final review (`max`) → asks "Render the final?" → final render (`low`) | Whatever you launch |
| What you do | Start it: `run_pipeline("launch_film", '{"project": "<slug>", "notes": "<anything the planner should know>"}')`, say what runs and when, end your turn. Relay step reports at check-ins. When it asks "Render the final?", upload the integration preview, give the person the review's verdict in a line, and wait for their answer: the approval is theirs. Then `answer_pipeline(run_id, "approve")` or `"changes: <the person's words>"`; changes run a revision pass, assembly and the final review again | Everything in sections 5-8 |
| When a step fails | It is re-issued once under the resume preamble. An act that fails twice stops the run once the others finish: `resume_task` with the run id continues it (finished steps replay), or split the act and resume | Section 10 |

Either way, delivery is yours: helpers never upload (section 8, step 2).

## 0. Size the job, then say the plan

Your first reply is the plan, sent with the first phase already running: write the brief, start the
concept and board work in the background (`start_task`), then reply with the plan and when the board
will arrive. A reply that promises a next step nothing has started is a stall. Starting estimates
(re-measure them; `PLAN.md` keeps the actuals):

| Piece | Phases | Work time (estimate) | Approvals |
| --- | --- | --- | --- |
| Sting, loop, logo reveal (≤ 10 s) | build, final | 20-30 min | none |
| Reel or teaser (15-30 s) | concept, build, final | 35-60 min | none unless they ask for a board |
| Feature film (30-60 s) | brief and concept 15 · board 20 · animatic 25 · production 60-90 · final 30 | 2.5-3.5 h | board, animatic |
| Launch film (60-120 s) | brief and concept 30 · board 30 · animatic 30-45 · contract 45 · production 90-150 · integration 30 · final 30-60 | 4-6 h | board, animatic |
| Recreation of a reference (per 90 s) | breakdown 35 · contract and lead act 60-90 · acts 90-120 · integration 30 · final 30-60 | 4-6 h | the shot list, if they want it |

> Plan for the 60 s launch film: about 4.5 h of work in five phases, and two approvals from you.
> 1. Brief and concept (~20 min). I'll pick the strongest of three directions.
> 2. Storyboard (~30 min). You approve the frames, copy and music direction.
> 3. Animatic (~35 min). You approve the timing on the music; timing locks after this.
> 4. Production (~2 h). The acts are built in parallel and each is reviewed as it lands.
> 5. Final and cut-downs (~45 min): 16:9 master, 9:16, a 15 s teaser.
> The concept and board are already in progress; the board lands here in about 50 min.

**Turns.** A turn runs from a message to your reply; nothing reaches the thread mid-turn except
files you upload. Keep turns short: start background work, say what runs and when, end the turn.
Helpers wake you when they finish, fail or are interrupted. On long work, check in every 10-15
minutes with `schedule_wakeup`, relaying the helpers' progress notes; reply `[quiet]` when nothing
changed. Each phase ends a turn on an artifact and a question. When the person pre-authorizes
("storyboard it and build it"), chain phases, then stop on the latest artifact with the plan for the
rest.

**Rules.** Keep phases, ETAs, decisions and the current step in `write_todos` and `PLAN.md`, and the
status in `run.json` (`status`, `phase`, `step`, `eta`, `started_at`, `finished_at`), which
`get_render_status` reads. End every phase on something the person can react to, with a one-line
provenance note and the next ETA. Re-estimate out loud once a phase passes 1.25× its estimate, with
the reason. Mention cost when they ask for more than one film or more than 3 minutes of picture; a
deployment may set a job budget, and you will be told when it is reached.

## 1. The brief (5-10 min)

Write `BRIEF.md` from the thread and attachments (`content-brief`): audience and where it plays
first; the one message; the proof; the final frame (the logo and one line, or the next step); length
and formats (the 16:9 master and the cut-downs); voice (a voiceover script, on-screen copy only, or
none; a film with voiceover is cut to the voiceover); music (a supplied track, `generate_music`, or
cues on the grid); the deadline; and the claims ledger. Ask at most two questions, only ones that
would change the film; if no answer comes, ship your recommendation and say which you chose.

## 2. Concept (15-30 min)

Three concepts for a long launch film, one for anything smaller. Delegate a big one with
[briefs/concept.md](briefs/concept.md) at `max`. Each has a title and its sentence, the motif that
resolves on the last frame, the arc in acts with times, the hook, the turn, the proof, the sound idea,
the films whose shape it borrows (only ones the person supplied or that `reference-study` measured),
and what it will not do. Pass the concept gate (`motion-direction`, directing) before you board.
Pick the concept yourself and name why in one line; offer the runner-up only when the choice is
genuinely theirs (tone, risk). When seeing the options would help, render them (`start_looks`).

## 3. Storyboard, then approval (20-40 min)

Follow `storyboard` and [references/storyboard.md](references/storyboard.md): poses from real HTML at
the target size, tied to the grid; look plates from `image-generation` where the concept is a look;
an editable copy on the Paper canvas when it is connected (the Paper skill, `paper-design`). Have a
critic ([briefs/critic.md](briefs/critic.md), `xhigh`) check the board against the brief before you
send it. Send the contact sheet, the shot list with verbatim copy, the music plan, and one line on
what locks once they approve. Wait for approval: a note now costs a minute, after production an hour.

## 4. Animatic, then approval (20-45 min)

Turn the approved board into `timeline.js` v1. Voiceover-led: generate or transcribe the voice and
key every copy change to its word. Music-led: map the track's beats (`analyze-audio.mjs --js`), or
pick a tempo and compose on whole bars. Then a temp score (`sound`) and a skeleton `index.html` with
the board's poses as held frames or rough moves on the grid. Render a draft at 30 fps with sound
(`start_render_job`), run the critic's animatic gate, then send it. **Timing locks on approval**; say
so, because a change after this re-plans the production.

## 5. The contract and the lead act

Decomposition rules (the failures behind them are in [orchestration.md](orchestration.md)):

- **Acts of 8-20 s, split at hard cuts.** A continuous transition belongs to one act; one builder owns
  both sides of it.
- **The system-defining act first.** The shared rig (the recurring camera, the hero card, the glass
  look, the diagram the film returns to) is proven inside one finished act, at `max`, before anyone
  else uses it. The lead also writes `API.md`: the shared exports with one-line signatures, from the
  real files (`grep -n "^export" rig/*.js timeline.js`), and the exact line every act uses to load
  them.
- **Freeze before fan-out**: `timeline.js`, `STYLE.md` (palette as tokens, faces, light policy, motion
  rules, the sound palette, waivers with reasons), the shared rig, and the cross-act tables (which
  moves blur, post effects). Nobody edits a frozen file while acts build; a change waits and goes out
  as a change notice ([briefs/resume.md](briefs/resume.md)).
- **One entry per act.** Each act is `acts/act-<N>.html`, a sub-composition that renders alone
  (`hyperframes render --composition acts/act-<N>.html`) and inside `index.html`.

## 6. Production

| Act | `effort` (always the act-builder brief) |
| --- | --- |
| 3D, camera fits, organic motion, shot-for-shot fidelity, the hero act, the lead | `max` |
| Type, UI, dashboards, diagrams, a re-layout, a polish pass | `xhigh` |

At most three builders at once on an 8 vCPU sandbox; builders render snapshots and short drafts with
`--workers 2`, and full-quality renders go to one `low` helper ([briefs/helper.md](briefs/helper.md))
behind the render lock. By hand: one `start_task` per act with the same `wave`, all in one message;
say what runs and when the first cut lands, and end your turn. Each brief gives a stop time in minutes
from its start, and builders check `date` at each render.

As acts land, and after the last one:

1. **Review each act as it lands**: a critic at `xhigh` writes `review/REVIEW-act<N>.md`.
2. **Merge the builders' `analysis/requests/*`** into the shared rig once nobody who reads it is still
   building, with a change notice for each. Chain each guarded edit to its check and render with `&&`
   (or `set -e`), so a failed check stops the render instead of rendering the unmerged rig.
3. **Update** `write_todos`, `PLAN.md` and `run.json`.
4. **One polish pass** on the critic's must-fix list, under the resume preamble.

**A failed task** returns nothing useful: re-issue the same brief under the resume preamble
([briefs/resume.md](briefs/resume.md)), or `resume_task` when a restart interrupted it. Two failures on
one act: split it at its next hard cut and give each half to a fresh builder.

## 7. Integration and review (20-40 min)

A `low` helper renders the whole film as a draft at 30 fps (the helper brief); a film of 15 s or less
can render in your own turn with `start_render_job`. Then check: frames at every act boundary (t−1,
t, t+1); the per-second motion curve against the animatic (`film-breakdown/scripts/compare.mjs`);
`video-score.mjs` on `index.html`, reading each finding against the holds `AUDIT` declares;
`video-gate`, `brand-lint` and `hyperframes check`, with any waivers listed; loudness (`audio-lint`).
Then the critic's integration gate (`xhigh`; `max` for a launch film's final review). Fix what it
blocks; do not re-litigate what the person approved.

## 8. Final, delivery, variations

1. **Render.** A `low` helper renders the final behind the render lock (`--quality delivery`, at the
   rate `timeline.js` declares; 30 fps for long films unless the brief asks for 60). Every render runs
   inside something that waits for it: a helper's turn, or your `start_render_job`, which wakes you
   when it exits. Budget from a measured act render. **The audit**: `video-score` passes, and every
   finding left is inside a hold `AUDIT` declares with its reason (an end card, a copy read); name
   those holds in the delivery note. Don't re-master by hand: `sound` masters to -14 LUFS and
   `audio-lint` checks it; if it fails, the mix is the problem.
2. **Deliver first.** `upload_files` the master the moment its checks pass, then reply with a one-line
   provenance note ("Final, 16:9, 60 s, with the approved score"). The upload records `DELIVERY.json`,
   so a retry never sends twice. Helpers never upload.
3. **Variations** come from the same `timeline.js` and score, so every cut shares its music: 9:16 and
   1:1 are re-laid out (act-builder brief at `xhigh`), never cropped; cut-downs of 6 s and 15 s; the
   thumbnail through `thumbnails`.

## 9. Talking to the person

At every stop: what is done, what is running (with its ETA), what needs their decision, in three
bullets or fewer. Every artifact gets a provenance line ("Animatic, 30 fps draft, temp score"). Name
the calls they would not expect and the one caveat that matters; never recap what they can see.
Translate the machinery: builders, critics, waves and effort levels are yours; "four acts in
parallel, a reviewer on each" is theirs.

## 10. When something breaks

| Symptom | Do this |
| --- | --- |
| A helper failed, came back partial, or a restart interrupted it | `resume_task` if its transcript was saved; otherwise re-issue the brief under the resume preamble. It restarts from its progress file |
| The pipeline stopped on an act that failed twice | Split the act at its next hard cut (or fix the brief), then `resume_task` with the run id |
| The project folder is gone (the sandbox was recreated) | Rebuild from what survives in the thread: the board, the animatic and finals you uploaded, and your `write_todos` plan. Tell the person what it costs |
| A final render or upload failed | Re-render only what failed; the delivery ledger stops a second send |
| Two blocking critic rounds on the same act | Tell the person what blocks it, with the critic's top note, and ask how to proceed |

## Project layout

```
/workspace/projects/<slug>/
  BRIEF.md  STYLE.md  PLAN.md  API.md  run.json  DELIVERY.json
  storyboard/        board sheets, pose HTML, plates, links
  timeline.js        the frozen grid: FPS, DUR, BPM or VO, CUTS, HITS, act ranges, BOARD, AUDIT
  index.html         the film: mounts every act on its range
  acts/act-<N>.html  one sub-composition per act, renders alone
  rig/               the shared modules and styles the lead act froze
  plan.json          the sound plan (`sound`); generated audio in sound-assets/
  analysis/          progress-act<N>.md, limits-act<N>.md, requests/, done-act<N>.json
  review/            REVIEW-*.md      scratch/act<N>/      build/ (previews)      renders/ (finals)
```

The sample-brand case study is pending: [references/case-studies/README.md](references/case-studies/README.md).
