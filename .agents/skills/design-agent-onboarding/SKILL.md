---
name: design-agent-onboarding
description: Install and configure Design Agent, add a brand, connect Paper, choose MDA or self-hosting, and diagnose setup without exposing credentials.
---

# Set up Design Agent

Work through these with the person, in order. Never print a key or token; report missing settings
by name. Do not deploy, connect accounts or publish anything until the person asks.

1. **Install and prove the computer.** `uv sync`, then `uv run design-agent sandbox build` (Docker;
   a cold build downloads about 2 GB and takes several minutes) and `uv run design-agent demo`: a
   scripted run renders the sample brand's launch card in three sizes and a 4-second teaser with no
   keys. If it fails, `uv run design-agent doctor` says what is missing.
2. **Model.** `uv run design-agent config set DESIGN_AGENT_MODEL=provider:model` and the provider's
   key (`ANTHROPIC_API_KEY=…`, or `LANGSMITH_GATEWAY_API_KEY` for a `langsmith:` model; typed by the
   person, or set in `.env` by hand). Defaults and other roles: `docs/models.md`. Re-run `doctor`,
   then `uv run design-agent test model`: `doctor` only checks that a key is set, the test makes
   one cheap call with it.
3. **Media keys (optional).** `OPENAI_API_KEY` (image generation), `ELEVENLABS_API_KEY` (voice,
   music, sound effects), `GROQ_API_KEY` (fast transcription). Each tool says plainly when its key
   is missing.
4. **Brand.** Follow the `brand-onboarding` skill to build `workspace/brand/` from what the person
   has (a brand guide, a website, files, or a Paper file). Until then the sample brand is used.
5. **Paper (optional).** `PAPER_MODE=local` when Paper Desktop runs on this machine; `bridged` for a
   deployed agent (see `docs/partners/paper.md`). `off` is fine: boards render in the sandbox.
6. **Try it.** `uv run design-agent ask "Make a LinkedIn card announcing …"`. Finals land in
   `workspace/out/<thread>/`, the last line estimates what the run cost, and `--thread <id>`
   continues a conversation.
7. **Choose where it runs.** Managed Deep Agents (managed runtime, sandboxes, Slack app and
   schedules; one command) or self-hosted (Docker Compose with Postgres and their own Slack app).
   The [design-agent-deploy](../design-agent-deploy/SKILL.md) skill takes it from there, including
   verifying with a real request.
8. **What next.** Teach it the deliverable the team asks for every week
   ([design-agent-customize](../design-agent-customize/SKILL.md)), and measure changes with
   [design-agent-evals](../design-agent-evals/SKILL.md).
