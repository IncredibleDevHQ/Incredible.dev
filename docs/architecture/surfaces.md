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

## Trace tags

Each run is tagged with its trigger, surface (the runtime profile's `surface`, such as `cli` or
`web`) and the kinds of files delivered, and names the template and version it came from
(`DESIGN_AGENT_TEMPLATE_TELEMETRY=0` turns that off); no user ids.

## The API and the CLI

The API returns each turn's reply and delivered files, and background news through
`GET /threads/{id}/updates` ([self-hosting](../self-hosting.md)). The CLI prints each step's tool
name as it runs and stays open while background work continues.

## Authenticated private workspaces

The browser entry point dispatches to `surfaces/web/auth.py` when Supabase is configured or
`DESIGN_AGENT_AUTH_REQUIRED=1`. Supabase verifies cookie sessions before the gateway selects a
user-specific web app. The user UUID determines its private Postgres schema and file root;
its runtime, event hub and brand shelf are separate. `store.py` supports the existing SQLite
developer path and the Postgres adapter in `postgres.py`; authenticated apps never use SQLite.
`open_persistence(..., schema=...)` keeps the LangGraph store/checkpoints in that same private
schema. The browser has no database credential or service-role key. See [Supabase](../supabase.md)
for trust boundaries, operational limits, and the distinction from the developer-only identity
switcher.
