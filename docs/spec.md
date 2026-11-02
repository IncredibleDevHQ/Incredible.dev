# Design Agent: product and engineering specification

Status: spec-first. This document is the source of truth until the implementation and its tests
exist; afterwards code and tests win and this document is kept current as the design record.
Precedence when sources disagree: `AGENTS.md` → this spec → `docs/architecture/` → official current
documentation (`docs/sources/official-links.md`) → installed package behavior and live probes →
model memory (never sufficient for a fast-moving API).

## 1. Outcome

Ship an open-source design agent that a team can deploy in an afternoon and use the next morning. In a
Slack thread (or the terminal), anyone can ask for on-brand design work and get finished files back:
ads in every size, social cards, slides and decks, diagrams, charts, thumbnails, storyboards and
motion graphics up to a 1–3 minute launch film with voiceover and music.

The product succeeds when, from a clean clone, a developer can:

- run an offline demo that renders a still and a short HyperFrames film through the real agent graph
  with a scripted model and no API keys;
- configure a model, a brand pack (or the bundled sample brand) and optional media keys;
- deploy to Managed Deep Agents with one command and talk to it in Slack, or self-host it with
  Docker;
- ask for a resize, a restyle, a deck, a chart, a storyboard or a film and receive files that pass
  deterministic brand, layout and render gates;
- watch a multi-hour job progress with a plan, an ETA, live status and check-ins, steer it mid-job,
  survive a deploy or restart, and receive the final once;
- connect Paper and have the agent draft on a shared canvas people can edit;
- swap the brand without touching code.

What makes it worth open-sourcing is not "a video CLI plus a model". It is the harness: the
designer's computer, the orchestration that lets one lead and several helpers work for hours on the
same machine, the context discipline that keeps it fast and cheap, the deterministic gates, and the
taste encoded as skills. The internal reference deployment taught every rule in this spec.

## 2. Positioning and name

- Public name: **Design Agent**. Repository: `design-agent` (target `github.com/langchain-ai/design-agent`).
  Python package `design_agent`, console script `design-agent`, environment prefix `DESIGN_AGENT_`.
- Tagline: "On-brand design and motion from a chat thread. Built on Deep Agents. Deploy with Managed
  Deep Agents. Renders with HyperFrames. Designs with Paper."
- It is the third LangChain go-to-market agent released this way, after the GTM Agent post and the
  open-source Paid Media Agent. Follow the Paid Media Agent's repository shape, documentation voice,
  onboarding, deployment paths, CI and release discipline unless this spec says otherwise.
- Partners: HeyGen (HyperFrames, the video engine) and Paper (the shared canvas). Both integrations
  are first-class, attributed, pinned and tested. See [docs/partners/](partners/).

## 3. Users and core journeys

### 3.1 Developer / operator

1. `git clone … && cd design-agent && uv sync && uv run design-agent demo` — no keys; needs Docker
   (local sandbox) or a LangSmith key (managed sandbox); `doctor` explains what is missing.
2. Configure a model (`provider:model`), optional media keys (OpenAI images, ElevenLabs), and a brand
   pack with the coding-agent onboarding skill or the optional setup console.
3. `uv run design-agent ask "Make a 1080x1350 LinkedIn card announcing our v2 launch"` locally.
4. `uv run mda deploy` (MDA, recommended) or `docker compose up -d --build` (self-host).
5. `uv run design-agent doctor` diagnoses configuration without printing secrets.

### 3.2 Requester (marketer, PM, engineer, founder) in Slack

- Quick ask: message → finished file in minutes → a note → fixed file.
- Big ask (deck, film): message → plan with phases and ETA → storyboard for a yes → live status while
  helpers build → check-ins every 10–15 minutes → first cut → final and cut-downs.
- Mid-job steering: "make the logo bigger" goes into the running work without stopping it.
- Options: "show me three directions" → three looks side by side → pick one → it continues.
- Drop files (logos, screenshots, footage, a reference film) into the thread; the agent uses them.

### 3.3 Brand owner / designer

- Defines the brand once as a brand pack (tokens, logos, fonts, voice, graphic language) — by hand,
  with the brand-onboarding skill, or imported from a Paper file — and reviews it.
- Reviews and edits drafts on the Paper canvas; the agent reads comments and edits back.
- Teaches taste: corrections become observations the agent weighs on the next similar job; studying a
  reference film produces a teardown and proposed skill edits a person approves.

### 3.4 Maintainer

- Adds a skill, a tool, a renderer or a gate once in the shared assembly; both deployment paths get it.
- Updates vendored HyperFrames skills with one script and a reviewed diff.
- Reproduces every release claim with a test, fixture, render, live probe or official source.

## 4. Scope

### 4.1 Included in v0.1

- One shared Deep Agents assembly for MDA, self-hosted API and Slack, CLI and schedules.
- The orchestration harness (§7): lead plus background helpers on one sandbox, wake-ups and
  self-scheduled check-ins, durable helper transcripts and resume, pipelines as code (launch film),
  parallel looks, detached render jobs with watchers, the `look` tool, context and cost controls,
  failure boundaries, steering, live progress and footer, the per-skill learning loop.
- The designer's computer (§8): a reproducible sandbox recipe with Chrome Headless Shell, ffmpeg, the
  pinned HyperFrames CLI, sharp, ECharts, D2, open fonts; workspace staging; bring-your-own licensed
  fonts.
- Media pipelines (§9): stills, multi-size ads, decks, charts and diagrams, thumbnails, storyboards,
  HyperFrames motion, audio (voice, music, effects), image generation, deterministic gates, delivery.
- HyperFrames integration (§10) and Paper integration (§13).
- Taste and judgment as skills (§11): a public design wiki, motion direction, storyboard-first,
  launch-film phases and briefs, critic, reference study, image generation craft, sound.
- Brand system (§12): validated brand-pack schema, a sample brand, onboarding, brand-lint.
- Surfaces (§14): MDA native Slack with live progress and file delivery, self-hosted Slack (Socket
  Mode and signed HTTP), self-hosted API, CLI, LangSmith Studio for development.
- Direct model providers with a tested capability registry; LangSmith Gateway optional.
- Tests (§20): unit, real-graph contracts with a scripted model, render smoke tests, offline behavior
  checks, opt-in live tests, a design eval set, a model matrix.
- Documentation and launch packaging (§21).

### 4.2 Planned for v0.2 (extension points designed now, code later)

- **Routines**: person-owned recurring jobs on MDA runtime schedules with generic sources (RSS/Atom,
  web page, Slack links) and the "a scheduled run never publishes" rule.
- **Publishing plugin**: approval-gated posting with an exactly-once publish ledger, revisions and
  slots (Buffer and others), with code-drawn approval cards.
- **Peer agents**: a configurable registry of other agents the design agent may @mention for facts.
- **Grounding**: read-only Drive/Docs/Notion style context tools.
- **Hosted Paper**: when Paper offers a hosted or token-based MCP.
- **Native MDA async subagents** replacing the custom helper runner once released (§7.4).

### 4.3 Not included

- Any LangChain brand asset, person, channel, account, campaign, analytics workspace, internal agent
  or internal infrastructure identifier.
- Licensed fonts, third-party films, frames, contact sheets or teardowns of other companies' work, the
  internal motion component library ported from a third-party site without a recorded license, or any
  asset with non-commercial terms.
- The internal canvas motion engine (HyperFrames is the single video engine).
- Social posting, the internal quote-post copilot, the launch ledger, managed-tool connectors, public
  asset hosting.
- An LLM "taste judge". Quality comes from deterministic gates, the agent looking at its own renders,
  and human review. (Every model judge tried internally failed or blocked legitimate asks.)
- A custom web frontend beyond the optional local setup console.
- A required model gateway or proxy.

## 5. Architecture

### 5.1 Layers

