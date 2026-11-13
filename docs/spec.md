# Design Agent: product and engineering specification

This fork runs self-hosted behind its own web UI. Slack, Paper and the Managed Deep Agents /
LangSmith-hosting paths were removed, and the spec below is trimmed to match.

Status: spec-first. This document is the source of truth until the implementation and its tests
exist; afterwards code and tests win and this document is kept current as the design record.
Precedence when sources disagree: `AGENTS.md` → this spec → `docs/architecture/` → official current
documentation (`docs/sources/official-links.md`) → installed package behavior and live probes →
model memory (never sufficient for a fast-moving API).

## 1. Outcome

Ship an open-source design agent that a team can deploy in an afternoon and use the next morning. In a
chat thread (or the terminal), anyone can ask for on-brand design work and get finished files back:
ads in every size, social cards, slides and decks, diagrams, charts, thumbnails, storyboards and
motion graphics up to a 1–3 minute launch film with voiceover and music.

The product succeeds when, from a clean clone, a developer can:

- run an offline demo that renders a still and a short HyperFrames film through the real agent graph
  with a scripted model and no API keys;
- configure a model, a brand pack (or the bundled sample brand) and optional media keys;
- self-host it with Docker;
- ask for a resize, a restyle, a deck, a chart, a storyboard or a film and receive files that pass
  deterministic brand, layout and render gates;
- watch a multi-hour job progress with a plan, an ETA, live status and check-ins, steer it mid-job,
  survive a deploy or restart, and receive the final once;
- swap the brand without touching code.

What makes it worth open-sourcing is not "a video CLI plus a model". It is the harness: the
designer's computer, the orchestration that lets one lead and several helpers work for hours on the
same machine, the context discipline that keeps it fast and cheap, the deterministic gates, and the
taste encoded as skills. The internal reference deployment taught every rule in this spec.

## 2. Positioning and name

- Public name: **Design Agent**. Repository: `design-agent` (target `github.com/langchain-ai/design-agent`).
  Python package `design_agent`, console script `design-agent`, environment prefix `DESIGN_AGENT_`.
- Tagline: "On-brand design and motion from a chat thread. Built on Deep Agents. Renders with
  HyperFrames."
- It is the third LangChain go-to-market agent released this way, after the GTM Agent post and the
  open-source Paid Media Agent. Follow the Paid Media Agent's repository shape, documentation voice,
  onboarding, deployment paths, CI and release discipline unless this spec says otherwise.
- Partner: HeyGen (HyperFrames, the video engine). The integration is first-class, attributed,
  pinned and tested. See [docs/partners/](partners/).

## 3. Users and core journeys

### 3.1 Developer / operator

1. `git clone … && cd design-agent && uv sync && uv run design-agent demo` — no keys; needs Docker
   (local sandbox); `doctor` explains what is missing.
2. Configure a model (`provider:model`), optional media keys (OpenAI images, ElevenLabs), and a brand
   pack with the coding-agent onboarding skill or the optional setup console.
3. `uv run design-agent ask "Make a 1080x1350 LinkedIn card announcing our v2 launch"` locally.
4. `uv run design-agent serve` or `docker compose up -d --build` (self-host).
5. `uv run design-agent doctor` diagnoses configuration without printing secrets.

### 3.2 Requester (marketer, PM, engineer, founder)

- Quick ask: message → finished file in minutes → a note → fixed file.
- Big ask (deck, film): message → plan with phases and ETA → storyboard for a yes → live status while
  helpers build → check-ins every 10–15 minutes → first cut → final and cut-downs.
- Mid-job steering: "make the logo bigger" goes into the running work without stopping it.
- Options: "show me three directions" → three looks side by side → pick one → it continues.
- Drop files (logos, screenshots, footage, a reference film) into the thread; the agent uses them.

### 3.3 Brand owner / designer

- Defines the brand once as a brand pack (tokens, logos, fonts, voice, graphic language) — by hand
  or with the brand-onboarding skill — and reviews it.
- Teaches taste: corrections become observations the agent weighs on the next similar job; studying a
  reference film produces a teardown and proposed skill edits a person approves.

