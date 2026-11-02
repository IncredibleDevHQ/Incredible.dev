# Contributing

Read [AGENTS.md](AGENTS.md) first; it is the operating contract for humans and coding agents.

## Setup

```bash
uv sync --all-extras --dev
uv run design-agent sandbox build      # Docker: the designer's computer
uv run design-agent demo
```

## Skills: two kinds

- **Runtime skills** in [skills/](skills/) are what the agent reads while it works. Ours are
  edited here; vendored HyperFrames skills are never edited (see the `vendor-sync` skill). Each is
  `skills/<name>/SKILL.md`, one level deep, with a one-line "when to use" description.
- **Coding-agent skills** in [.agents/skills/](.agents/skills/) (linked from `.claude/skills`) are
  workflows for people and their coding agents: onboarding, brand onboarding, vendor sync, release
  check. They never reach the runtime.

## Before opening a pull request

```bash
make check     # ruff, ruff format, mypy, offline tests
make render    # render smoke inside the sandbox image (Docker)
make demo
```

The suite is offline by design: scripted models, a folder sandbox, fake MCP servers and fake
media providers. Live checks are opt-in (`DESIGN_AGENT_LIVE_TESTS=1`, `tests/live/`). Evals spend
money and run only on request ([docs/evals.md](docs/evals.md)).

## Rules that reviews enforce

- One shared assembly (`src/design_agent/assembly.py`). Runtimes and surfaces adapt it; they never
  fork tools, prompts or policy.
- The model makes creative calls; code renders, measures, gates, delivers and states every number
  a report contains.
- Keys stay on the host. Nothing reaches the sandbox but files; host tools fetch and generate.
- Anything that leaves the thread (publishing, posting elsewhere) needs a person in the loop.
- Untrusted input stays data: user files, Slack events, canvas content, MCP metadata, web pages.
- Public Managed Deep Agents APIs only. A missing seam goes behind an interface with an MDA adapter
  and a self-host adapter, and an upstream ask.
- Keep the root prompt small (`tests/contract/test_prompt_budget.py`); workflows go in skills.
- No company-specific content: brands, people, ids, licensed fonts or third-party media
  (`tests/unit/test_public_hygiene.py`).
- Comments explain constraints, not history. Delete what is obsolete instead of keeping layers.
