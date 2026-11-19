# Upstream asks

Seams this project works around today, each with what it does instead. Partner questions for
HyperFrames are in [docs/partners/hyperframes.md](partners/hyperframes.md).

## LangChain (1.4.6)

| Ask | Why | Today |
| --- | --- | --- |
| `jump_to: "end"` from an `after_agent` hook should reach the graph's end | it routes back to the first `after_agent` hook, so a hook that jumps loops until the recursion limit | no `after_agent` jumps |

## Deep Agents (0.7.28)

| Ask | Why | Today |
| --- | --- | --- |
| A TTL option for the prompt caching it installs | it always appends Anthropic caching with a 5-minute TTL; a lead read again an hour later pays to rewrite its prefix | `CachedChatAnthropic` sets every breakpoint to the role's TTL |
| A way to shorten skill descriptions in the resident list | vendored skills carry long upstream descriptions | `SkillListMiddleware` swaps them per request from `config/vendored-skills.toml` |

## Claude Code (2.1.326)

| Ask | Why | Today |
| --- | --- | --- |
| `--thinking-display` in the CLI reference | summaries of a model's thinking reach a `stream-json` reader only with it (`summarized`); the Agent SDK documents the same choice as `thinking.display`, the CLI's reference and `--help` do not list the option | the house passes it, and a CLI that answers `unknown option` is run again without it, where the trail shows the tokens thought so far in place of words (`research.run`) |
| A sign of life in `codex exec --json` and Kimi Code's `stream-json` while a model thinks | both print a line only once a message or tool call is whole, so minutes of thinking read the same as a hang | the trail says such an agent is quiet and why, and warns after ten minutes |