### 3.4 Maintainer

- Adds a skill, a tool, a renderer or a gate once in the shared assembly; every runtime gets it.
- Updates vendored HyperFrames skills with one script and a reviewed diff.
- Reproduces every release claim with a test, fixture, render, live probe or official source.

## 4. Scope

### 4.1 Included in v0.1

- One shared Deep Agents assembly for the self-hosted API and the CLI.
- The orchestration harness (§7): lead plus background helpers on one sandbox, wake-ups and
  self-scheduled check-ins, durable helper transcripts and resume, pipelines as code (launch film),
  parallel looks, detached render jobs with watchers, the `look` tool, context and cost controls,
  failure boundaries, steering, a presenter hook for live progress (§7.11), the per-skill learning
  loop.
- The designer's computer (§8): a reproducible sandbox recipe with Chrome Headless Shell, ffmpeg, the
  pinned HyperFrames CLI, sharp, ECharts, D2, open fonts; workspace staging; bring-your-own licensed
  fonts.
- Media pipelines (§9): stills, multi-size ads, decks, charts and diagrams, thumbnails, storyboards,
  HyperFrames motion, audio (voice, music, effects), image generation, deterministic gates, delivery.
- HyperFrames integration (§10).
- Taste and judgment as skills (§11): a public design wiki, motion direction, storyboard-first,
  launch-film phases and briefs, critic, reference study, image generation craft, sound.
- Brand system (§12): validated brand-pack schema, a sample brand, onboarding, brand-lint.
- Surfaces (§14): self-hosted API and CLI.
- Direct model providers with a tested capability registry; LangSmith Gateway optional.
- Tests (§20): unit, real-graph contracts with a scripted model, render smoke tests, offline behavior
  checks, opt-in live tests, a design eval set, a model matrix.
- Documentation and launch packaging (§21).

### 4.2 Planned for v0.2 (extension points designed now, code later)

- **Routines**: person-owned recurring jobs with generic sources (RSS/Atom, web page) and the "a
  scheduled run never publishes" rule.
- **Publishing plugin**: approval-gated posting with an exactly-once publish ledger, revisions and
  slots (Buffer and others), with code-drawn approval cards.
- **Peer agents**: a configurable registry of other agents the design agent may @mention for facts.
- **Grounding**: read-only Drive/Docs/Notion style context tools.

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
- A web frontend in the engine itself: this fork's own web UI plugs in through the presenter hook
  (§7.11).
- A required model gateway or proxy.

## 5. Architecture

### 5.1 Layers

```text
┌───────────────────────────────────────────────────────────────┐
│ The lead and its helpers      plans, delegates, reports        │  what we build
│ The context                   skills · design wiki · brand ·   │
│                               observations                     │
│ The designer's computer       one sandbox per thread: renderers│
│                               (HyperFrames, Chromium, sharp,   │
│                               ffmpeg, ECharts, D2), fonts,     │
│                               workspace folders, gates         │
│ The self-hosted runtime       HTTP API, Postgres or SQLite,    │
│ (or local: CLI, demo, tests)  Docker sandboxes, wake-ups       │
├───────────────────────────────────────────────────────────────┤
│ Deep Agents                   planning, files, subagents,      │  off the shelf
│                               skills, summarization            │
│ The model                     Claude Opus 5.5 by default       │
└───────────────────────────────────────────────────────────────┘
   Outside the sandbox (host tools and MCP): image generation, voice and
   music, optional web research. Keys never enter the sandbox.
```

### 5.2 One core, thin adapters

```text
runtime/self_hosted.py (API)                 runtime/local.py (CLI, demo, tests)
             \                                         /
        build_agent_components(settings, runtime_profile) ── src/design_agent/assembly.py
                                  |
      model · tools · middleware · subagents · skills · interrupt policy · pipelines
                                  |
                          Deep Agents graph
                                  |
   sandbox backend (Docker | host-dev) · host tools · MCP (config/mcp.toml)
```

