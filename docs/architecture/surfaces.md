# Surfaces: the presenter hook, the API and the CLI

Every surface reaches the same agent. What differs is presentation: a channel UI shows the agent's
work as it goes and carries follow-ups into the running job; the API and the CLI run headless.

## The presenter hook

Code: `src/design_agent/surfaces/presenter.py`, `RuntimeProfile.presenter`
(`src/design_agent/runtime/profiles.py`) and `build_local_runtime(presenter=...)`.

A `Presenter` hands the assembly the middleware that shows a thread's work where its people are:

- `lead_middleware(settings=..., services=...)` lands right after the run tags and before
  background work, outside the model guards: steering reads follow-ups before progress draws the
  turn, so a retried call shows as one step and a boundary's line counts as the reply.
- `helper_middleware(settings=...)` lands in every helper after its stagger gate, just inside the
  model guards, so each helper's steps can show in their own lane.

With no presenter, runs are headless. `DESIGN_AGENT_ENABLE_PROGRESS`, `DESIGN_AGENT_ENABLE_FOOTER`
and `DESIGN_AGENT_ENABLE_STEERING` are the switches a presenter reads. Step names come from the
phrasebook (`src/design_agent/surfaces/phrasebook.py`): a studio phrase per tool call, in both
tenses, never argument text.

Follow-ups to running background helpers need no presenter: on a person's turn while helpers run,
the lead sees what is running and can pass the note on with `steer_task`; the helper reads it
before its next model call.

## The web app's canvas

Code: `src/design_agent/surfaces/web/` (`catalog.py`, `agent.py`, `presenter.py`).

A task's work on the canvas is a set of assets, each one capability's piece of work (the catalog's
fourteen kinds, from a storyboard to a film study) with its sources, its review board and its
finished files. People add an asset made from another, or place a template (slots wired together,
some signed off before anything is made from them); the bridge tells the lead each asset's id, kind,
brief and sources in the turn's input, and the lead files its work under them with the canvas
tools. A board or `upload_files` delivery that names no asset is filed under the one under way it
fits (none when two fit equally), or becomes a new asset. Approving a board signs its asset off,
and the line that reaches the lead names what that lets it start on.

## The web app's episodes

Code: `src/design_agent/episode/` (the plan as code handles it), `surfaces/web/episode_desk.py`,
`episode_workers.py` and `computer.py`; the writer's instructions are the `episode` skill.

An episode is an asset made in a studio of its own rather than by asking the lead for it. Three
hands make its plan and none writes in another's: the writer (an agent) writes `plan.json`, a
typed classifier reads the words and gives every label, and code derives every number. The desk
runs the loop: a stage's turn, then the reading and the checks on the host, then the next turn
opening with that report. That keeps the two kinds of writer the same shape:

- a local one (`LocalWorker`): the person's own Claude Code, Codex or Kimi Code, run by
  `research.run` with `writes`, in `workspace/house/episodes/<id>/` and nowhere else, with none
  of the house's keys;
- the built-in one (`BuiltinWorker`): a turn on the episode's thread (`AgentHost.told`), in
  `/workspace/projects/<id>/` on that thread's computer.

Either way the run is a row in the store's `runs` table (prompt, steps, answer, session), as a
research run is. A local agent's session is resumed when it can be; when it cannot, or another
agent takes the lane, the turn opens with what was said, from those rows.

A picture is built in a lane of its own (`picture:<unit>`), by the agent a person picked for
that picture (`picks.units[<unit>].builder`), else its chapter's
(`picks.chapters[<chapter>].builder`), else the film's writer (`settings.writer`, which a person
can change for a plan that stands); each agent has its own gate on how many it builds at once. A picture has a row once it is asked for (`make`, or all of them on
`approve`), and only a row that says `queued` is built: nothing is drawn by itself. A pick (or a
change) that alters what a made picture is drawn from, or its level, leaves the row as it is
and the view calls it out of date; `apply` asks again for every such row (and, once the plan is
approved, for pictures with no row). What a pick leaves the writer is kept in `picks.writer`
until `apply` turns it into a `redo` turn, after which the pictures follow. A rich picture
takes two turns before it is posed: a `motion plan` turn that writes
`pictures/<id>.motion.json`, which `picture.motion_plan` holds to its shape and the row keeps,
then the `picture` turn, whose brief carries that plan.

A plan that stands is changed by one of two turns, and the studio stays open through each.
What a person's own changes leave the writer waits in `picks.writer` until `apply`, which makes
it one `redo`: a pick that needs a picture, a line they added with a picture of a type they
picked, a step of a picture whose word their words took away. A change a person asks for in
words is a `change` (a note on a picture is first read by the classifier: how it is drawn goes
to its builder, what it shows to the writer). A person's own words for a line (`edit`), a line
they add (`add_line`: going on in its block, said to camera, or with a picture) and lines they
cut or join (`cut_lines`) are code's alone: a new line is labelled as the person chose it (its
beat does what the beat before it does), the line after it is told how it now follows
(`classify.follows`), and the writer is told nothing until the person applies. The house's copy of the plan is the plan: it is
written into the writer's folder before every turn, so a person's words reach the writer. The
plan, its labels and its pictures as they stood are kept in `history`, a row per change: while
a change stands its row holds the episode as it stood before, and once the change is taken
back the row holds the episode as the change left it, so it can be put back. A turn that
fails or is stopped falls back to its own row and drops it; a turn that leaves the plan and
the picks as they were keeps none. Going either way keeps the picks a person made since
(`plan.picks_kept`), re-settles the frames under them, and keeps a picture made since that
still fits its lines. A row's summary names the lines whose words changed with what they
said, the lines that were cut with the line each followed, and the pictures planned again;
the studio lays that into the script.

What no model does runs through `Computer`, the thread's sandbox for the desk's own use: staging
the channel's brand pack as an engine run would, checking and posing a picture (`hyperframes
check`, then a still at the end of each line), cutting a take to the film's format (the recording
is copied across as a file, `put_stream`, since a camera's own runs to gigabytes), rendering
the film. A picture sits in the project's `compositions/` folder, which is where the renderer's
checks read sub-compositions from. The film's page is
written by `episode.film` from the plan, the person's picks, the takes and the built pictures;
`episode.timeline` is its clock.

## Trace tags

Each run is tagged with its trigger, surface (the runtime profile's `surface`, such as `cli` or
`web`) and the kinds of files delivered, and names the template and version it came from
(`DESIGN_AGENT_TEMPLATE_TELEMETRY=0` turns that off); no user ids.

## The API and the CLI

The API returns each turn's reply and delivered files, and background news through
`GET /threads/{id}/updates` ([self-hosting](../self-hosting.md)). The CLI prints each step's tool
name as it runs and stays open while background work continues.
