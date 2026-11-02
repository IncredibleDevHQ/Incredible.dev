# Surfaces: Slack, the API and the CLI

Every surface reaches the same agent. What differs is presentation: in Slack the agent shows its
work as it goes, takes follow-ups mid-job, and ends each reply with a short footer.

## Slack presentation

Code: `src/design_agent/surfaces/slack/` (Web API client, who a run answers, step phrases, the
stream) and `src/design_agent/middleware/{progress,footer,steering,tracing}.py`.

- **Live progress.** One message per turn shows a card per step in plain studio language
  ("Studying the brand", "Rendering the teaser"), through Slack's streaming API
  (`chat.startStream`/`appendStream`/`stopStream`), or one message redrawn with `chat.update` when
  streaming is refused. It settles to "Done", or is deleted when the turn's reply is `[quiet]`.
  Cards never carry argument text: no paths, queries, file ids or anybody's words. Each background
  helper streams its own message.
- **Footer.** Only what changes: agents still running, time so far, estimated cost of the job, and
  a trace link when `DESIGN_AGENT_TRACE_HOST` is set (a trace URL exposes workspace and run ids, so
  it is off by default).
- **Steering.** A follow-up while helpers run starts a turn at once (the lead ends its turn after
  handing work off), sees what is running, and can pass the note to a helper with `steer_task`;
  the helper reads it before its next model call. While the lead's own turn is busy, it reads new
  messages in the thread before each model call and folds them in; "stop", "cancel" or "never mind"
  ends the turn at its next step.
- **Trace tags.** Each run is tagged with its trigger, surface and the kinds of files delivered, and
  names the template and version it came from (`DESIGN_AGENT_TEMPLATE_TELEMETRY=0` turns that
  off); no user ids by default.

The bot token stays on the host: progress and footer call the Slack Web API from middleware, and
the sandbox never sees a token, a Slack URL or a Slack payload.

## Managed Deep Agents

MDA's channel posts the final reply, reacts to the starting message, transfers attachments to
`/workspace/attachments/` and provides `upload_files`. Presentation uses the reserved
`mda/slack-bot-token` connection and the event on `runtime.channel`.

A second message in a busy Slack thread becomes a run queued behind the current one (there is no
public way to add input to a running run). The steering middleware folds it into the running turn
by reading the thread, so the queued run ends at once with "Folded that into the work above." (it
has to say something: MDA posts a scheduled or queued run's newest assistant text). A new
top-level direct message is its own thread and runs in parallel; only the platform can route it to
the working thread. Upstream asks: [docs/upstream.md](../upstream.md).

## Self-hosted Slack

`design-agent slack` runs a Bolt app in one process with the agent (Socket Mode by default, or
signed HTTP on `/slack/events`): mentions and direct messages start turns, duplicate deliveries
start one, attachments are fetched on the host with the bot token, finals upload to the thread,
and wake-up replies post there. The same middleware draws progress and the footer. Manifest:
`config/slack-manifest.example.yaml`.

## The API and the CLI

The API returns each turn's reply and delivered files, and background news through
`GET /threads/{id}/updates` ([self-hosting](../self-hosting.md)). The CLI prints each step's tool
name as it runs and stays open while background work continues.