```text
┌───────────────────────────────────────────────────────────────┐
│ The lead and its helpers      plans, delegates, reports        │  what we build
│ The context                   skills · design wiki · brand ·   │
│                               observations · optional memory   │
│ The designer's computer       one sandbox per thread: renderers│
│                               (HyperFrames, Chromium, sharp,   │
│                               ffmpeg, ECharts, D2), fonts,     │
│                               workspace folders, gates         │
├───────────────────────────────────────────────────────────────┤
│ Managed Deep Agents           Slack, sandboxes, identity,      │  off the shelf
│ (or the self-hosted runtime)  schedules, memory, Context Hub   │
│ Deep Agents                   planning, files, subagents,      │
│                               skills, summarization            │
│ The model                     Claude Opus 5.5 by default       │
└───────────────────────────────────────────────────────────────┘
   Outside the sandbox (host tools and MCP): image generation, voice and
   music, Paper, optional web research. Keys never enter the sandbox.
```

### 5.2 One core, thin adapters

```text
agent.py (MDA)      runtime/self_hosted.py (API, Slack)      runtime/local.py (CLI, demo, tests)
       \                         |                                   /
        build_agent_components(settings, runtime_profile) ── src/design_agent/assembly.py
                                  |
      model · tools · middleware · subagents · skills · interrupt policy · pipelines
                                  |
                          Deep Agents graph
                                  |
   sandbox backend (MDA | LangSmith | Docker | host-dev) · host tools · MCP (Paper, …)
```

`agent.py` stays a small MDA entry exporting one named `agent` built with `define_deep_agent` (or a
per-run factory if a feature needs it). The self-hosted and local entries compile the same components
with `create_deep_agent`. Shared behavior lives under `src/design_agent/`; surface code never enters
domain, tool or policy modules.

```python
@dataclass(frozen=True)
class AgentComponents:
    model: BaseChatModel
    tools: tuple[BaseTool, ...]
    middleware: tuple[AgentMiddleware, ...]
    subagents: tuple[SubAgent, ...]
    interrupt_on: Mapping[str, InterruptOnConfig]
    pipelines: Mapping[str, PipelineSpec]


def build_agent_components(*, settings: Settings, runtime: RuntimeProfile) -> AgentComponents: ...
```

The assembly performs no network calls and holds no process-global mutable state. Per-run objects
(task tools, runtime handles, sandbox handles) are created per run and never cached on a middleware
instance (an internal bug once ran one user's helpers in another user's sandbox this way).

### 5.3 Control plane and data plane

The model is the control plane: concept, layout, copy, motion direction, what to check, how to
explain. Deterministic code is the data plane: rendering, export sizes, font resolution, color and
token checks, layout overflow, timing determinism, audio loudness, file identity, delivery
exactly-once, permissions, cost metering, and every number the agent reports about a job.

### 5.4 Context architecture

- The always-loaded prompt is small and stable: role, delivery and approval contract, delegation
  contract, translation rule, brand source precedence, links to skills. Target ≤ 8k tokens including
  the skill list.
- Skills hold workflows and judgment and load on demand (only name + one-line "when to use" stays
  resident). The internal deployment cut skill descriptions to "when to use" and saw time fall 51% and
  input tokens 59% across 11 real tasks; the skill list had been 47% of the system prompt.
- The brand pack and design wiki are files the agent opens when a job needs them.
- Large tool results and images go to files; the model receives a path and a compact summary.
- The job lives on disk: `BRIEF.md`, `PLAN.md` (phases, ETAs, decisions, current step), `run.json`
  (status for `get_render_status`), frozen contract files (`timeline`, `STYLE.md`, `API.md`), one
  progress file per helper, review files, `DELIVERY.json` (never send twice).

## 6. Model configuration

### 6.1 Direct providers

`DESIGN_AGENT_MODEL` accepts `provider:model` (LangChain init format). `DESIGN_AGENT_MODEL_BASE_URL`
and `DESIGN_AGENT_MODEL_API_KEY_ENV` support compatible endpoints. The LangSmith Gateway is an
optional preset (`langsmith:provider/model`), never required. Anthropic and OpenAI provider packages
are core dependencies (MDA installs core only); others are extras.

Roles, each independently configurable and defaulting to the lead model:

| Role | Setting | Default | Notes |
| --- | --- | --- | --- |
| Lead | `DESIGN_AGENT_MODEL` | `anthropic:claude-opus-5-5` at `high` effort | vision required |
| Helpers | `DESIGN_AGENT_HELPER_MODEL` | lead model; effort per task (`low`, `xhigh`, `max`) | vision required |
| `look` | `DESIGN_AGENT_LOOK_MODEL` | lead model at `low` effort | vision required; ≤ 8 images per call |
| Tool selector | `DESIGN_AGENT_TOOL_SELECTOR_MODEL` | small fast model | only for models without native tool search |
| Learning proposer | `DESIGN_AGENT_LEARNING_MODEL` | lead model at `low` | optional |

### 6.2 Capability registry

A small, tested, exact-id registry (no provider-name substring guessing) records per model: vision
input and image token cost, tool calling, native deferred tool search, effort levels and their names,
context window, max output tokens (and the minimum the harness needs for `xhigh`/`max`), thinking
behavior (preserved thinking constraints on history edits), prompt-cache TTL options, server-side
context editing support, streaming tool calls, required integration package, and middleware
constraints. Unknown models take the portable path; `doctor` explains missing capabilities. Models
without vision are rejected for lead, helper and `look` roles with a clear error.

Deep Agents 0.7.28 ships harness profiles only up to the previous Claude generation; the registry
supplies the Opus 5.5 profile (1M input, 128k output) so the SDK does not cap output at 4k and
summarization does not fall back to a low fixed trigger. Retire the local profile when an installed
release carries it.

### 6.3 Call behavior

Stall ceiling 600 s; SDK retries 0; the harness's retry middleware owns recovery (6 attempts, doubling
backoff, transient classification). A failure that outlasts retries ends the person's turn with one
plain line ("I hit a model error, reply continue to pick up where I left off") and never kills the
run silently. Cache TTL 1 h for the lead, 5 min for helpers (configurable).

## 7. Orchestration harness

This is the core value. Each primitive below states its contract, the MDA implementation on public
APIs, the self-hosted implementation, and its upstream status.

### 7.1 Lead and helpers on one computer

- The lead is a chief of staff: it plans, delegates, reports and stays free to talk.
- Helpers are the same model with a role written into a complete brief (builder, critic, analyst,
  sound designer, helper). There are no specialist agents; the brief is the role and effort is the
  dial.
- Helpers work in the thread's sandbox, in the project folder, so nothing is copied between them.
  Each owns the files its brief assigns and treats everything else as read-only. A brief states the
  role, quality bar, inputs, deliverables, how to check the work, budget, progress file and how to
  resume.
- At most `DESIGN_AGENT_MAX_PARALLEL_BUILDERS` (default 3 on 8 vCPU) render-heavy helpers run at once;
  renders take a lock.

### 7.2 Background tasks

Lead tools: `start_task(description, effort, label, wave?, wake_on_progress?)`, `check_tasks`,
`cancel_task`, `resume_task`, `schedule_wakeup(minutes 1–1440, prompt, reason)`. Helper tool:
`report_progress(note, urgent?)`. A helper's final message and progress notes are all the lead sees.

Contract:

- `start_task` returns immediately with a task id; the lead tells the person what is running and when
  to expect it, then ends its turn. A turn never ends on a promise that nothing has started.
- Progress notes wait for the lead's next turn unless urgent or the lead asked to follow closely.
- The lead is woken (a new turn on the same thread) when a task finishes, fails, stops early or is
  interrupted by a restart, when a watch fails, stalls or finishes, and when a check-in comes due. Each
  notice lists what is still running. Replying `[quiet]` posts nothing.
- A silent crash must surface: restarts produce "interrupted" notices, not silence.

MDA implementation (managed-deepagents 0.9.3): MDA builds one graph per deployment and does not yet
run async subagents that share the lead's sandbox (open upstream work: one graph per async subagent,
background general-purpose subagent, lead-sandbox sharing, subagent posting into the lead's Slack
thread, Slack approvals reaching subagent runs). Therefore v0.1 runs helpers in-process as asyncio
tasks invoking the declared subagent graphs with the lead's sandbox backend, exactly like the internal
reference, behind a `HelperRunner` protocol.

Self-hosted implementation: the same in-process runner inside the API process, with helper records,
transcripts, wake-ups and watches persisted in Postgres.

### 7.3 Durable helpers