The self-hosted and local entries compile the same components with `create_deep_agent`. MCP
servers are declared in `config/mcp.toml` (http, sse or stdio; credentials through `headers_env`
from the host environment) and their tools are named `{server}_{tool}`. Shared behavior lives under
`src/design_agent/`; surface code never enters domain, tool or policy modules.

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
are core dependencies; others are extras.

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

This is the core value. Each primitive below states its contract and its implementation.

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

Implementation: helpers run in-process as asyncio tasks invoking the declared subagent graphs with
the lead's sandbox backend, exactly like the internal reference, behind a `HelperRunner` protocol.
On the self-hosted runtime the runner lives inside the API process, with helper records,
transcripts, check-ins and watches persisted in the store (Postgres, or SQLite without
`DATABASE_URL`).

### 7.3 Durable helpers

A helper's transcript is checkpointed to the store as it works (tool results before each model call,
the reply after it). `resume_task(id)` restarts the worker with a one-line brief that a before-agent
hook swaps for the saved transcript plus a closing note. Saved history is always valid to send back:
viewed images become text stubs naming the file; thinking blocks are dropped (a provider rejects
replayed thinking once earlier history was edited); a tool call cut off by the restart gets a result
saying its effect is unknown; past a byte cap, the oldest steps after the brief are dropped with a
marker. Before this existed, a 90-minute builder could lose most of its work to a deploy.

### 7.4 Wake-ups and check-ins (`Waker`)

```python
class Waker(Protocol):
    async def wake(self, target: WakeTarget, message: str, *, dedupe_key: str) -> WakeReceipt: ...
    async def schedule(self, target: WakeTarget, at: datetime, message: str) -> str: ...
    async def cancel(self, schedule_id: str) -> None: ...
```

- Coalescing inbox: multiple events within a short window become one notice; retries at 10 s, 1 min,
  5 min; delivery counts only once the lead's run actually started.
- In-process adapter (CLI, demo, self-hosted API): start a run on the thread in the same process.
  Check-ins are timers kept in the store; at startup the self-hosted API re-arms them (one whose
  time passed while the process was down fires at once) and sweeps what a restart killed (§15.2).

### 7.5 Pipelines as code

When a job has a known shape, the pipeline runs it as code and the model makes the creative calls
inside steps. `run_pipeline(name, args_json)`, `answer_pipeline(run_id, answer)`; finished steps
replay from a memo; `resume_task("p-…")` continues a run after a restart; a pipeline can `ask` the
operator a question (the lead relays it). Ship `launch_film`: plan (max) → lead act (max) → each act
(xhigh or max) reviewed by a critic as it lands with one fix pass → assembly → final review → operator
approval → final render. Running a launch film from instructions alone, the internal lead skipped
reviews; control flow belongs in code, judgment in briefs. `episode_plan` plans a 4 to 10 minute
explainer in words before any picture, in stages a person signs off between: the brief and its
ledger of claims (max); the top layer (the spine from the brief, max, then the chapter list from
the spine, xhigh); and each chapter's beats (xhigh) followed by its shots, written from those
beats (xhigh). Shots are never written beside their beats: the shots step is handed the beats in
its brief and does not start until they pass. The voice is written with the beat, and its shots
cut the passage without changing a word. The brief names the gap the idea closes for the viewer;
the chapter list gives each chapter one question, names the one chapter the film turns on, and
carries the first line and a last line that lands the idea without reciting it. A first reader
(xhigh) then sends back what a viewer would trip on, once; its verdict is kept as a file. A
last stage writes only the shots of a chapter whose beats stand. Every step has a time limit: a
helper that goes quiet is stopped and its step re-issued once.

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
- Cost meter: per call, per role, per job, published to traces and a presenter's footer. Prices
  live in `config/prices.toml` with a date and source; figures are estimates.
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

