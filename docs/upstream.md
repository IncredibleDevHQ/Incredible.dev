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
