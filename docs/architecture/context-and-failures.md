# Context, cost and failure boundaries

How the agent keeps each model call small and cacheable, what it costs, and why an error never
ends a run silently. Code: `src/design_agent/middleware/guards.py` and the modules it lists.

## What the model sees

The always-loaded prompt is `instructions.md`, deepagents' tool notes, and one line per skill.
Workflows live in skills, brand facts in the brand pack, and both are opened when a job needs them.

Measured on the real graph with the sample brand (`tests/contract/test_prompt_budget.py`, which
fails if either number passes its ceiling):

| First lead call | Characters | Approx. tokens | Ceiling |
| --- | --- | --- | --- |
| System prompt, skill list included (36 skills) | 15,413 | ~4,400 | 8,000 (SPEC §5.4) |
| Tool schemas (39 tools, no MCP) | 40,288 | ~11,500 | 12,000 |

The skill list was 15,551 characters before vendored skills got one-line summaries. Upstream
HyperFrames and LangSmith skills are vendored unmodified, with descriptions written for other
setups; `SkillListMiddleware` hands deepagents a copy of the thread's skill metadata in which
each vendored skill's description is its line from `config/vendored-skills.toml`. Nothing is written
to the thread, and `tests/unit/test_guards.py` keeps the summaries equal to
`skills-lock.json`.

deepagents 0.7.28 appends no framework prompt for the registry's models; the budget test fails if
anything but `instructions.md` leads the system prompt.

## Tool disclosure

Host tools and the framework's own are always bound. Tools from MCP servers (`config/mcp.toml`,
named `{server}_{tool}` on every runtime) are disclosed on demand:

- Verified Anthropic and OpenAI models: provider-native tool search. Each deferred tool's
  description opens with its name in plain words, because search is lexical and does not split
  `docs_SearchPages` into words. A server marked `always_shown` stays bound.
- Other models: `LLMToolSelectorMiddleware`, bounded to `DESIGN_AGENT_MCP_MAX_TOOLS` per call, over
  MCP tools only, on the tool-selector role's model.

Selection is not authorization: approval and policy act on a call's name, deferred or not.

## Cache discipline

- Stable prefix: the system prompt does not change while work runs. The date and anything that
  happened in the background arrive as messages, written once into history.
- deepagents installs Anthropic prompt caching with a five-minute TTL on every agent. The lead's
  thread is read again minutes to hours apart, so `CachedChatAnthropic` sets every breakpoint to
  the role's TTL: `DESIGN_AGENT_CACHE_TTL` (lead, `1h`) and `DESIGN_AGENT_HELPER_CACHE_TTL` (`5m`).
- Fan-out stagger: helpers started in one wave over the same prefix wait (up to 5 s) for the first
  sibling's response, so the prefix is written once, not N times.
- Server-side clearing of old tool results in helpers' requests (`clear_tool_uses_20250919`) is
  available behind `DESIGN_AGENT_ENABLE_TOOL_CLEARING` and off until measured: each clear breaks
  the cached prefix, so it waits for a 120k-token prompt and clears at least 20k tokens.
- Large tool results go to files (deepagents' eviction at 20k tokens stays on).

## Cost

Every model call's usage is priced from `config/prices.toml` (dated, sourced list prices) and summed
per job, per helper and per role (`harness/meter.py`). Figures are estimates. With
`DESIGN_AGENT_JOB_BUDGET_USD` set, the lead is told once, when a job's spend reaches it, to ask the
person before starting more work; nothing is stopped in code.

## Failure boundaries

| Failure | What happens |
| --- | --- |
| Connection blip, 408/409/429, 5xx | Retried up to five times over ~15 s (`model_retry.py`). Never a tool call. |
| Stalled call (read timeout after `DESIGN_AGENT_MODEL_TIMEOUT_SECONDS`) | Not replayed. The lead's turn ends with a line saying so; the work is in the thread and sandbox, so "continue" resumes. |
| Retries exhausted | Same: one line, the run continues to exist. |
| 4xx | Raised: it fails the same way every time, and someone has to fix it. |
| Graph step limit near | The turn wraps up with tools off: what is finished, with paths, and the next step, marked partial in `response_metadata`. |
| A synchronous `task` subagent raises | The lead gets a tool error naming the exception class, and can do the step itself. |
| `upload_files` raises | A tool error saying the files were not sent; never claimed as sent. |
| An MCP server fails to load | Left out with a warning; the rest load (`throw_on_load_error=False` on MDA). |
| An MCP call raises | A tool error naming the server; other tools keep working. |
| History names a tool that is gone | References are dropped per call; if the provider still refuses, one deeper repair folds the old calls into text notes and retries once. |
| Mislabeled or oversized image | Its type is read from the bytes and it is resized to a 1500 px long edge before the call; undecodable bytes drop that block only. |

Helpers have no turn-ending boundary: their failure reaches the lead as news (a failed helper's
notice), and the lead decides.

Order matters and is fixed in `guards.py`: image clamp, failure boundary (lead only), step budget,
retry, skill list, tool disclosure, history repair, meter.
