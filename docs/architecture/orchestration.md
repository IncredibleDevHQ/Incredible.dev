# Orchestration

Design Agent's lead plans, delegates and reports. Helpers do the long work (builds, reviews,
renders) in the background, on the same sandbox, while the lead stays free to talk. The lead ends
its turn as soon as work is running and is woken when something happens. The code that makes this
work is the harness in `src/design_agent/harness/`.

The harness imports only the standard library, `langchain`, `langchain_core` and `langgraph`. It
never imports MDA, Slack or a sandbox client. Hosts plug in through three small protocols in
`harness/protocols.py`, so the same primitives run under Managed Deep Agents, the self-hosted
runtime, a plain Deep Agents graph, and the unit tests.

| Protocol | What the host provides |
| --- | --- |
| `HelperRunner` | `start(brief, effort=…)` returns a task id at once; `run(…)` awaits a `HelperResult` |
| `SandboxExec` | `execute(command, timeout=…)` in the thread's sandbox, returning an `ExecResult` |
| `Waker` | `wake(target, message, dedupe_key=…)`, `schedule(target, at, message)`, `cancel(id)` |

## The event spine

Everything that happens in the background is one `Event` (`harness/events.py`): a kind
(`task.done`, `watch.stalled`, `wakeup.due`, …), the thread it concerns, its source (`t-…` helper,
`r-…` watch, `p-…` pipeline, `w-…` check-in), a label, a sentence of text and structured data.
Producers publish to the in-process bus. Consumers subscribe: the inbox, the cost meter, and the
store-backed `EventLog`, which keeps a thread's events for a week. Producers and consumers never
import each other.

The attention rule (`harness/policy.py`) decides what each event costs the lead:

| Delivery | Events | Effect |
| --- | --- | --- |
| `NOW` | helper finished, failed or interrupted; watch failed, stalled or finished; check-in due; someone must act | wake the lead |
| `NEXT` | helper progress notes, pipeline steps | ride along with the lead's next turn |
| `LOG` | starts, per-frame render progress, usage | recorded only |

`data["urgent"]` promotes any event to `NOW`; `data["ping"]` marks one a person must act on.
Unknown kinds wake the lead, because nothing is dropped silently.

## Waking the lead

`Inbox` (`harness/inbox.py`) is built once per process with the host's `Waker` injected. Work that
starts on a thread registers a `WakeTarget` for it: the thread id plus an opaque `channel` the
adapter uses (where replies post). `NOW` events landing within five seconds of each other, or while
a wake-up is under way, are delivered together as one notice (`harness/notices.py`). The notice says
how each helper ended, what is still running, and the likely next step. A lead turn that starts
for any other reason (a message from the person) carries whatever is still waiting, so the lead is
not woken again for news it already has.

A reply of exactly `[quiet]` means there is nothing worth saying. Locally and self-hosted, the
runtime posts wake-up replies itself and drops it. On MDA every scheduled run's reply is posted by
MDA's schedule delivery, an `after_agent` hook installed ahead of every authored middleware, so it
runs last and cannot be skipped (and an empty reply would make it repost an earlier one). There
`QuietReplyMiddleware` rewrites a final `[quiet]` into one line about the work still running
("Still working: act 2 (12 min)."). The upstream ask: let a scheduled run end without a post.

A wake-up counts as delivered only when the waker's `WakeReceipt` says the lead's run started. A
failure, or a receipt with `delivered=False`, is retried after 10 s, 1 min and 5 min with
whatever landed meanwhile. After the last retry the events are held for the lead's next turn. Each
wake-up carries a `dedupe_key` built from the thread and the batch's event ids, so a retry of a
batch that did start a run can be recognised by the adapter.

Adapters live outside the harness. Self-hosted, the waker enqueues a run in the API process with a
Postgres timer table for check-ins (SPEC §7.4). On MDA it uses public one-time runtime schedules on
the current thread (`runtime/waker/mda.py`), with these constraints from managed-deepagents 0.9.4:

- **Latency.** A schedule's `at` must be at least a minute ahead and is rounded up to the next
  whole minute, so a wake-up lands 60–120 s after the event, plus the scheduler's own lag. The
  inbox coalesces meanwhile, so one wake-up carries everything that happened. Measuring the lag
  needs a deployment; the upstream ask is a public "start a run on this thread now" API.
