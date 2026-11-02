# CLI

`uv run design-agent <command>`; `--help` on any command for its options.

| Command | Does |
| --- | --- |
| `demo` | a scripted run through the real agent, sandbox and gates, no keys: a card in three sizes and a 4-second teaser |
| `doctor [--json]` | checks Python, packages, every model role, keys, the brand, the sandbox and MCP, without printing secrets |
| `ask "<request>" [--thread ID] [--file PATH]… [--no-wait]` | one request with your model; stays open for background work; threads persist in `workspace/state/` |
| `config show\|set KEY=VALUE…\|generate KEY…` | read and change `.env` without printing secrets |
| `brand validate\|css\|show\|init` | check the active pack, regenerate `tokens.css`, show it, start one from the sample |
| `fonts verify` | brand font files present with their checksums; open fonts listed in `fonts/LICENSES.md` |
| `sandbox build\|test` | build the local image, run its probe |
| `skills verify\|sync-vendor` | vendored HyperFrames, LangSmith and Deep Agents skills against `skills-lock.json`; re-vendor from upstream (`--upstream` for one, `--check-only` to compare pins) |
| `manifest` | what the workspace stager puts in each sandbox |
| `serve` | the self-hosted HTTP API ([self-hosting](self-hosting.md)) |
| `eval list\|run` | the eval set ([evals](evals.md)); `run` spends money and asks first |
| `test model\|sandbox\|db` | real connectivity checks; `model` costs a cent or so |

There is no web setup console in v0.1: `config`, `doctor` and the coding-agent
[onboarding skill](../.agents/skills/design-agent-onboarding/SKILL.md) cover setup.
