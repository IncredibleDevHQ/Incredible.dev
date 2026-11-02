---
name: design-agent-customize
description: Change what Design Agent knows and does. Teach it a new deliverable with a runtime skill, change its instructions, design doctrine or checks, connect MCP servers and tools, or change models and cost caps. Use when someone wants it to make something new, follow a new rule, or use another tool.
---

# Customize Design Agent

Every kind of knowledge has one home. Find the owner before editing, so a fix lands once and every
asset after it follows:

| The change | Its home |
| --- | --- |
| Brand facts: colours, fonts, logos, voice, graphic language | `workspace/brand/` ([brand-onboarding](../brand-onboarding/SKILL.md)) |
| A deliverable or workflow the team asks for often | a runtime skill, `skills/<name>/SKILL.md` |
| Doctrine for every visual: hierarchy, type, colour, charts | `skills/design-wiki/references/` |
| Identity, delivery and approval rules, how it talks | `instructions.md` (a budget test fails past about 8k tokens) |
| A rule a machine can count | a check in `workspace/tools/` |
| A tool or data source | an MCP server in `config/mcp.toml` |
| Which model plays which role, effort, budgets | `.env` settings; [Models](../../../docs/models.md) |

## Add a runtime skill

Start with the graphic the team asks for every week.

1. Read two skills close to it (`skills/stills/`, `skills/thumbnails/`) and `skills/design-wiki/SKILL.md`.
2. Create `skills/<name>/SKILL.md` as a real folder one level deep (MDA does not follow symlinks
   there). Frontmatter: `name` is the folder; `description` says when to use it, in the words
   people use when they ask. Body: what good looks like, sizes, steps, the checks to run. Put depth
   in `references/` and keep the body small. Text only: binary files (fonts, images) go in
   `skill-binaries/<name>/`, because Context Hub takes only UTF-8 text; the stager puts them back
   beside the skill in the sandbox.
3. No brand facts, colours or libraries from a CDN in the skill: the brand pack supplies them.
4. `uv run pytest -q tests/unit/test_taste_skills.py tests/unit/test_media_skills.py` checks
   frontmatter, size, links, and that every tool, script and check it names exists.
5. Try it with the request people actually send: `uv run design-agent ask "…"`. Look at the files.
6. Add an eval task if it matters ([design-agent-evals](../design-agent-evals/SKILL.md)), then
   redeploy ([design-agent-deploy](../design-agent-deploy/SKILL.md)).

Vendored skills (HyperFrames and LangSmith, listed in `skills-lock.json`) are never edited: override them in a
sibling skill of ours, or send the change upstream.

## Instructions, doctrine and checks

- Phrase rules as defaults with a reason, or as checks with evidence. A rule about the model is
  temporary; retest it when the model changes and delete what the new model outgrows.
- A rule a machine can count belongs in code, as a check, not in prose.
- After editing, run `uv run pytest -q`, then compare before and after with the evals.

## Tools

- **MCP servers:** copy `config/mcp.example.toml` to `config/mcp.toml` and declare servers. Locally,
  header values come from the environment (`headers_env`); on MDA a server that needs credentials
  names a workspace connection (`connection`), owned by the deployment or each person (`owner`).
  The example file has presets for Notion, Linear, GitHub, Figma and others
  ([integrations](../../../docs/integrations.md)). MDA serves HTTP and SSE only. Paper is configured
  with `PAPER_*`, not here ([Paper](../../../docs/partners/paper.md)).
- **Media keys:** `OPENAI_API_KEY` (images), `ELEVENLABS_API_KEY` (voice, music, sound effects),
  `GROQ_API_KEY` (transcription).
- **A new host tool** is code in `src/design_agent/tools/`: keys stay on the host and results drop
  into the sandbox as files. Follow the change discipline in `AGENTS.md`.

## Models and cost

`uv run design-agent config set DESIGN_AGENT_MODEL=provider:model`, then
`uv run design-agent test model`. `DESIGN_AGENT_JOB_BUDGET_USD` makes the agent ask before passing
a budget; `DESIGN_AGENT_HELPER_EFFORT_CAP` caps helpers' effort. More: [Customization](../../../docs/customization.md).