- **Delivery receipt.** The woken run's first hook writes the wake key to the deployment store;
  the waker polls for it for up to five minutes before it counts the wake-up delivered.
- **Who can schedule.** Only a run's own runtime can create a schedule, for that run's thread. The
  waker keeps each thread's latest `runtime.schedules`, so after a restart a thread has none until
  a run happens on it.
- **Restarts.** While a thread has background work, it holds one sentinel schedule 15 minutes
  ahead, which the process pushes forward every five minutes. It fires only once that process is
  gone; the sentinel turn sweeps the ledger at once, so its reply says what the restart stopped.
  If it fires while the work still runs (a postponement failed), the turn ends without a model call.
- **Ownership and caps.** Agent-owned same-thread schedules need a channel binding; runs without
  one (Studio, the API) schedule as the caller. Each owner holds at most `MDA_MAX_AGENT_SCHEDULES`
  (default 20) unexpired schedules; a thread uses one sentinel plus its pending wake-ups and
  check-ins.

## Background helpers and restarts

`harness/tasks.py` runs a helper as an asyncio task and publishes `task.started`, `task.progress`,
`task.done`, `task.failed` and `task.cancelled`. `CURRENT` (and the meter's `CURRENT_TASK_ID`)
names the helper whose code is running, so its tools, transcript and cost are attributed to it.

A process restart kills in-process helpers silently, so the ledger (`harness/ledger.py`) keeps a
heartbeat record per helper in the deployment store, refreshed every minute. The record also
holds how the helper ended until the lead has been told. `ledger.sweep` finds records whose
heartbeat is more than three minutes old: a helper still marked running is published as
`task.interrupted`, and one that ended but was never delivered is published as a normal finish.
Check-ins the lead scheduled (`harness/wakeups.py`) live in the ledger too, so one a restart
swallowed fires late rather than never.

## Durable helpers

`TranscriptCheckpointMiddleware` (`harness/durable.py`) saves a helper's history to the store as
it works: tool results before each model call, the reply after it. `resume_task(id)` restarts the
worker with `resume_brief(id)`, and the middleware swaps that one-line brief for the saved
transcript and a closing note. What is saved is always valid to send back:

- viewed images and other media become text stubs naming their file (`[image you viewed: …]`);
- thinking blocks are dropped, since a provider may reject replayed thinking after an edit;
- a tool call a restart cut off gets a result saying its effect is unknown;
- past the byte cap (8 MB), the oldest steps after the brief are dropped, with a marker.

## Pipelines as code

`WorkflowRunner` (`harness/workflow.py`) runs registered pipelines (`fn(ctx, **args)`) in the
background. Control flow is Python; every creative call is a helper brief. `ctx.agent` runs one
helper and can validate the JSON its report ends with, sending it back with the problem up to
`attempts` times. `ctx.parallel` and `ctx.pipeline` fan out, and `ctx.ask` parks the run until a
person answers through the lead. Every step is memoized by the hash of its brief, effort, schema
and label. A re-run after an answer, a restart or `resume_task("p-…")` replays finished steps
instantly and runs only the rest. Pipelines must be deterministic: no clock, randomness or
environment inside them.

## Parallel looks

`Looks` (`harness/branches.py`) copies a project into `looks/<id>/` per creative direction
(without `looks/`, `out/` and `node_modules/`, which is linked back) and starts one helper per look.
Each helper writes `look.json` with its direction, summary and stills. `LookWatch` hears every look's
helper end and asks a person to pick. `pick` backs the project up to `looks/_backup-<ts>/`, then
merges the chosen look over it with newer files winning. Looks belong at the stills stage, never
full renders.

## Render jobs and watchers

`WatchRunner` (`harness/watch.py`) polls a source every 15 s, parses new output and publishes
`watch.progress` (fraction, phase, ETA), `watch.done`, `watch.error`, or `watch.stalled` after five
minutes with no new output and no progress. A watch that stalled and starts moving again says so
urgently. Polling the sandbox also keeps an idle sandbox alive. `SandboxDetachedRender`
(`harness/offload.py`) runs a command under `nohup`/`setsid` with its output in a log and its exit
code in `<log>.exit`; the exit code is the verdict, and the log feeds progress.

Parsers come from `parser_for(kind)`:

| Kind | Reads |
| --- | --- |
| `heartbeat` (default) | any output as a sign of life; failure lines (`Error`, `Traceback`, `Killed`, OOM, `exited with code N`) end it |
| `hyperframes` | `hyperframes render` progress (below) |
| `ffmpeg` | `-progress` blocks or the stats line; a percentage with `total_frames` or `duration_seconds` |
| `json` | a status file (`status`, `step`, `progress`, `eta`), read with `SandboxJsonSource` |
| `regex` | any `N/M` counter or percent, with optional done and error patterns |

HyperFrames 0.8 writes two forms of progress. Without a TTY (a detached job's log) it prints a
machine line per step beside a plain progress line:

```text
  ██████████░░░░░░░░░░░░░░░  42%  Streaming frame 18/60
@hf-progress {"code":"capture","done":18,"total":60,"pct":42}
```

Under a TTY it redraws one colored bar with `\r` and prints no machine lines. The stage codes are
`compile`, `extract_video`, `process_audio`, `start_browsers`, `capture`, `encode` and `assemble`.
The parser maps either form to one phase name, takes `pct` as the fraction, and reads frame counts
during capture and encode. A render is done at `100%  Render complete`, and the parser waits one
read for the `◇  <output path>` line that follows. It fails at a `NN%  Failed: …` progress line,
`Render cancelled`, the CLI's error box (`✗  Render failed`, `✗  Not a directory: …`) or a killed
process. It deliberately ignores generic `Error` text, because a best-effort render logs the page's
own script errors as warnings and still finishes. Real captured logs live in
`tests/unit/harness/fixtures/`.

`WatchLedger` keeps each watch's record in the store: what it reads and how, where it stands, and
the host's wake data. The record is refreshed while the watch runs and kept after it ends until the
lead has heard the end. After a restart, `sweep` publishes a lost end again, or reports a cut-off
watch as `task.interrupted`. That record stays resumable for 24 hours, so `resume_task("r-…")` can
watch the same log (and exit file) again under the same id.

## Context and cost

- `harness/cache.py` rewrites every `cache_control` breakpoint in a request to one TTL (1h for the
  lead, which sleeps between turns; 5m for helpers) and adds a breakpoint on the tools array when
  the tools are Anthropic-shaped. A payload for another provider passes through unchanged.
  `StaggerGate` holds a wave of sibling helpers until the first response starts, so they read the
  shared prefix rather than each writing it. `PrefixWatch` logs which part of a prefix changed.
- `harness/context.py` builds Anthropic's server-side tool-result clearing for helpers (opt-in)
  and counts image tokens by their real cost instead of LangChain's flat 85 tokens, reading image
  sizes from file headers with the standard library.
- `harness/meter.py` prices every call from its uncached, cache-write (by TTL), cache-read and output
  tokens, and sums a job (thread) per source and per role. Prices live in `config/prices.toml`, one
  entry per provider and model with the date it was checked and its public source. Long-context
  tiers are included where a provider has them. Every figure is an estimate; the provider's invoice
  is the source of truth.

## Learning

`ObservationStore` (`harness/learning.py`) keeps per-skill observations: what a past job showed,
with evidence. A near-duplicate (token Jaccard ≥ 0.8 or difflib ratio ≥ 0.85) merges into the
existing note and counts again. Ratings add helpful or harmful votes. A note whose harmful votes
lead by two is dropped by `prune`. Notes are `proposed` until seen again, rated helpful or given
by a person. The rendered list is headed as untrusted notes the next job weighs, never rules.

## Upstream status

| Primitive | Upstream today | Plan |
| --- | --- | --- |
| Background helpers on the lead's sandbox | Deep Agents async subagents run as server runs on their own threads; MDA does not build them yet | migrate when MDA runs async subagents on the lead's sandbox, then delete the in-process runner |
| Durable transcripts | server runs are checkpointed; in-process subagents are not | keep the stub rules if replay still needs them |
| Wake-ups | Deep Agents notifies a parent when a same-deployment async subagent finishes | becomes the native path for helper results once async subagents ship in MDA |
| Event bus, attention rule, watchers, detached jobs, pipelines, looks, meter | none | candidates to upstream as they are |