- Steering: a person's turn while helpers run notes what is running, and `steer_task` passes their
  follow-up to a running background helper, which reads it before its next model call ("I've added
  your notes to the fix pass that's already running").
- Presentation: a surface plugs into runs through the `Presenter` protocol in
  `src/design_agent/surfaces/presenter.py` (`lead_middleware(settings, services)`,
  `helper_middleware(settings)`), held by `RuntimeProfile.presenter`. With no presenter, runs are
  headless. The fork's web UI plugs in here for live progress and follow-ups; no presenter ships yet.
  `DESIGN_AGENT_ENABLE_PROGRESS`, `DESIGN_AGENT_ENABLE_FOOTER` and `DESIGN_AGENT_ENABLE_STEERING` are
  switches a presenter reads.
- Footer: only what changes — agents running, time left, cost, trace link.
- Every piece of presenter UI starts as a mock people react to before it is built (the first internal
  progress message was rejected on sight).

### 7.12 Learning loop

After a job, the lead saves observations for the owning skill (`save_observations`) or has
`learn_from_job` propose up to five from the thread, each with evidence. Before a similar job it reads
them (`read_observations`) and rates the ones that helped or misled (`rate_observation`). Near
duplicates merge; a note whose harm votes lead by two is dropped. Observations are notes the agent
weighs, never rules. Brand rules are forever; model rules last until the next model. Optional, on by
default when a store exists.

### 7.13 Memory

Removed in this fork (MDA native memory layers); observations (§7.12) carry the learning.

## 8. The designer's computer

### 8.1 Recipe

One reproducible recipe (`sandbox/setup.sh`) builds the local and self-hosted Docker sandbox image and
the CI image:

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

- Every download is version-pinned and checksum-verified. No `@latest` at build time.
- The build fails unless `hyperframes lint` and a 1-second draft render of the bundled fixture
  succeed, a Chromium screenshot of a fixture page succeeds, and ffprobe confirms the outputs.
- Never put instructions, skills, brand packs, user data, fonts under license, credentials or `.env`
  values in the image.
- Measure the final size.
- Size: default 8 vCPU / 16 GiB for motion (renders take 8–40 s per second of film on CPU); document a
  2–4 vCPU profile for stills-only teams. Sizes come from `DESIGN_AGENT_SANDBOX_VCPUS` and
  `DESIGN_AGENT_SANDBOX_MEM_GIB`.
- Egress: sandbox containers run with no network; downloads happen only when the image is built.
  Compositions must not need the network at render time (GSAP and fonts are local).

### 8.2 Workspace layout (inside the sandbox)

```text
/workspace/
  attachments/        files people drop in the thread
  projects/<slug>/    BRIEF.md, PLAN.md, run.json, sources, compositions, renders, review/, DELIVERY.json
  skills/<name>/      staged copies of skill scripts and assets (/skills is mounted read-only,
                      outside the sandbox filesystem, so scripts cannot run in place)
  tools/              gates: brand-lint, video-gate, film-probe, text-fidelity, …
  brand/              the active brand pack (tokens, logos, voice, graphic language)
  fonts/              open fonts plus the operator's licensed fonts
  references/         the user's reference films and teardowns (when provided)
  .renders/           detached render logs and exit files
```

`projects/<slug>/` lives with the thread's sandbox: files survive an idle stop; running processes do
not. Staged copies are refreshed every run, so edits to them die with the run.

### 8.3 Workspace staging

A `WorkspaceStager` middleware stages, on the first model call of a cold sandbox and whenever the
manifest digest changes: skill scripts and assets, `workspace/tools/`, the active brand pack, open and
licensed fonts. It uploads one compressed delta with a sha256 checklist through the sandbox backend's
file API, runs a fontconfig refresh, verifies required font families resolve (`fc-match`), and writes
a ready marker. The manifest is generated by `scripts/build_manifest.py`, never hand-edited.

### 8.4 Fonts

- Open fonts ship in `fonts/` with `LICENSES.md` and the OFL text, and are built into the image.
- Licensed fonts are bring-your-own: the operator places files in Git-ignored `private-fonts/` and
  declares them in the brand pack's `fonts.toml` (`family`, `weight`, `style`, `file`, `sha256`,
  `required`). The stager uploads them to the sandbox; the self-hosted runtime mounts the folder
  read-only. Never commit them; `design-agent fonts verify` checks each is present with its recorded
  checksum.
