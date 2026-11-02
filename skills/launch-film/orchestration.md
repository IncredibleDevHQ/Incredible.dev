# Orchestration: running a production with helpers

How a lead and several helpers make one film without stepping on each other. Each rule names the
failure it prevents; these failures are what multi-agent productions run into when the rule is
missing, so read them as defaults to weigh with their reason attached. The `launch_film` pipeline
(`run_pipeline`) encodes the order and the gates in code; everything here applies whether you run it
or orchestrate by hand.

## Effort per job; the brief is the role

Every helper is the same worker, in the background, in this thread's computer (`start_task`). Its
`description` is its whole prompt and its `effort` is the one other thing you choose, so the role is
written into the brief ([briefs/](briefs/README.md)) and the effort is picked per job:

| Job (brief) | `effort` | Typical time (estimate) |
| --- | --- | --- |
| A long film's concept and board draft (`concept.md`) | `max` | 20-30 min |
| The lead: the shared rig and the system-defining act (`act-builder.md`, marked lead) | `max` | 45-90 min |
| A hero act with 3D, camera fits or organic motion; a shot-for-shot act (`act-builder.md`) | `max` | 45-90 min |
| An act of type, UI, dashboards or diagrams; a 9:16 or 1:1 re-layout; a polish pass (`act-builder.md`) | `xhigh` | 30-60 min |
| Breaking down a reference film, a track or a voiceover (`analyst.md`) | `xhigh` | 20-35 min per 90 s |
| A review at a gate, fresh eyes each time (`critic.md`) | `xhigh`; `max` for a launch film's final review | 5-15 min |
| The score, when you don't make it yourself (`sound.md`) | `xhigh` | 15-20 min a pass |
| Frame grabs, conversions, full renders behind the lock, cut-downs (`helper.md`) | `low` | minutes |
| Research, anything else | `high` | |

Whoever runs the deployment can cap every helper's effort (`DESIGN_AGENT_HELPER_EFFORT_CAP`) to
control cost; the capped effort is what runs.

**Why effort goes where it goes.**
- **Quality is made in the builds.** A builder at high effort runs many compare-and-fix rounds on its
  act; that loop is where a film gets good, so it gets the budget.
- **The lead stays at its usual effort.** Most of the lead's turns are short replies and check-ins;
  high effort on every one costs a great deal for nothing.

**Where the cost goes.** Most of a long-running helper's cost is re-reading its own context, and
images grow it fastest. The cheapest quality lever is an image budget, not a lower effort: crop to
the region under test, keep sheets at 1,500 px or less, measure with a script instead of looking
again, and start a fresh builder for each 8-20 s act rather than one builder for the whole film.

## Decomposition

1. **Acts of 8-20 s, split at hard cuts.** No builder then hands a moving state to another. Keep with
   the lead any act whose boundary is a continuous move.
2. **Continuity stays with one author.** If a transition carries an object across a boundary (a card
   squeezing into a grid, a camera push through a card), one act owns the whole transition. If it must
   be split, the brief's boundary table gives the exact state at t−1, t and t+1: the camera, the
   grounds, each shared object's position, size, rotation and colour, anything moving with its
   velocity, and the copy on screen.
3. **Smaller scopes get more attention.** A builder with one short act runs more comparison rounds
   per second of film than a lead spread across half the film; keep the director's own build share
   small.
4. **The system-defining act first.** Build the recurring rig inside one finished act before anyone
   else touches it. Then write `API.md` from the real exports, not from memory, and paste it into
   every brief.

## Contracts: freeze before fan-out

| File | Owner | Rule |
| --- | --- | --- |
| `timeline.js` | director | Frozen at animatic approval: `FPS`, `DUR`, `BPM` and beats or the `VO` word list, `CUTS` as frames, named cuts, `HITS`, act ranges, `BOARD`, `AUDIT`. Builders import times and never type them |
| `STYLE.md` | director | Palette as tokens (plus any declared film colours with their source), faces and weights, light policy (glow, depth), motion rules and the easing family, the sound palette, waivers with reasons |
| `rig/` and `API.md` | the lead, then frozen | Read-only for builders. Nobody edits them while acts build |
| Cross-act tables | director | Which moves blur and how much, post effects, the cut convention |
| `acts/act-<N>.html` and its own `rig/act-<N>-*.js` | one builder each | Covers exactly its range and renders alone |
| `analysis/requests/act<N>-*.md` | builders | Proposed changes to shared files; the director merges them when nobody who reads them is building |
| `analysis/progress-act<N>.md`, `done-act<N>.json` | builders | The heartbeat and resume point, and the done signal with the report |
| `review/REVIEW-*.md` | critic | Verdict, per-shot scores, must-fix items |