A helper's transcript is checkpointed to the store as it works (tool results before each model call,
the reply after it). `resume_task(id)` restarts the worker with a one-line brief that a before-agent
hook swaps for the saved transcript plus a closing note. Saved history is always valid to send back:
viewed images become text stubs naming the file; thinking blocks are dropped (a provider rejects
replayed thinking once earlier history was edited); a tool call cut off by the restart gets a result
saying its effect is unknown; past a byte cap, the oldest steps after the brief are dropped with a
marker. Before this existed, a 90-minute builder could lose most of its work to a deploy.

Upstream status: Deep Agents async subagents run as server runs with checkpoints, but MDA does not
build them yet (§7.2). When MDA ships async subagents that use the lead's sandbox, migrate and delete
the custom runner and transcript store; keep the transcript-stub rules if replay still needs them.

### 7.4 Wake-ups and check-ins (`Waker`)

```python
class Waker(Protocol):
    async def wake(self, target: WakeTarget, message: str, *, dedupe_key: str) -> WakeReceipt: ...
    async def schedule(self, target: WakeTarget, at: datetime, message: str) -> str: ...
    async def cancel(self, schedule_id: str) -> None: ...
```

- Coalescing inbox: multiple events within a short window become one notice; retries at 10 s, 1 min,
  5 min; delivery counts only once the lead's run actually started.
- MDA adapter on public APIs only: one-time runtime schedules (`runtime.schedules.create(at=…,
  prompt=…)`) on the current thread, which post to the originating channel and survive redeploys.
  Respect the per-owner cap (default 20; raise with `MDA_MAX_AGENT_SCHEDULES` when needed) and clean up
  fired or cancelled schedules in the housekeeping sweep. Measure wake latency in Slice 3; if it is
  worse than about one minute, document it and ask upstream for a public "start run on this thread"
  API. Do not import private ingress, loopback or channel modules (the internal reference does; that
  is the main portability debt this spec removes).
- Self-hosted adapter: enqueue a run on the thread in-process (same process as the API), with a
  Postgres-backed timer table for check-ins and a startup sweep.
- Deep Agents 0.7.27 notifications (parent wake-ups when a same-deployment async subagent finishes)
  become the native path once MDA builds async subagent graphs.

### 7.5 Pipelines as code

When a job has a known shape, the pipeline runs it as code and the model makes the creative calls
inside steps. `run_pipeline(name, args_json)`, `answer_pipeline(run_id, answer)`; finished steps
replay from a memo; `resume_task("p-…")` continues a run after a restart; a pipeline can `ask` the
operator a question (the lead relays it). Ship `launch_film`: plan (max) → lead act (max) → each act
(xhigh or max) reviewed by a critic as it lands with one fix pass → assembly → final review → operator
approval → final render. Running a launch film from instructions alone, the internal lead skipped
reviews; control flow belongs in code, judgment in briefs.

### 7.6 Parallel looks

`start_looks(directions…)` copies the project per look (`looks/<id>/`, excluding outputs and
dependencies, linking `node_modules`), one helper per look writes `look.json` (`{id, direction,
summary, stills}`); when all land the lead posts them side by side and the person picks;
`pick_look(id, why)` backs up the project and merges the chosen look (newer wins) and records why as
an observation. Looks happen at the cheap stage (stills, storyboards), never full renders.

### 7.7 Render jobs and watchers

`start_render_job(command, label, kind)` runs detached (`setsid`, log file, exit-code file) and starts a
watcher; `watch_progress(path, kind)` watches an existing job; `stop_watch(id)`. Watchers poll (which
also keeps an idle sandbox alive), parse progress (parsers: `hyperframes`, `ffmpeg`, `json`, `regex`,
default `heartbeat`), and wake the lead on exit, failure or a stall (default 5 min of silence). Records
persist so a restart can resume watching for 24 h.

### 7.8 Looking at images

`look(paths, question)` has a cheap helper call view up to 8 images (each fit to 1280 px) and return a
short answer; only the answer enters the lead's context. A 1080p frame costs about 2,700 tokens and is
re-read from cache on every later turn, so a kept frame over 50 turns costs ~134k cached tokens versus
~15k for the answer. Workers get an image budget and prefer one contact sheet to many frames.

### 7.9 Context and cost controls