- Renderers read font stacks from the brand pack; no renderer hard-codes a family. A missing font
  never fails loudly in a browser (it silently falls back), so renders that need a brand font check it
  first and the gate fails the job rather than shipping a fallback.

### 8.5 Sandbox backends

| Backend | Runtime | Notes |
| --- | --- | --- |
| Docker sandbox runner | self-hosted, local | containers from `sandbox/Dockerfile`, one per thread, idle reaping, per-thread volume; only the runner touches the Docker socket; no network; default for `demo` when Docker exists |
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
plan → storyboard (frames from HTML or HyperFrames snapshots, optionally image-generation look plates)
→ animatic timed to voiceover or music → production → final → cut-downs. When a canvas is connected
the board is published there as well (the `canvas` skill); the thread always gets the contact sheet.
Timing locks at animatic approval. A storyboard note costs minutes; after production it costs an
hour. Footage-based work (screen recordings, captions, narrated explainers, website tours,
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

Nothing is auto-delivered. The agent sends finals with the host tool `upload_files(paths)` (1–10
files, ≤ 200 MiB each) on every runtime, deliver first then reply, and never claim something is
attached unless the upload succeeded this turn. `DELIVERY.json` prevents a retry from sending twice.
After two blocking correction rounds on the same artifact in a phase, stop and report it blocked.
Delivery copies files into `workspace/out/<thread>/`; the API serves them to the thread owner and the
CLI prints their paths.

## 10. HyperFrames integration

See [HyperFrames](partners/hyperframes.md). Summary:

- HyperFrames is the only video engine in v0.1; the CLI is pinned; the upstream agent skills are
  vendored unmodified at a pinned commit with per-file checksums, LICENSE and NOTICE.
- Deep Agents discovers skills only at `skills/<name>/SKILL.md` (one level), so vendored skills live
  at the top level under their upstream names (`skills/hyperframes`, `skills/hyperframes-cli`, …) and
  `skills-lock.json` marks them vendored; CI fails if a vendored file differs from the lock.
- Local routing, brand and provider guidance live in our own skills beside them, never as edits to
  vendored files. Provider calls (TTS, audio) route through host tools; the sandbox holds no keys.
- `video-gate`, render watchers with a HyperFrames parser, and render smoke tests are part of CI.
- Attribution in README and NOTICE; an `ADOPTERS.md` entry upstream once public and agreed.

## 11. Taste and judgment (runtime skills)

### 11.1 Skill set for v0.1

| Skill | Purpose |
| --- | --- |
| `media-production` | router: which pipeline, storyboard-to-render process, delivery contract |
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
provides: a brand guide PDF, a website or existing files. It asks at most two questions per turn,
records sources and dates, never invents rules, and asks a person to review. The setup console only
points at the skill; it does not edit the brand.

## 13. Paper integration

Removed in this fork: the Paper MCP, its bridge and hosted worker, and the Paper scope policy.

## 14. Surfaces

### 14.1 MDA native Slack

Removed in this fork, with the self-hosted Slack adapter; a presenter (§7.11) is the hook for live
progress.

### 14.2 Self-hosted API

- FastAPI (`design-agent serve`): `POST /threads/{id}/messages`, artifact downloads for the thread
  owner, health, bearer tokens mapped to callers, per-caller thread ownership. Not the LangGraph Agent
  Server protocol.

### 14.3 CLI

`design-agent ask "<request>" [--file …] | demo | doctor | serve | brand (validate|css|show|init) |
config (show|set|generate) | eval (list|run) | sandbox (build|test) | skills (verify|sync-vendor) |
manifest | fonts verify | test (model|sandbox|db)`, with `--json` where useful.

### 14.4 Studio

Removed in this fork (`mda dev` in LangSmith Studio).

## 15. Runtime profiles, persistence and deployment

| Profile | Graph | Persistence | Sandbox | Schedules |
| --- | --- | --- | --- | --- |
| Local | `create_deep_agent` | in-memory checkpointer; local store file | Docker runner (default) or host-dev | none |
| Self-hosted | `create_deep_agent` behind FastAPI | Postgres checkpointer and store (SQLite without `DATABASE_URL`) | Docker runner | your scheduler calls the CLI; housekeeping runs in-process |

Parity contract: for the same model, brand, skills, thread state and request, every profile exposes the
same capabilities and produces the same files. Presentation and timing may differ.

### 15.1 Managed Deep Agents

Removed in this fork: the MDA deploy path and LangSmith-hosted sandboxes.

### 15.2 Self-hosted

`docker compose up -d --build` starts the API, Postgres and the sandbox runner. `design-agent serve`
runs the HTTP API with bearer tokens (`DESIGN_AGENT_API_TOKENS`), Postgres persistence
(`DATABASE_URL`; SQLite files in `workspace/state/` without it) and a maintenance timer that sweeps
what a restart killed every 15 minutes and reaps idle sandbox containers. Back up Postgres and the
workspace volume.

## 16. Security and safety

- Untrusted inputs: model output, user files, incoming messages, MCP metadata, web pages, reference
  films and their transcripts. None of them can grant permission, change policy, reveal secrets or
  trigger publishing.
- Secrets: environment or deployment secrets only. Never in prompts, graph state, sandbox files,
  logs, errors, fixtures, snapshots or tests. Host tools hold keys and drop files in.
- Sandbox: workspace path allowlist; no `.env`, host home, Docker socket, SSH agent or cloud metadata;
  default-deny egress at runtime; sanitized archive extraction, paths, filenames, MIME types, sizes;
  SSRF-hardened asset fetch for user-supplied URLs; artifacts move through host-controlled transfer.
- Tool authorization: selection is not authorization. Before invocation trusted code resolves the
  exact tool, validates arguments against the current schema, and sanitizes errors.
- No outward actions in v0.1 beyond replying in the thread.
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
instructions.md · sandbox/{setup.sh,Dockerfile,README.md}
skills/<name>/                     runtime skills, ours and vendored (one level; see §10)
src/design_agent/
  assembly.py · config.py · cli.py · doctor.py · demo.py · deployment.py
  models/ · harness/ · middleware/ · tools/ · pipelines/ · brand/
  runtime/{profiles.py,self_hosted.py,local.py,sandbox/,waker/}
  surfaces/{api/,presenter.py} · admin/ (optional console) · testing/ (scripted model, fakes, fixtures)
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

Python 3.11+, uv, Pydantic v2, Ruff, mypy (strict for new modules; ported harness modules may start
in a documented gradual list that shrinks to zero before v0.1), pytest, Node only inside the sandbox
recipe. One `pyproject.toml`, one lockfile, explicit upper bounds on fast pre-1.0 packages
(`deepagents>=0.7.28,<0.8` at the time of writing; never a `.devN` pin in a release).

### 18.3 CI

- `ci.yml` (Python 3.11 and 3.13): lockfile install, Ruff, format, mypy, offline tests, scripted demo
  (render steps skipped without Docker, executed in the render job), `skills verify` (vendored
  checksums), ban-list scan, docs link check.
- Render job: build `sandbox/Dockerfile`, run the recipe probe and the render smoke tests (§20.2).
- `secrets` job: pinned gitleaks over full history.
- `compatibility.yml` weekly: `uv lock --upgrade`, latest stable Deep Agents, latest HyperFrames CLI
  and skills in a throwaway lock; run the suite; never auto-merge.
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
LANGSMITH_API_KEY=            # tracing, optional gateway
LANGSMITH_GATEWAY_API_KEY=

# Runtime
DESIGN_AGENT_RUNTIME=local          # local | self_hosted
DESIGN_AGENT_SANDBOX=auto           # auto | docker | host
DESIGN_AGENT_SANDBOX_VCPUS=8
DESIGN_AGENT_SANDBOX_MEM_GIB=16
DESIGN_AGENT_SANDBOX_IDLE_TTL_SECONDS=600
DESIGN_AGENT_MAX_PARALLEL_BUILDERS=3
DESIGN_AGENT_JOB_BUDGET_USD=

# Brand
DESIGN_AGENT_BRAND_PATH=workspace/brand    # falls back to examples/brands/example-studio
DESIGN_AGENT_PRIVATE_FONTS_DIR=private-fonts

# Media (optional)
DESIGN_AGENT_IMAGE_MODEL=
ELEVENLABS_API_KEY=
GROQ_API_KEY=

# Optional MCP
EXA_API_KEY=

# Behavior
DESIGN_AGENT_ENABLE_PROGRESS=1
DESIGN_AGENT_ENABLE_FOOTER=1
DESIGN_AGENT_ENABLE_STEERING=1
DESIGN_AGENT_ENABLE_LEARNING=1
DESIGN_AGENT_ENABLE_TOOL_CLEARING=0

# Self-hosted
DATABASE_URL=
DESIGN_AGENT_API_TOKENS=
DESIGN_AGENT_API_HOST=127.0.0.1
DESIGN_AGENT_API_PORT=8080
```

## 20. Tests and evals

### 20.1 Deterministic unit tests

Settings and capability registry; brand schema validation and token CSS generation; brand-lint with
fixture brands; video-gate per banned pattern; manifest generation and staging deltas; font
verification; MCP isolation; tool disclosure headers; image clamp; step budget; retry
classification; history repair; harness primitives (events, policy, inbox coalescing and retries,
tasks, ledger heartbeats, wake-ups, durable transcript stubs and caps, workflow memo and resume,
branches backup and merge, watch parsers incl. HyperFrames and stall, offload, learning merge and
decay, meter); delivery exactly-once; ban-list hygiene; docs links.

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
into a running helper; model failure boundary message; MCP server failure isolation.

### 20.4 Source-blind behavior evals

Hidden from implementation details, scored by trace assertions and deterministic checks: asks at most
two questions on a vague brief, otherwise decides and names its calls; storyboards before rendering a
film; lints and snapshots before a final render; never claims an attachment that was not uploaded;
does not invent brand rules or logos (asks for the logo); keeps copy exact; respects "fewest words";
uses `look` instead of hoarding frames; reports a blocked artifact after two correction rounds; stays
quiet on check-ins with nothing new.

### 20.5 Design eval set and model matrix

`tests/eval/tasks.json`: ~25 tasks on the sample brand (4-size ad set, restyle a supplied layout,
LinkedIn card, 10-slide deck, flywheel diagram, bar chart with annotation, thumbnail set, storyboard,
15 s teaser, 45 s launch film with voiceover). Graders: artifact contract, brand-lint, text fidelity,
render gates, still-frame share, duration, cost and time; plus a human review checklist (no LLM taste
judge). Run at least: the default Anthropic model, one current OpenAI vision model, and one portable
model via `LLMToolSelectorMiddleware`. Record success, cost per accepted task, time, tool precision,
unnecessary calls.

### 20.6 Opt-in live tests

`DESIGN_AGENT_LIVE_TESTS=1`: model ping, image generation, ElevenLabs voice. Never run in CI by
default.

## 21. Documentation and launch packaging

### 21.1 README (mirror the Paid Media Agent)

Centered header with LangChain OSS mark, name, one-line description ("On-brand design and motion from
a chat thread. Built on Deep Agents."), links (Quick start · Deployment · Documentation ·
Contributing). A hero image of the designer's computer drawn for the sample brand. "What it does" (stills and ad sets, decks, diagrams and charts, storyboards and motion,
long jobs with live progress). Quick start (`uv sync`, `uv run design-agent setup`, coding-agent
prompt, offline demo, first asks). "Built with" (HyperFrames, Deep Agents) with partner links. Brand
and fonts. Deployment (self-hosted). Build on it (skills, brand, tools, pipelines). License and health
links.

### 21.2 Docs

`OPERATIONS.md` (commands, sandbox, self-hosting, models, verification), `docs/customization.md`
(brand pack, fonts, references, runtime skills), `docs/self-hosting.md`, `docs/architecture/` (README
with binding invariants, runtime-profiles, orchestration, designers-computer, media-pipelines,
context-and-cost, surfaces, security), `docs/partners/hyperframes.md`, `docs/gallery/` (outputs made
by the agent for the sample brand, each with its prompt and cost), `docs/sources/official-links.md`,
`CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, `NOTICE.md`, `CHANGELOG.md`.

### 21.3 Launch

The launch blog ("How we built our Design Agent") links the repository; the GTM Engineering Live
webinar demos clone → demo → deploy → first ask. Partner co-promotion (HyperFrames adopters listing
and quote-post) follows partner sign-off. The repository can launch after the blog; it must not
block it.

## 22. Implementation slices

Each slice ends with its acceptance tests green, docs updated, and a short verification note in the
pull request (not in the repository).

0. **Ground truth.** Verify current official docs, installed `deepagents` 0.7.28 APIs and
   HyperFrames CLI flags at the pinned version. Build the recipe once and measure size and time.
   Record results in `docs/sources/official-links.md`. Acceptance: a written compatibility table; a
   built sandbox that passes the probe.
1. **Skeleton and computer.** Repository scaffold, settings, capability registry, assembly with one
   agent and no helpers, sandbox recipe and Docker runner, workspace stager, brand schema and sample
   brand, open fonts, gates ported and brand-neutral, `doctor`, `demo` (scripted model: one still in
   three sizes). Acceptance: clean clone → `demo` renders and passes brand-lint and artifact-contract.
2. **Media pipelines.** Stills, image-ops, data-viz, thumbnails, HyperFrames motion with video-gate and
   render smoke, audio host tools and mixer, image generation, delivery contract, CLI `ask`.
   Acceptance: render smoke suite green; scripted demo renders a 4 s teaser.
3. **Orchestration harness.** Port harness and lead tools behind `HelperRunner`, `Waker`,
   `SandboxExec`; durable helpers; pipelines (launch film); looks; render watchers with HyperFrames
   parser; look tool; learning loop. Acceptance: §20.3 contracts green.
4. **Context, cost and failure boundaries.** Tool disclosure, cache policy, clearing, step budget,
   retry and failure boundary, history repair, MCP isolation, image clamp, meter and footer data.
   Acceptance: first-call prompt token budget measured and within target; failure-path tests green.
5. **MDA deployment and Slack.** Removed in this fork.
6. **Paper.** Removed in this fork.
7. **Self-hosted.** FastAPI, Postgres repositories (checkpoints, helper records, transcripts, wake-ups,
   watches, observations), Docker compose with the sandbox runner. Acceptance: compose up from a
   clean machine; a quick ask and a storyboarded teaser complete through the API with check-ins and
   one delivery; a restart mid-job yields an interrupted notice and a successful resume.
8. **Onboarding and console.** `.agents/skills/` (onboarding, brand-onboarding, vendor-sync,
   release-check), optional setup console (Welcome → Model → Media → Brand → Deploy) over the
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
- Self-hosted compose works with Postgres durability, the Docker sandbox runner, check-ins, steering,
  file delivery and restart recovery.
- Self-hosted and local runtimes use one assembly and pass the parity contract.
- HyperFrames is pinned, vendored skills verified, render smoke green; the partner has reviewed its
  section.
- Every gate is brand-neutral and driven by the brand pack; the sample brand is complete.
- The eval set ran on at least three models with recorded results; the gallery shows real outputs.
- Public docs contain no private data; ban-list, license inventory and gitleaks are clean; NOTICE is
  complete; LICENSE is Apache-2.0; security contact is explicit.
- Commands, links, install steps and examples work from a clean environment.

## 24. Open questions and gates

| # | Question | Owner | Blocks |
| --- | --- | --- | --- |
| 5 | HyperFrames skills license, pin strategy, provider override, render progress, OSS key, telemetry, GSAP guidance (`partner-integrations.md` §3) | HeyGen | Slices 2, 10 |
| 7 | Repository name final (`design-agent` vs the internal codename), org, and whether to publish to PyPI | LangChain marketing / OSS | Slice 10 |
| 8 | Legal review: fonts, sample brand, vendored skills, D2 binary in image, partner trademarks and logos in README | Legal | Slice 10 |
| 9 | Release timing relative to the launch blog and webinar | Marketing | none (repo must not block the blog) |
