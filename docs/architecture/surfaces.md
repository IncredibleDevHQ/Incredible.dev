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
sixteen kinds, from a storyboard to a film study) with its sources, its review board and its
finished files. People add an asset made from another, or place a template (slots wired together,
some signed off before anything is made from them); the bridge tells the lead each asset's id, kind,
brief and sources in the turn's input, and the lead files its work under them with the canvas
tools. A board or `upload_files` delivery that names no asset is filed under the one under way it
fits (none when two fit equally), or becomes a new asset. Approving a board signs its asset off,
and the line that reaches the lead names what that lets it start on.

An episode's brief and its plan are boards of kind `brief` and `plan`: their frames are sections
in words (JSON files), reviewed row by row, with a note or a refine on any one row.
`design_agent.episode` reads them. It refuses a section that does not pass, puts a chapter's shots
only under beats the board already holds, marks the shots of a beat whose words changed as stale,
and works out the clock, the word counts and the checks every time a board is read, so no number
on it was written by the model. When a brief is published, the host reads the material its
`source` row names and marks each quote in the ledger found or not. The brief is signed off
first, and its asset gates the plan's. The plan is then signed off in two layers: the top layer,
which has the chapters written, then the whole plan once every chapter has shots written from
its beats as they stand. The review reads a plan as a deck (`PlanReview.tsx`, `PlanFilm.tsx`,
`PlanTimeline.tsx`): the episode is the cover, each chapter is one slide with its timeline inside
it, the slides run down a filmstrip, and the part picked on a slide is shown in full under it.
The timeline is drawn from the numbers the host works out: where each beat and shot starts, how
long its line takes to say and its words to read. The checks carry what each is about (`group`:
time, structure or words), and the review shows them in those parts; the chapter the film turns
on is marked on its thumbnail and on the episode's strip.

## Trace tags

Each run is tagged with its trigger, surface (the runtime profile's `surface`, such as `cli` or
`web`) and the kinds of files delivered, and names the template and version it came from
(`DESIGN_AGENT_TEMPLATE_TELEMETRY=0` turns that off); no user ids.

## The API and the CLI

The API returns each turn's reply and delivered files, and background news through
`GET /threads/{id}/updates` ([self-hosting](../self-hosting.md)). The CLI prints each step's tool
name as it runs and stays open while background work continues.