- Tool disclosure: provider-native deferred tool search for verified Anthropic and OpenAI models;
  `LLMToolSelectorMiddleware` (bounded) for others. Host tools stay bound; MCP tools are deferred with
  a search header (the tool's name in plain words) at the start of each description so search finds
  them. Selection is not authorization (§16). The internal first call carried 84 tools and ~247k
  characters of schemas (~98k of 108k prompt tokens) before deferral; after deferral the agent briefly
  could not find sound-effect tools until descriptions led with plain names.
- Cache discipline: stable prefix, tools-array breakpoint, date injected into history not the system
  prompt, notices appended once, per-role TTL, prefix-change watch, fan-out stagger.
- Server-side clearing of old tool results for helpers where the provider supports it (off by
  default until measured); image-aware token counting; Deep Agents large-result eviction (default 20k
  tokens) left on.
- Step budget: wrap up just before the recursion limit with a usable message.
- Cost meter: per call, per role, per job, published to the footer and traces. Prices live in
  `config/prices.toml` with a date and source; figures are estimates.
- Optional soft budget `DESIGN_AGENT_JOB_BUDGET_USD`: the lead asks before exceeding it.

### 7.10 Failure boundaries

- Errors never end a run silently: model failure boundary, tool error boundaries for `task` and file
  delivery, delegated-task error boundary.
- History repair: stale `tool_reference` and dangling tool calls are repaired before a model call;
  removing or renaming a tool must not poison existing threads.
- MCP isolation: one server failing to load degrades that server only; the agent and other tools stay.
- Image clamp: detect MIME from bytes and resize oversized inline images before they reach the model.
- Deep Agents state hand-back: custom state keys must not be copied back out of parallel subagents
  without a reducer (use the documented omit-from-schema pattern) — two parallel tasks otherwise end
  the run with an update error.

### 7.11 Steering, progress and footer

- Steering: follow-up messages during a run steer the running work ("I've added your notes to the fix
  pass that's already running"); one run per Slack message; stop/cancel.
- Live progress: one streamed message per job with a task card per step, step names in plain studio
  language (a phrasebook maps tools to present/past-tense phrases), a separate stream per background
  helper.
- Footer: only what changes — agents running, time left, cost, trace link.
- Every piece of Slack UI starts as a mock people react to before it is built (the first internal
  progress message was rejected on sight).

### 7.12 Learning loop

After a job, the lead saves observations for the owning skill (`save_observations`) or has
`learn_from_job` propose up to five from the thread, each with evidence. Before a similar job it reads
them (`read_observations`) and rates the ones that helped or misled (`rate_observation`). Near
duplicates merge; a note whose harm votes lead by two is dropped. Observations are notes the agent
weighs, never rules. Brand rules are forever; model rules last until the next model. Optional, on by
default when a store exists.

### 7.13 Memory (on for MDA)

`memory.py` declares MDA native memory: a team layer for every caller and a personal layer per person,
mounted anywhere in Slack (MDA's default is the person's DM only). Every lesson has one owner (craft →
a skill, a fact → a check, a team rule → the team layer, a person's taste → their own layer); the hot
file is kept a short index by instruction; writes to a person's files must read first; the user layer is private to that person and never quoted into shared threads. Memory is not a
primary value driver for design work; observations (§7.12) carry most of the learning.

## 8. The designer's computer

### 8.1 Recipe

One reproducible recipe, used by MDA's bake (`sandbox/__init__.py` + `sandbox/setup.sh`), the
optional standalone snapshot publisher, the local Docker sandbox and CI:

| Component | Pin | Purpose |
| --- | --- | --- |
| Debian bookworm base with Node 22 LTS (or the range HyperFrames supports) | image digest | runtime |
| ffmpeg / ffprobe | distro version recorded | encode, probe, contact sheets |
| Chrome Headless Shell via `hyperframes browser ensure` into a fixed cache dir | HyperFrames version | the one browser all renderers use |
| `hyperframes` CLI | exact version | video engine |
| `sharp`, `gsap` (installed, not vendored), `echarts` | exact versions, sha256 | stills, motion runtime, charts |
| D2 | exact version, sha256 | diagrams |
| Open fonts (Inter, IBM Plex Mono, Fira Code, plus Geist and Fragment Mono for the sample brand) | sha256 | defaults and sample brand |
| fontconfig with `/workspace/fonts` registered | — | brand fonts at render time |
| python3, ripgrep, jq, woff2 tools | distro | Deep Agents file tools, scripts |

Rules:

- Every download is version-pinned and checksum-verified. No `@latest` at bake time.
- The bake fails unless `hyperframes lint` and a 1-second draft render of the bundled fixture succeed,
  a Chromium screenshot of a fixture page succeeds, and ffprobe confirms the outputs.
- Never bake instructions, skills, brand packs, user data, fonts under license, credentials or `.env`
  values (MDA forwards non-reserved `.env` values to the bake builder; the recipe must not persist
  them).
- Measure the final size. MDA bakes from a `docker_image` base with a fixed small filesystem capacity
  (1 GiB as of 0.9.3), which a Chromium + ffmpeg + Node image can exceed. If it does, ship
  `design-agent sandbox publish --fs-gib N` (LangSmith SDK, as the Paid Media Agent does) and declare
  the published snapshot as the bake base; document both paths.
- Size: default 8 vCPU / 16 GiB for motion (renders take 8–40 s per second of film on CPU); document a
  2–4 vCPU profile for stills-only teams. Sizes pass through `define_sandbox` extra keys (`vcpus`,
  `mem_bytes`, `fs_capacity_bytes`); verify against the installed SDK.
- Egress: default-deny at runtime through `proxy_config.access_control` with an allowlist the operator
  can extend. Bake-time downloads happen before the policy applies. Compositions must not need the
  network at render time (GSAP and fonts are local).

### 8.2 Workspace layout (inside the sandbox)

```text
/workspace/
  attachments/        files people drop in the thread (MDA writes <id>__<name>)
  projects/<slug>/    BRIEF.md, PLAN.md, run.json, sources, compositions, renders, review/, DELIVERY.json
  skills/<name>/      staged copies of skill scripts and assets (MDA mounts /skills read-only from
                      Context Hub, outside the sandbox filesystem, so scripts cannot run in place)
  tools/              gates: brand-lint, video-gate, film-probe, text-fidelity, …
  brand/              the active brand pack (tokens, logos, voice, graphic language)
  fonts/              open fonts plus the operator's licensed fonts
  references/         the user's reference films and teardowns (when provided)
  .renders/           detached render logs and exit files
/memories/            MDA memory layers: agent/ (team), user/ (the person asking)
```

`projects/<slug>/` lives with the thread's sandbox: files survive an idle stop; running processes do
not. Staged copies are refreshed every run, so edits to them die with the run.

### 8.3 Workspace staging

A `WorkspaceStager` middleware stages, on the first model call of a cold sandbox and whenever the
manifest digest changes: skill scripts and assets, `workspace/tools/`, the active brand pack, open and
licensed fonts. It uploads one compressed delta with a sha256 checklist through the public sandbox
file API (`runtime.backend.upload_files` on MDA; the backend API elsewhere), runs a fontconfig refresh,
verifies required font families resolve (`fc-match`), and writes a ready marker. The manifest is
generated by `scripts/build_manifest.py`, never hand-edited. MDA ships project files inside the Agent
Server image (200 MB compressed archive limit); keep vendored skills lean and measure.

### 8.4 Fonts

- Open fonts ship in `fonts/` with `LICENSES.md` and the OFL text, and are baked.
- Licensed fonts are bring-your-own: the operator places files in Git-ignored `private-fonts/` and
  declares them in the brand pack's `fonts.toml` (`family`, `weight`, `style`, `file`, `sha256`,
  `required`). MDA's deploy archive includes Git-ignored project files, so the files reach the Agent
  Server image and the stager uploads them; the self-hosted runtime mounts the folder read-only.
  Never commit them; `check_deploy_tree` fails a deploy whose required fonts are missing or mismatched.
- Renderers read font stacks from the brand pack; no renderer hard-codes a family. A missing font
  never fails loudly in a browser (it silently falls back), so renders that need a brand font check it
  first and the gate fails the job rather than shipping a fallback.

### 8.5 Sandbox backends

| Backend | Runtime | Notes |
| --- | --- | --- |
| MDA managed sandbox | MDA | one sandbox per thread, adopted across deploys, baked from the recipe |
| LangSmith Sandboxes (`LangSmithSandbox`) | self-hosted, local | same recipe via a published snapshot; needs `LANGSMITH_API_KEY` |
| Docker sandbox runner | self-hosted, local | containers from `sandbox/Dockerfile`, one per thread, idle reaping, per-thread volume; only the runner touches the Docker socket; egress policy enforced; default for `demo` when Docker exists |
| Host (development only) | local | runs renderers on the developer's machine; explicit flag; never in production |

Partner sandboxes supported by Deep Agents (Daytona, Modal, Runloop, Vercel) are documented extension
points, not v0.1 targets.

## 9. Media pipelines

### 9.1 Stills and layouts

Every still is one HTML page; every element is a layer the agent can move, restyle or swap. Chromium
renders; `sharp` exports every size; an image-ops script provides Photoshop's image menu in code
(resize, crop, rotate, flip, extend, modulate, tint, greyscale, blur, sharpen, trim, flatten,
composite with blend modes, format and quality, pipelines). Multi-size ads recompose per size rather
than scale. Paged PDFs for decks and one-pagers. Lighter HTML-to-image renderers were tried and
crashed on variable fonts or rendered blank; use a real browser.

### 9.2 Decks

HyperFrames `slideshow` for animated decks; HTML-to-PDF for static decks; batch work shows one sample,
then numbered batches that wait for approval (the internal 54-slide overnight deck pattern).

### 9.3 Charts and diagrams

A JSON spec renders through ECharts (charts, stat cards) or D2 (diagrams) to PNG/SVG with brand-pack
tokens. Code computes every value; the model writes the spec and labels.

### 9.4 Motion

HyperFrames compositions (HTML + paused GSAP timeline + data attributes), storyboard-first:
plan → storyboard (frames from HTML or HyperFrames snapshots, optionally image-generation look plates,
optionally an editable Paper twin) → animatic timed to voiceover or music → production → final →
cut-downs. Timing locks at animatic approval. A storyboard note costs minutes; after production it
costs an hour. Footage-based work (screen recordings, captions, narrated explainers, website tours,
PR-to-video, music-driven edits) uses the corresponding HyperFrames skills.

### 9.5 Audio

Host tools: `generate_voiceover` (ElevenLabs, word timestamps written beside the audio),
`generate_sound_effect`, `generate_music` (paid ElevenLabs plans), `transcribe_audio` (local
`hyperframes transcribe` by default, optional Groq). A synthesized cue library covers UI sounds without
keys. A mixer masters to −14 LUFS / −1 dBTP. Films with voiceover are cut to the voiceover, not the
music. Bring-your-own music files are supported; no stock-music provider in v0.1.

### 9.6 Image generation

Host tool `generate_image` (OpenAI direct by default; gateway optional). The model id and parameters
pass through to the provider; do not allowlist sizes, qualities or models in code (validate with the
API). Report whether a transparent cut-out actually has alpha. Anything with the logo or exact copy is
built in HTML on brand, not left to the image model. Background removal via HyperFrames.

### 9.7 Gates (deterministic)

| Gate | Checks |
| --- | --- |
| `brand-lint` | colors against allowed palette and banned list, font tokens and stacks, radius limits, casing rules and copy rules from the brand pack (`--tokens`) |
| `video-gate` | seek-breaking patterns: `Math.random(`, `Date.now(`, `new Date()`, timers, `requestAnimationFrame`, unpaused timelines, time-of-render reads, and similar; warnings for risky patterns |
| `hyperframes lint / validate / inspect` | composition contract, timing, layout overflow |
| `film-probe` / `film-analysis` / `video-score` | blank frames, cuts carrying nothing, shots that never develop, silent crops, still-frame share |
| `text-fidelity` | rendered text equals requested copy |
| `artifact-contract` | outputs exist, dimensions, durations, formats, sizes |
| `audio-lint` | loudness, clipping, duration match |

Exit code 2 means a probe could not run (a tooling failure, reported as such), never a pass.

### 9.8 Delivery

Nothing is auto-delivered. On MDA, the agent sends finals with the Slack file upload API exposed by the
SDK (`upload_files(paths)`, 1–10 files, ≤ 200 MiB each; formerly `attach_file`), deliver first then
reply, and never claim something is attached unless the upload succeeded this turn. `DELIVERY.json`
prevents a retry from sending twice. After two blocking correction rounds on the same artifact in a
phase, stop and report it blocked. The self-hosted Slack adapter implements file upload
(`files.getUploadURLExternal` + `completeUploadExternal`); the API serves artifacts to the thread
owner; the CLI writes to `workspace/out/` and prints paths.

## 10. HyperFrames integration

See [HyperFrames](partners/hyperframes.md). Summary:

- HyperFrames is the only video engine in v0.1; the CLI is pinned; the upstream agent skills are
  vendored unmodified at a pinned commit with per-file checksums, LICENSE and NOTICE.
- MDA discovers skills only at `skills/<name>/SKILL.md` (one level), so vendored skills live at the
  top level under their upstream names (`skills/hyperframes`, `skills/hyperframes-cli`, …) and
  `skills-lock.json` marks them vendored; CI fails if a vendored file differs from the lock.
- Local routing, brand and provider guidance live in our own skills beside them, never as edits to
  vendored files. Provider calls (TTS, audio) route through host tools; the sandbox holds no keys.
- `video-gate`, render watchers with a HyperFrames parser, and render smoke tests are part of CI.
- Attribution in README and NOTICE; an `ADOPTERS.md` entry upstream once public and agreed.

## 11. Taste and judgment (runtime skills)

### 11.1 Skill set for v0.1

| Skill | Purpose |
| --- | --- |
| `media-production` | router: which pipeline, storyboard-to-render process, delivery contract, Paper routing |
| `content-brief` | intake for vague asks; at most two questions with reasons, otherwise decide and say so |
| `brand-design` | concept gate, ground/accent/type framework, preserving a supplied reference |
| `design-wiki` | public doctrine: hierarchy, typography, color, layout, platform specs, data-viz, diagrams, review rubric |
| `stills` (from the internal ad-creative) | HTML-to-image ads, banners, carousels, paged PDFs |
| `image-ops`, `gif-edit`, `visual-verify` | deterministic pixel work; checking your own renders |
| `data-viz` | charts, diagrams, stat cards |
| `thumbnails` | thumbnail sets and size/legibility gates |
| `image-generation` | prompting craft, look plates, cut-outs, when not to use it |
| `storyboard` | beat sheets, pose frames, contact-sheet sign-off |
| `motion-direction` | directing, craft, techniques, review for HyperFrames (from the internal motion wiki) |
| `launch-film` | phases, sizing tables, decomposition, effort per role, briefs (concept, critic, act-builder, helper, resume, analyst, sound), orchestration, storyboard |
| `film-breakdown` | measure a film: cuts, contact sheets, motion energy, beat grid, audio |
| `reference-study` | study a user-supplied reference frame by frame, write a teardown to `workspace/references/`, propose observations or skill edits for a person to approve |
| `sound` | voice, music, effects, mixing and mastering |
| `paper-design` | working on the Paper canvas (mode-aware) |
| vendored HyperFrames skills | composition authoring, CLI, animation, creative, media, registry, slideshow, website-to-video, PR-to-video, music-to-video, captions, overlays, explainer, general video, Remotion porting |

### 11.2 Principles the skills must encode

- Storyboard first for motion: it grounds the agent and gives people a cheap thing to react to.
- A deck is a sequence of frames; a film is a sequence of frames with something crossing between them.
  A film is an argument with a turn; a frame asks for at most two things at once.
- Fewest words on graphics: each fact once; no sub-line, caption, footer, URL or eyebrow the ask did
  not supply; explanation belongs in the reply.
- Concept first. Never ship generic abstract node/dot/network wallpaper; a weak pass is a reject.
- The agent looks at its own renders and fixes what is off, the same loop it runs on code.
- A clear ask gets finished work, not a proposal: make the concept, layout and copy calls and name
  them in one line. When options help, render them instead of describing them.
- Speak in a teammate's words: never let tool names, file paths, scores or gates reach the person
  unless they ask.

### 11.3 Rules versus observations (the bitter lesson)

The internal video rules grew to ~50,000 lines and ~2,700 prohibitions; a hand-written plugin of
~2,600 lines made better films. Measured on one brief after a model upgrade, the share of frames where
nothing moves was 10% for the model alone, 43% with stock HyperFrames skills, 57% with the full
rulebook and 18% with one small motion skill. So:

- Ship small skills that teach judgment and process; keep the brand as hard rules; express taste as
  observations the agent weighs.
- Every doctrine rule in the public wiki names its evidence: a measurement on a film the project made
  (for example with the sample brand during Slice 9 evals), or a public, linkable source. Rules whose
  only evidence is internal or third-party media are rewritten as proposed guidance or dropped.
- Credit public creators with links when a technique derives from their public work; never reproduce
  their media.
- Keep the still-frame-share and other `film-analysis` metrics as eval signals (§20), not as hard
  gates that fight the model.

## 12. Brand system

### 12.1 Brand pack

```text
workspace/brand/                    (Git-ignored; defaults to examples/brands/example-studio/)
  brand.toml                        name, description, default formats, voice summary, file pointers
  tokens.json                       validated by src/design_agent/brand/schema.py
  tokens.css                        generated from tokens.json (CSS custom properties, neutral --brand-* prefix)
  fonts.toml                        families, weights, files, sha256, required flags, open fallbacks
  logos/                            SVG/PNG marks with usage notes (clear space, minimum size, colorways)
  voice.md                          tone and copy rules
  graphic-language.md               what graphics should mean, construction rules, do/don't examples
  examples/                         optional approved reference outputs (own work only)
```

`tokens.json` keeps the internal schema's shape so gates port cleanly: `design.allowedColors`,
`extendedPalette`, `officialAssetColors`, `bannedColors`, `allowedFontTokens`, `knownOffBrandFonts`,
`fontStacks`, `maxRectRadiusPx`, `creativeTypography`, `diagramConstruction`, `replacementColors`;
`copy.bannedPhrases`, `warnPhrases`, `bannedChars`, `maxHashtags`, `casingRules`. Validate on load and
in `doctor`; a broken pack fails loudly.

### 12.2 Sample brand

`examples/brands/example-studio/`: a fictional brand created for this repository, with an original
SVG logo, a palette, OFL fonts and a short voice guide, licensed CC0 (or Apache-2.0) and checked for
obvious trademark collisions. Every example, fixture, test, gallery output and doc screenshot uses it.

### 12.3 Brand onboarding

A coding-agent skill (`.agents/skills/brand-onboarding/`) builds or updates the pack from what the user
provides: a brand guide PDF, a website, existing files, or a Paper file (via Paper MCP reads of tokens,
palette and type nodes). It asks at most two questions per turn, records sources and dates, never
invents rules, and asks a person to review. The setup console only points at the skill; it does not
edit the brand.

## 13. Paper integration

See [Paper](partners/paper.md). Summary:

- Modes: Local (stdio `paper mcp` or `http://127.0.0.1:29979/mcp`; default for CLI and Studio),
  Bridged (the bundled bearer-authenticated bridge in front of a user's Paper Desktop, reachable over
  a tunnel the user owns; usable from MDA and self-hosted), Hosted worker (documented recipe only),
  Off (boards render in the sandbox and attach to the thread).
- MDA's `define_mcp` supports HTTP and SSE transports only (no stdio), so MDA deployments use Bridged
  mode. The local and self-hosted runtimes use `langchain-mcp-adapters` and may use stdio.
- Host-enforced tool allowlist, scheme refusal, protected brand file, default drafts file, degrade one
  missing tool not the whole MCP layer, export allowed in Local and Bridged modes.
- Verify the MCP tool naming the installed SDK produces (`{server}_{tool}` versus `{server}__{tool}`)
  and make the deferral and scope rules use the real separator.

## 14. Surfaces

### 14.1 MDA native Slack

- `channels/slack.py` with name (≤ 35 chars), description (≤ 139), icon (512×512 PNG ≤ 1 MB),
  background color, trigger behavior and bot triggers from settings; MDA routes through its Trigger
  Server, posts the final reply, reacts to the starting message, provisions the Slack app, transfers
  inbound files to `/workspace/attachments/`, and renders approval cards for interrupts.
- One Trigger channel per agent; Slack channels forbid `deploy --no-wait`; schedules and channels
  require `identity.py`.
- MDA 0.9.3 offers `runtime.channel.post` (an extra text message) but no streaming or message
  updates. Live progress, status and the footer therefore call the Slack Web API directly with the
  reserved agent connection `mda/slack-bot-token` and the channel/thread ids from `raw_event` (the
  documented pattern). Use Slack's agent streaming and status APIs where available; fall back to one
  updated message.
- Track the 0.10 line: `trigger_mode="mention|thread|all"` replaces `trigger_on_all_messages`, and shell
  environment will take precedence over the project `.env`.

### 14.2 Self-hosted Slack and API

- Slack via Bolt: Socket Mode (no public URL) or signed HTTP; streaming progress; file upload; the
  same steering, dedupe and authorization rules as MDA. Manifest in `config/slack-manifest.example.yaml`.
- FastAPI: `POST /threads/{id}/messages`, artifact downloads for the thread owner, health, bearer
  tokens mapped to callers, per-caller thread ownership. Not the LangGraph Agent Server protocol.

### 14.3 CLI

`design-agent setup | doctor [--sandbox] | demo | ask "<request>" [--file …] | brand
(validate|show|init) | fonts verify | sandbox (publish|use|test) | skills (verify|sync-vendor) | serve
| slack | config (show|set|generate) | test (model|sandbox|paper|slack|db|all)`, with `--json` where
useful. The project deploys and runs with MDA's own `mda deploy` and `mda dev`.

### 14.4 Studio

`uv run mda dev .` opens the managed runtime in LangSmith Studio for development: model calls, tool
results, interrupts, helper runs.

## 15. Runtime profiles, persistence and deployment

| Profile | Graph | Persistence | Sandbox | Slack | Schedules |
| --- | --- | --- | --- | --- | --- |
| Local | `create_deep_agent` | in-memory checkpointer; local store file | Docker runner (default), LangSmith, or host-dev | none (CLI) | none |
| MDA | `define_deep_agent` | managed threads, checkpoints, store, Context Hub | managed, baked from recipe | native channel + direct Web API for progress | `schedules/*.py` + runtime schedules |
| Self-hosted | `create_deep_agent` behind FastAPI | Postgres checkpointer and repositories | Docker runner or LangSmith | Bolt adapter | your scheduler calls the CLI; housekeeping runs in-process |

Parity contract: for the same model, brand, skills, thread state and request, every profile exposes the
same capabilities and produces the same files. Presentation and timing may differ.

### 15.1 Managed Deep Agents (recommended)

- Requires a LangSmith organization with MDA access, an API key with deployment permission, and a
  model key. Regions: GCP US (default), GCP EU, GCP APAC, AWS US via `LANGSMITH_ENDPOINT`.
- Project layout follows MDA conventions: root `agent.py` (named `agent` export), `instructions.md`,
  `identity.py`, `channels/slack.py`, `schedules/housekeeping.py`, `sandbox/__init__.py` +
  `sandbox/setup.sh`, `memory.py`, optional `tools/mcp.py`, `skills/<name>/SKILL.md`,
  `[tool.mda] python-version` in `pyproject.toml`. Do not author `langgraph.json`.
- `uv run mda deploy` on the project as it is, after `doctor` (brand pack, fonts, manifest, `.env`
  review — MDA forwards every non-reserved `.env` key as a deployment secret and archives ordinary
  project files even if Git-ignored), then the Slack authorization hand-off and a smoke message.
- One-click from GitHub: MDA has a hidden `mda prepare` used by LangSmith's GitHub-sourced builds. If
  LangSmith exposes a public "deploy this repository" flow by release, add a README button; otherwise
  the command above is the one-click path. (Open question for the MDA team.)
- `uv run mda delete` removes the deployment, sandboxes, snapshots, crons and Context Hub repos.

### 15.2 Self-hosted

`docker compose up -d --build` starts the API, Postgres and the sandbox runner; `--profile slack`
adds the Bolt worker. The API and Slack worker share Postgres. Back up Postgres and the workspace
volume. MDA's own `--push-to` path targets self-hosted LangSmith, not plain Docker; this profile is the
LangSmith-free path, following the Paid Media Agent.

## 16. Security and safety

- Untrusted inputs: model output, user files, Slack events, Paper canvas content and comments, MCP
  metadata, web pages, reference films and their transcripts. None of them can grant permission,
  change policy, reveal secrets or trigger publishing.
- Secrets: environment or deployment secrets only. Never in prompts, graph state, sandbox files,
  logs, errors, Slack blocks, fixtures, snapshots or tests. Host tools hold keys and drop files in.
- Sandbox: workspace path allowlist; no `.env`, host home, Docker socket, SSH agent or cloud metadata;
  default-deny egress at runtime; sanitized archive extraction, paths, filenames, MIME types, sizes;
  SSRF-hardened asset fetch for user-supplied URLs; artifacts move through host-controlled transfer.
- Tool authorization: selection is not authorization. Before invocation trusted code resolves the
  exact tool, validates arguments against the current schema, applies scope policy (Paper allowlist,
  protected files), and sanitizes errors.
- No outward actions in v0.1 beyond replying in the thread and editing the configured Paper drafts.
  Paper deletes, token writes and AI image generation are off unless the operator enables them.
- Licensing: CI blocks committed font binaries outside `fonts/`, media in `workspace/references/`, and
  banned identifiers; vendored files must match `skills-lock.json`.

## 17. Extraction and scrub process (from the internal reference)

1. Start a fresh repository; never import the internal git history.
2. Port through an allowlist copier (internal-only, deleted before release) that copies only
   allowlisted paths, rewrites names, and writes an import log with source paths and checksums (kept out of the public tree).
3. Re-vendor HyperFrames skills from upstream; do not copy the internal vendored copies.
4. Run the ban-list scan (§18.4), gitleaks over the full history, and a license inventory (every
   third-party file has a license and a NOTICE line, or it is removed).
5. Rewrite all examples, fixtures and docs against the sample brand.
6. Legal and partner review gates (§24) before the repository becomes public.

## 18. Repository, tooling and CI

### 18.1 Layout (target)

```text
agent.py · identity.py · instructions.md · memory.py
channels/slack.py · schedules/housekeeping.py · sandbox/{__init__.py,setup.sh,Dockerfile,README.md}
skills/<name>/                     runtime skills, ours and vendored (one level; see §10)
src/design_agent/
  assembly.py · config.py · cli.py · doctor.py · demo.py · deployment.py
  models/ · harness/ · middleware/ · tools/ · pipelines/ · brand/ · paper_bridge/
  runtime/{profiles.py,mda.py,self_hosted.py,local.py,sandbox/,waker/}
  surfaces/{api/,slack/} · admin/ (optional console) · testing/ (scripted model, fakes, fixtures)
workspace/{tools/,brand/README.md,references/README.md,projects/.gitkeep}
examples/{brands/example-studio/,prompts/,README.md}
fonts/ (OFL) · private-fonts/ (ignored) · config/*.example.* · docs/ · tests/
.agents/skills/{design-agent-onboarding,brand-onboarding,vendor-sync,release-check}/
.github/{workflows/{ci,compatibility,release}.yml,ISSUE_TEMPLATE/,PULL_REQUEST_TEMPLATE.md,dependabot.yml}
README.md · AGENTS.md · CLAUDE.md · OPERATIONS.md · CONTRIBUTING.md · SECURITY.md
CODE_OF_CONDUCT.md · LICENSE (Apache-2.0) · NOTICE.md · CHANGELOG.md · Makefile · pyproject.toml
uv.lock · Dockerfile · docker-compose.yml · .env.example · skills-lock.json · .gitleaks.toml
.pre-commit-config.yaml
```

### 18.2 Toolchain

Python 3.11+ (MDA supports 3.11–3.14), uv, Pydantic v2, Ruff, mypy (strict for new modules; ported
harness modules may start in a documented gradual list that shrinks to zero before v0.1), pytest,
Node only inside the sandbox recipe. One `pyproject.toml`, one lockfile, explicit upper bounds on fast
pre-1.0 packages (`managed-deepagents>=0.9.3,<0.10`, `deepagents>=0.7.28,<0.8` at the time of writing;
never a `.devN` pin in a release).

### 18.3 CI

- `ci.yml` (Python 3.11 and 3.13): lockfile install, Ruff, format, mypy, offline tests, scripted demo
  (render steps skipped without Docker, executed in the render job), MDA definition import smoke,
  `skills verify` (vendored checksums), ban-list scan, docs link check.
- Render job: build `sandbox/Dockerfile`, run the recipe probe and the render smoke tests (§20.2).
- `secrets` job: pinned gitleaks over full history.
- `compatibility.yml` weekly: `uv lock --upgrade`, latest stable MDA and Deep Agents, latest
  HyperFrames CLI and skills in a throwaway lock; run the suite; never auto-merge.
- `release.yml`: tag, changelog, GitHub release (no PyPI publish in v0.1 unless decided).

### 18.4 Ban-list scan

A test fails on any match of: LangChain brand tokens and logo file names, internal people's names,
Slack id patterns outside test fixtures that use clearly synthetic ids, company email addresses, LangSmith
workspace/deployment ids and URLs, internal snapshot names, internal agent names, the internal codename
outside `NOTICE.md`, licensed font file names outside docs, and third-party media extensions under
`workspace/references/` or `examples/`. The list lives in `tests/unit/test_public_hygiene.py` and is
reviewed at release.

## 19. Configuration (`.env.example` outline)

```dotenv
# Model (provider:model). Gateway form: langsmith:provider/model
DESIGN_AGENT_MODEL=anthropic:claude-opus-5-5
DESIGN_AGENT_MODEL_EFFORT=high
DESIGN_AGENT_HELPER_MODEL=
DESIGN_AGENT_LOOK_MODEL=
DESIGN_AGENT_TOOL_SELECTOR_MODEL=
DESIGN_AGENT_MODEL_BASE_URL=
DESIGN_AGENT_MODEL_API_KEY_ENV=
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
GOOGLE_API_KEY=
LANGSMITH_API_KEY=            # MDA deploy/dev, LangSmith sandboxes, tracing, optional gateway
LANGSMITH_GATEWAY_API_KEY=

# Runtime
DESIGN_AGENT_RUNTIME=local          # local | mda | self_hosted
DESIGN_AGENT_SANDBOX=auto           # auto | mda | langsmith | docker | host
DESIGN_AGENT_SANDBOX_SNAPSHOT=
DESIGN_AGENT_SANDBOX_VCPUS=8
DESIGN_AGENT_SANDBOX_MEM_GIB=16
DESIGN_AGENT_SANDBOX_IDLE_TTL_SECONDS=600
DESIGN_AGENT_SANDBOX_EGRESS_ALLOW=
DESIGN_AGENT_MAX_PARALLEL_BUILDERS=3
DESIGN_AGENT_JOB_BUDGET_USD=

# Brand
DESIGN_AGENT_BRAND_PATH=workspace/brand    # falls back to examples/brands/example-studio
DESIGN_AGENT_PRIVATE_FONTS_DIR=private-fonts

# Media (optional)
DESIGN_AGENT_IMAGE_MODEL=
ELEVENLABS_API_KEY=
GROQ_API_KEY=

# Paper (optional)
PAPER_MODE=off                      # off | local | bridged
PAPER_MCP_URL=                      # local: http://127.0.0.1:29979/mcp or stdio; bridged: https://…/mcp
PAPER_BRIDGE_TOKEN=                 # bridged; MDA connection "paper-bridge" in production
PAPER_BRAND_FILE_ID=                # read-only
PAPER_DRAFTS_FILE_ID=
PAPER_TEAM_ID=                      # bridge team check

# Optional MCP
EXA_API_KEY=

# Behavior
DESIGN_AGENT_ENABLE_PROGRESS=1
DESIGN_AGENT_ENABLE_FOOTER=1
DESIGN_AGENT_ENABLE_STEERING=1
DESIGN_AGENT_ENABLE_LEARNING=1
DESIGN_AGENT_ENABLE_TOOL_CLEARING=0

# MDA Slack appearance
DESIGN_AGENT_SLACK_NAME="Design Agent"
DESIGN_AGENT_SLACK_DESCRIPTION="On-brand design and motion from a chat thread."
DESIGN_AGENT_SLACK_BACKGROUND_COLOR=

# Self-hosted
SLACK_BOT_TOKEN=
SLACK_APP_TOKEN=
SLACK_SIGNING_SECRET=
SLACK_TRANSPORT=socket_mode
DATABASE_URL=
DESIGN_AGENT_API_TOKENS=
DESIGN_AGENT_API_HOST=127.0.0.1
DESIGN_AGENT_API_PORT=8080
```

## 20. Tests and evals

### 20.1 Deterministic unit tests

Settings and capability registry; brand schema validation and token CSS generation; brand-lint with
fixture brands; video-gate per banned pattern; manifest generation and staging deltas; font
verification; Paper scope (allowlist, schemes after unescaping, protected file, default file,
missing-tool degradation) and bridge (bearer, rebinding, path, team); MCP isolation; tool disclosure
headers; image clamp; step budget; retry classification; history repair; harness primitives (events,
policy, inbox coalescing and retries, tasks, ledger heartbeats, wake-ups, durable transcript stubs and
caps, workflow memo and resume, branches backup and merge, watch parsers incl. HyperFrames and stall,
offload, learning merge and decay, meter); delivery exactly-once; ban-list hygiene; docs links.

### 20.2 Render smoke tests (CI render job, Docker)

Inside the sandbox image: Chromium screenshot of a fixture page at three sizes with brand fonts
resolved; `hyperframes lint`, `validate`, `snapshot --at 1.0`, 2 s 1920×1080 draft render with ffprobe
duration within one frame and non-blank first/last frames; ECharts and D2 fixture renders; image-ops
pipeline; audio mixer loudness on a synthesized fixture.

### 20.3 Real-graph contract tests

Scripted model, real Deep Agents graph, real middleware, fake MCP servers, fake media providers, a fake
sandbox backend (or the Docker runner in the render job): quick ask to delivery; storyboard gate before
a film render; `start_task` → progress → completion wake-up; restart → interrupted notice →
`resume_task` from transcript; `schedule_wakeup` and quiet replies; pipeline step memo and operator
question; looks fan-out, pick and merge; render job watcher wake on exit, failure and stall; steering
into a running helper; model failure boundary message; MCP server failure isolation; Paper storyboard
twin and export; memory policy when enabled.

### 20.4 Source-blind behavior evals

Hidden from implementation details, scored by trace assertions and deterministic checks: asks at most
two questions on a vague brief, otherwise decides and names its calls; storyboards before rendering a
film; lints and snapshots before a final render; never claims an attachment that was not uploaded;
does not invent brand rules or logos (asks for the logo); keeps copy exact; respects "fewest words";
uses `look` instead of hoarding frames; reports a blocked artifact after two correction rounds; handles
Paper being unavailable; stays quiet on check-ins with nothing new.

### 20.5 Design eval set and model matrix

`tests/eval/tasks.json`: ~25 tasks on the sample brand (4-size ad set, restyle a supplied layout,
LinkedIn card, 10-slide deck, flywheel diagram, bar chart with annotation, thumbnail set, storyboard,
15 s teaser, 45 s launch film with voiceover). Graders: artifact contract, brand-lint, text fidelity,
render gates, still-frame share, duration, cost and time; plus a human review checklist (no LLM taste
judge). Run at least: the default Anthropic model, one current OpenAI vision model, and one portable
model via `LLMToolSelectorMiddleware`. Record success, cost per accepted task, time, tool precision,
unnecessary calls.

### 20.6 Opt-in live tests

`DESIGN_AGENT_LIVE_TESTS=1`: model ping, image generation, ElevenLabs voice, LangSmith sandbox bake and
probe, Paper Local mode read/write/export on a scratch file, MDA dev smoke. Never run in CI by default.

## 21. Documentation and launch packaging

### 21.1 README (mirror the Paid Media Agent)

Centered header with LangChain OSS mark, name, one-line description ("On-brand design and motion from
a chat thread. Built on Deep Agents. Deploy with Managed Deep Agents."), links (Quick start ·
Deployment · Documentation · Contributing). A hero image of the designer's computer drawn for the
sample brand. "What it does" (stills and ad sets, decks, diagrams and charts, storyboards and motion,
long jobs with live progress). Quick start (`uv sync`, `uv run design-agent setup`, coding-agent
prompt, offline demo, first asks). "Built with" (HyperFrames, Paper, Deep Agents, MDA) with partner
links. Brand and fonts. Deployment table (MDA recommended vs self-hosted). Build on it (skills, brand,
tools, pipelines). License and health links.

### 21.2 Docs

`OPERATIONS.md` (commands, MDA deployment, Slack settings, schedules, sandbox, self-hosting, models,
verification), `docs/customization.md` (brand pack, fonts, references, runtime skills, memory,
schedules), `docs/self-hosting.md`, `docs/architecture/` (README with binding invariants,
runtime-profiles, orchestration, designers-computer, media-pipelines, context-and-cost, surfaces,
security), `docs/partners/{hyperframes,paper,paper-hosted-worker}.md`, `docs/gallery/` (outputs made
by the agent for the sample brand, each with its prompt and cost), `docs/sources/official-links.md`,
`CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, `NOTICE.md`, `CHANGELOG.md`.

### 21.3 Launch

The launch blog ("How we built our Design Agent") links the repository; the GTM Engineering Live
webinar demos clone → demo → deploy → Slack ask. Partner co-promotion (HyperFrames adopters listing
and quote-post, Paper integration post and a template file for the sample brand) follows partner
sign-off. The repository can launch after the blog; it must not block it.

## 22. Implementation slices

Each slice ends with its acceptance tests green, docs updated, and a short verification note in the
pull request (not in the repository).

0. **Ground truth.** Verify current official docs, installed `managed-deepagents` 0.9.3 and
   `deepagents` 0.7.28 APIs (`define_deep_agent`, `define_sandbox` extra keys, `upload_files`,
   `runtime.schedules`, `runtime.channel`, `connections.get`, `define_mcp` naming, memory layers),
   HyperFrames CLI flags at the pinned version, Paper transports. Bake the recipe once with MDA and
   measure size and time; decide `docker_image` bake versus published snapshot. Record results in
   `docs/sources/official-links.md`. Acceptance: a written compatibility table; a baked sandbox that
   passes the probe.
1. **Skeleton and computer.** Repository scaffold, settings, capability registry, assembly with one
   agent and no helpers, sandbox recipe and Docker runner, workspace stager, brand schema and sample
   brand, open fonts, gates ported and brand-neutral, `doctor`, `demo` (scripted model: one still in
   three sizes). Acceptance: clean clone → `demo` renders and passes brand-lint and artifact-contract.
2. **Media pipelines.** Stills, image-ops, data-viz, thumbnails, HyperFrames motion with video-gate and
   render smoke, audio host tools and mixer, image generation, delivery contract, CLI `ask`.
   Acceptance: render smoke suite green; scripted demo renders a 4 s teaser.
3. **Orchestration harness.** Port harness and lead tools behind `HelperRunner`, `Waker`,
   `SandboxExec`; MDA waker on runtime schedules; durable helpers; pipelines (launch film); looks;
   render watchers with HyperFrames parser; look tool; learning loop. Acceptance: §20.3 contracts green;
   wake latency measured and documented.
4. **Context, cost and failure boundaries.** Tool disclosure, cache policy, clearing, step budget,
   retry and failure boundary, history repair, MCP isolation, image clamp, meter and footer data.
   Acceptance: first-call prompt token budget measured and within target; failure-path tests green.
5. **MDA deployment and Slack.** `agent.py`, `identity.py`, channel, housekeeping schedule, sandbox
   declaration, progress streaming via the Slack Web API, footer, steering, file delivery, `deploy`
   preflight. Acceptance: deploy to a test workspace; a quick ask and a storyboarded teaser complete in
   Slack with live progress, check-ins and one delivery; a redeploy mid-job yields an interrupted notice
   and a successful resume.
6. **Paper.** Local and Bridged modes, scope middleware, bridge, storyboard twin and export, brand
   import in the onboarding skill. Acceptance: unit and contract tests; opt-in live test on a scratch
   file.
7. **Self-hosted.** FastAPI, Postgres repositories (checkpoints, helper records, transcripts, wake-ups,
   watches, observations), Bolt Slack adapter with streaming and file upload, Docker compose with the
   sandbox runner. Acceptance: compose up from a clean machine; the same Slack scenarios as Slice 5.
8. **Onboarding and console.** `.agents/skills/` (onboarding, brand-onboarding, vendor-sync,
   release-check), optional setup console (Welcome → Model → Media → Brand → Paper → Deploy) over the
   same CLI actions. Acceptance: a new developer configures and deploys using only the README and a
   coding agent.
9. **Skills and taste.** Port and scrub the design wiki, motion direction, launch film (new sample-brand
   case study), storyboard, reference study, sound, image generation; re-evidence doctrine against
   sample-brand films; run the eval set and model matrix; build the gallery. Acceptance: eval report
   committed under `docs/gallery/` (outputs and metrics), human review notes recorded.
10. **Release readiness.** Docs complete, ban-list and license inventory clean, gitleaks clean, partner
    reviews, legal review, CHANGELOG, tag. Acceptance: §23.

## 23. Definition of done (v0.1)

- A clean clone runs `uv sync && uv run design-agent demo` and renders a still set and a short film
  with no API keys (Docker present), or explains exactly what is missing.
- Model configuration is direct and documented; the capability registry is tested.
- MDA deployment is one command with a preflight; Slack works with live progress, check-ins, steering,
  file delivery and restart recovery.
- Self-hosted compose works with Slack, Postgres durability and the Docker sandbox runner.
- MDA, self-hosted and local runtimes use one assembly and pass the parity contract.
- HyperFrames is pinned, vendored skills verified, render smoke green; Paper Local and Bridged modes
  pass their tests; both partners have reviewed their sections.
- Every gate is brand-neutral and driven by the brand pack; the sample brand is complete.
- The eval set ran on at least three models with recorded results; the gallery shows real outputs.
- Public docs contain no private data; ban-list, license inventory and gitleaks are clean; NOTICE is
  complete; LICENSE is Apache-2.0; security contact is explicit.
- Commands, links, install steps and examples work from a clean environment.

## 24. Open questions and gates

| # | Question | Owner | Blocks |
| --- | --- | --- | --- |
| 1 | When will MDA release async subagents sharing the lead's sandbox and Slack thread, and a public "start a run on this thread" API? | MDA team | migration off the custom helper runner (not v0.1) |
| 2 | Is there a public one-click "deploy this GitHub repository" flow (the `mda prepare` path)? | MDA team | README deploy button |
| 3 | `docker_image` bake filesystem capacity for a ~2–3 GiB media image; recommended path? | MDA team | Slice 0 decision |
| 4 | Skills Context Hub limits (file count, size) for ~700 vendored files | MDA team | vendoring scope |
| 5 | HyperFrames skills license, pin strategy, provider override, render progress, OSS key, telemetry, GSAP guidance (`partner-integrations.md` §3) | HeyGen | Slices 2, 10 |
| 6 | Paper hosted MCP, export to remote agents, tool-name stability, plan limits, Linux Desktop (`partner-integrations.md` §3) | Paper | Slice 6 scope |
| 7 | Repository name final (`design-agent` vs the internal codename), org, and whether to publish to PyPI | LangChain marketing / OSS | Slice 10 |
| 8 | Legal review: fonts, sample brand, vendored skills, D2 binary in image, partner trademarks and logos in README | Legal | Slice 10 |
| 9 | Release timing relative to the launch blog and webinar | Marketing | none (repo must not block the blog) |
