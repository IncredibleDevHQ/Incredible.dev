# Architecture

One agent assembly (`src/design_agent/assembly.py`) serves Managed Deep Agents, the CLI, the
self-hosted API and Slack. Runtime profiles (`src/design_agent/runtime/`) supply what differs: the
sandbox backend, how files are delivered, how the lead is woken, where state persists.

| Page | Covers |
| --- | --- |
| [Orchestration](orchestration.md) | background helpers, wake-ups and check-ins, restarts and durable transcripts, pipelines, looks, render watchers, learning |
| [Context and failures](context-and-failures.md) | what the model sees, tool disclosure, cache discipline, cost, failure boundaries |
| [Surfaces](surfaces.md) | Slack progress, footer and steering on MDA and self-hosted, the API, the CLI |

Request path: a message arrives (Slack, API, CLI) → the lead's turn: the workspace is staged into the
thread's sandbox (skills' scripts, gates, brand pack, fonts) → the lead plans, composes, renders in
the sandbox, looks at its work, runs the gates → finals are delivered with `upload_files` and
recorded in the project's `DELIVERY.json` so nothing is sent twice. Long work runs as background
helpers in the same sandbox; their ends wake the lead.

Trust boundaries: model output, user files, Slack events, canvas content, MCP metadata and web pages
are data. Keys live in host tools; the sandbox has no credentials and no network by default.

## The lead and its helpers

- Each thread gets one lead. It writes a plan in the thread's project folder and decides what to
  delegate.
- Helpers run in the background on the same sandbox and files. Each one has a heartbeat, a
  durable transcript, and a lead that can steer it.
- Nobody sits and waits. Render watchers and check-ins wake the lead when work lands, fails or
  stalls: one-time schedules on Managed Deep Agents, an in-process waker everywhere else.
- Before anything ships, the lead and helpers look at their own renders with a vision `look`
  tool.

## The context

- The always-on prompt is small, about 4k tokens. Workflows live in [skills](../../skills/)
  (`skills/<name>/SKILL.md`) and load on demand. On Managed Deep Agents they mount read-only from
  Context Hub.
- Brand facts come only from the brand pack. It's staged into the sandbox with its fonts and logos.
- Context stays bounded:
  - Long tool results go to files, with a short summary in the conversation.
  - Provider tool search loads MCP tools only when they're needed.
  - Helpers can clear old tool results server-side.
  - Prompt caching keeps the lead's prefix warm for an hour.

## The designer's computer

- One recipe, [`sandbox/setup.sh`](../../sandbox/), pins Chrome Headless Shell, FFmpeg, HyperFrames,
  sharp, ECharts, D2 and open fonts by version and sha256. It ends with a probe that renders a
  page, a film and a diagram. The same recipe builds:
  - the local and self-hosted Docker image;
  - the LangSmith snapshot that Managed Deep Agents clones for each thread;
  - the CI image.
- Every thread gets its own sandbox, and its files persist in `/workspace/projects/` between turns.
  - Locally, it's a container with no network, dropped capabilities, an unprivileged user, and
    limits capped to your machine.
  - On Managed Deep Agents, it's a LangSmith sandbox (16 GiB disk, 8 vCPU) with default-deny
    egress.
- Before a run, a manifest with a sha256 checklist stages skills, the checks, your brand pack and
  its fonts into `/workspace`, read-only.

## The checks

The checks ([`workspace/tools/`](../../workspace/tools/README.md)) run before anything is delivered:

| Check | What it catches |
| --- | --- |
| `brand-lint` | off-brand colours, fonts, radii and copy |
| `video-gate`, `hyperframes check` | non-deterministic animation, layout, motion and contrast problems |
| `artifact-contract` | a wrong size or duration, a missing file, a blank first frame |
| font check | a brand font that silently fell back, web fonts included |
| chart and graph contracts | truncated baselines, mixed units, shares that don't add up to 100%, a diagram that changed shape |

## Keys stay outside

The sandbox never holds a credential. Host tools run next to the agent,
keep the keys, and drop their results in as files:

- image generation;
- voice, music and sound effects;
- transcription;
- an asset fetcher with SSRF protection;
- reading this deployment's own LangSmith traces (`list_traces`, `read_trace`);
- Paper, scoped by a policy;
- your MCP servers;
- delivery: to Slack, to `workspace/out/` locally, or attached to the LangSmith trace for API
  runs.

## Where each piece runs

| | Managed Deep Agents | Self-hosted |
| --- | --- | --- |
| Agent | `agent.py` (`define_deep_agent`), `identity.py`, `memory.py`, `tools/mcp.py` | the same assembly in a FastAPI app |
| Threads and memory | LangSmith; team and per-person memory layers (`memory.py`) | Postgres checkpointer and store; no memory layers |
| Sandboxes | LangSmith sandboxes from your snapshot (`sandbox/__init__.py`) | containers on your Docker host |
| Slack | managed app (`channels/slack.py`) | your Bolt app, Socket Mode or signed HTTP |
| Wake-ups and housekeeping | runtime schedules; `schedules/housekeeping.py` every 15 minutes | in-process waker and maintenance loop |
| Skills | synced to Context Hub; binary files ship as deployment files | read from the checkout |

## Models

Claude Opus 5.5 is the default, and any tool-calling model with vision works. A
registry keyed by exact model id sets effort, tool search and output limits per role: lead,
helper, look, tool selector and learning. The optional [LangSmith Gateway](../models.md) uses
each provider's native route, so caching and context editing keep working. Every call is metered
per job, helper and role, and LangSmith traces every run.