Failures this table prevents:
- **The unannounced change.** A shared table that changes after builders start, without a notice,
  gets layered over by one act and logged as a limit by another, and the final carries the defect.
- **Forked helpers.** Without a requests channel and a shared toolkit (`film-breakdown`), the same
  component gets rebuilt in several acts and dozens of near-duplicate measurement scripts appear.
- **No done signal.** Without `done-act<N>.json` and a stop time, the lead polls file times and waits
  for builders to go quiet.

## Waves

- **One `start_task` per act, all sharing a `wave` name, in one message.** They run in parallel; you
  end your turn. Each task wakes you when it lands, fails or is interrupted; set `wake_on_progress`
  only when you must hear every note. The person's messages reach you as new turns while they build.
- **Check-ins.** Between those wake-ups, `schedule_wakeup` keeps the person posted, about every 10-15
  minutes on a long wave.
- **Pipeline, not barrier.** A landed act's critic starts while the others build; an `xhigh` type act
  lands well before a `max` hero act. Merge shared-file requests and render the integration only once
  nobody who reads those files is still building.
- Wave 0 is the lead: the shared rig and the system-defining act. Wave 1 is the parallel acts. Wave 2
  is polish on the critic's notes.
- **At most three builders on one 8 vCPU sandbox.** Each renders snapshots and short drafts with
  `--workers 2`, which leaves room for the director, a critic and ffmpeg. Only a `low` helper with the
  helper brief renders at full quality, one render at a time, behind the lock
  (`flock /workspace/.render.lock <command>`). On a bigger sandbox the pipeline's `builders_at_once`
  can go up.
- **Between waves**: critics review each act as it lands; merge requests and write change notices;
  render the integration as a draft; update `write_todos`, `PLAN.md` and `run.json`; tell the person
  in a line if the phase changed.
- **A helper cannot be messaged while it runs.** Everything it needs is in its brief and the files the
  brief names, so resumability lives on disk: the builder updates its progress file every ~10 minutes,
  and a failed or interrupted task is resumed (`resume_task`) or re-issued under the resume preamble
  ([briefs/resume.md](briefs/resume.md)).

## Review: independent, at every gate

Makers' self-scores go unchecked unless someone else looks: a motion regression or a smear ships when
the only reviewer is the builder. So:
- **A critic reviews every act and every gate** in a fresh context and regenerates its own evidence:
  its own frames at times it picks, strips across transitions, the per-second motion curve against
  the reference or the animatic.
- **Re-run the motion curve after every change to speed or amplitude.** A fix at one second can break
  the next.
- **After two blocking rounds on the same act**, tell the person what blocks it rather than looping.

## Communication cadence

- **Kickoff**: phases, ETAs and approvals (SKILL.md section 0).
- **Every phase boundary**: the artifact, its provenance line, three bullets or fewer, the next ETA.
- **Slippage**: say so at 1.25× the estimate, with the reason.
- **Close**: done, running, and what needs their decision.

## Long jobs on this computer

| Constraint | Consequence |
| --- | --- |
| Helpers have no step budget of their own; each runs until its work is done or its stop time | One act per task. Chunk larger scopes into acts, not into longer tasks |
| Everything you do in your own turn fills your context | Delegate the building; the director plans, reviews, integrates and delivers. Use `look` for images |
| A sandbox command is stopped after about 30 minutes, and an idle sandbox stops after about 10 | Long renders run detached: your `start_render_job`, or a helper's detached render it polls with short commands. No single command runs past ~25 min; a long final renders act by act |
| The person's approval can take hours | Put each phase's outputs in the thread (board, animatic, finals) and keep `PLAN.md` current, so the next turn resumes from what exists |
| A restart ends running helpers | You are woken with a notice; `resume_task` continues one whose transcript was saved, and a pipeline run resumes with its id |
