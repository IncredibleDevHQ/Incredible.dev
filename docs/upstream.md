# Upstream asks

Seams this project works around today, each with what it does instead. Partner questions for
HyperFrames and Paper are in [docs/partners/](partners/).

## Managed Deep Agents (0.9.4)

| Ask | Why | Today |
| --- | --- | --- |
| A public "start a run on this thread now" API | waking the lead after background work lands in 60–120 s through one-time schedules, which round to the next minute | `runtime.schedules.create(at=now+61s, new_thread=False)` ([orchestration](architecture/orchestration.md)) |
| Let a scheduled run end without a post | schedule delivery posts the newest non-empty assistant text of the thread, from a hook installed ahead of every authored middleware; an empty reply would repost an earlier one | a `[quiet]` reply becomes a one-line status of the running work |
| Async subagents that share the lead's sandbox, and a background general-purpose subagent | helpers must work in the lead's sandbox on the lead's files | in-process helpers behind `HelperRunner`, with heartbeats and durable transcripts |
| Schedules creatable for a thread from outside a run | after a restart, a thread has no route for wake-ups until a run happens on it | a sentinel schedule per busy thread, pushed forward while the process lives |
| Streaming and message updates on `runtime.channel` | live progress and the footer need updates to one message | the Slack Web API with the reserved `mda/slack-bot-token` connection |
| A way to add input to a running run, or choose the strategy for a busy thread | a second Slack message queues behind the running turn | steering reads the thread before each model call and folds follow-ups in; the queued run ends with one line |
| Route direct-message follow-ups to the thread already working | a new top-level DM is its own thread and runs in parallel | not handled |
| Expose a schedule run's Slack conversation and thread | after a restart, wake-up turns cannot find their Slack thread until a message run happens | progress reuses the thread's last known target |
| Dedupe Slack's duplicate deliveries at ingress; react when a message is queued | duplicate events and a silent queue | not handled on MDA (the self-hosted adapter dedupes) |
| An ignore list for `mda deploy` | it archives Git-ignored files (except `.env` and virtualenvs), so renders in `workspace/out/` count toward the 200 MB limit | `doctor` warns past 150 MB; clear old renders |
| Same-thread wake-ups for API callers: agent-owned schedules without a channel, or API keys counted as people | a thread started with an API key cannot be woken (`User schedules require an authenticated person`; agent-owned same-thread schedules need a channel), so background work over the API never reports back | Slack only ([deploy guide](deploy-mda.md#4-verify)) |
| A larger filesystem for `docker_image` bakes (honor `fs_capacity_bytes`) | the computer is 1.3 GiB; `docker_image` bakes get a fixed 1 GiB, so a fresh clone can't go straight to `mda deploy` | a published snapshot (`design-agent sandbox publish`) once per workspace |

## LangChain (1.4.6)

| Ask | Why | Today |
| --- | --- | --- |
| `jump_to: "end"` from an `after_agent` hook should reach the graph's end | it routes back to the first `after_agent` hook, so a hook that jumps loops until the recursion limit | no `after_agent` jumps; the quiet reply is rewritten instead |

## Deep Agents (0.7.28)

| Ask | Why | Today |
| --- | --- | --- |
| A TTL option for the prompt caching it installs | it always appends Anthropic caching with a 5-minute TTL; a lead read again an hour later pays to rewrite its prefix | `CachedChatAnthropic` sets every breakpoint to the role's TTL |
| A way to shorten skill descriptions in the resident list | vendored skills carry long upstream descriptions | `SkillListMiddleware` swaps them per request from `config/vendored-skills.toml` |
