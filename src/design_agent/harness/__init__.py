"""The orchestration harness: the primitives under Design Agent's background work.

A job (a launch film, a render, a batch of thumbnails) runs for minutes to hours. The lead starts
helpers and watchers, ends its turn, and is woken by what happens. These primitives make that
cheap, visible and durable. Each module is one primitive; each publishes or consumes
`harness.events.Event`s and depends only on the small protocols in `harness.protocols`, never on
MDA, Slack or a sandbox client, so the same code runs under every runtime profile and in tests.

Core (the event spine):
- `events`: the `Event` type, the in-process `BUS`, and the store-backed `EventLog`.
- `policy`: the attention rule: which events wake the lead now, which wait for its next turn,
  which are only recorded, and which need a person.
- `protocols`: `HelperRunner`, `SandboxExec`, `Waker`.
- `tasks`, `ledger`, `inbox`, `notices`, `wakeups`: background helpers, their heartbeat records
  and sweep, coalesced delivery to the lead, the notice it is woken with, and its own check-ins.

Building blocks:
- `watch`, `offload`: watchers that turn a log or status file into events, with a stall timer, and
  detached render jobs tracked the same way.
- `cache`, `context`, `meter`: a stable prompt prefix, cache TTL per role, clearing old tool
  results the way the API accepts, image-aware token counts, and the cost of every job.
- `durable`: helpers that save their transcript as they go and resume after a restart.
- `workflow`: pipelines whose control flow is code, with memoized steps that replay after a crash.
- `branches`: several creative looks in parallel, then one picked and merged.
- `learning`: observations with evidence and counts, saved after a job and read by the next.

docs/architecture/orchestration.md explains each primitive and its upstream counterpart.
"""
