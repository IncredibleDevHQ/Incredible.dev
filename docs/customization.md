# Customization

Everything below is local files: edit them by hand or with your coding agent, then redeploy.

## Brand

`workspace/brand/` (Git-ignored) holds your pack: `brand.toml`, `tokens.json`, `fonts.toml`,
`voice.md`, `graphic-language.md`, `logos/`. The schema is `src/design_agent/brand/schema.py`; the
sample pack in `examples/brands/example-studio/` shows every field. `uv run design-agent brand
validate` checks it and `brand css` regenerates `tokens.css`. The [brand-onboarding
skill](../.agents/skills/brand-onboarding/SKILL.md) builds a pack from your sources.

Colour roles: `design.roles.light` and `design.roles.dark` in `tokens.json` name the token for each
role (`ground`, `ink`, `accent`, `muted`, `quiet`, `rule`, and a `series` list). Charts and diagrams
use them; a role you leave out is measured from the palette.

Fonts: each family in `fonts.toml` points at an open font in `fonts/` or a licensed file in
`private-fonts/` (Git-ignored), and `family` is the name inside the file (`fonts verify` checks it).
Web formats work: `tokens.css` declares `.woff2` and `.woff` faces with `@font-face`. Licensed fonts
reach the sandbox as deployment files (MDA) or a read-only mount (self-hosted), never through Git.

## Instructions and skills

Two folders hold skills. `.agents/skills/` is for coding agents working on this repo (onboarding,
brand setup, deploy, evals); `skills/` is what the agent itself reads at work.

- `instructions.md` is the always-loaded prompt: identity, how the agent works, delivery and
  approval rules, how it talks. Keep it short; the budget test fails past about 8k tokens.
- `skills/<name>/SKILL.md` are workflows the agent opens when a job needs them. Add one for a
  format your team makes often (a newsletter header, a conference kit): a one-line "when to use"
  description, steps, sizes, the gates to run, and links to `references/` for depth. Keep the
  folder to text: MDA syncs it to Context Hub, which takes only UTF-8, so a skill's fonts or
  images go in `skill-binaries/<name>/` and reach the sandbox beside the skill.
- Rules come with evidence or are phrased as defaults; brand facts belong in the brand pack, not
  in skills.

## Learning

After a job the agent can save what it learned for the skill it used (`save_observations`), or
have a quick helper propose observations (`learn_from_job`). Before a similar job it reads them and
rates the ones that helped. Observations live in the deployment's store and are notes the agent
weighs, never rules. Turn it off with `DESIGN_AGENT_ENABLE_LEARNING=0`.

## Traces

The agent reads its own LangSmith traces: `list_traces` finds runs by time, thread, trigger or
failure, and `read_trace` writes one run tree to the workspace with its errors and slowest steps.
Ask it in the thread ("why did the last render fail?") and it can look. It reads only the project
its runs are traced to, but every thread in it: turn it off with `DESIGN_AGENT_ENABLE_TRACES=0`
where people must not see each other's requests ([SECURITY.md](../SECURITY.md#trace-access)).

## MCP servers

[Integrations](integrations.md) sets up the hosted ones (Notion, Linear, GitHub, Figma and more) in
a few commands. Copy `config/mcp.example.toml` to `config/mcp.toml` and declare servers there. Every runtime names
their tools `{server}_{tool}`; the agent discovers them on demand, so many servers do not crowd its
context. Locally, header values come from your environment (`headers_env`); on MDA a server that
needs credentials names a workspace connection (`connection`), owned by the deployment or by each
person (`owner`). A local app's own server can run
over stdio (`transport = "stdio"` with a `command`) locally and self-hosted; MDA serves HTTP and SSE
only and leaves it out. A server that fails to load or errors leaves the rest working. Paper is
configured with `PAPER_*` instead ([Paper](partners/paper.md)), so do not declare a `paper` server.

## Settings

`uv run design-agent config show` lists every setting with its current value (secrets as set or
unset); `.env.example` documents each one.
