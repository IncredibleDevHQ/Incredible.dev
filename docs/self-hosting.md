# Self-hosting

The same agent, run on a machine you operate: an HTTP API, an optional Slack app, Postgres for
durability, and Docker for the sandbox computers. Docker Compose starts all of it.

## What you need

- A Linux host (or macOS with Docker Desktop) with Docker and Compose v2.24+.
- A model key ([Models](models.md)).
- For Slack: a Slack app you create (Socket Mode needs no public URL).

## Start

```bash
cp .env.example .env
uv run design-agent config set DESIGN_AGENT_MODEL=anthropic:claude-opus-5-5 ANTHROPIC_API_KEY=…
uv run design-agent config generate DESIGN_AGENT_API_TOKENS POSTGRES_PASSWORD
docker compose -f deploy/self-host/compose.yaml up -d --build
curl -s http://127.0.0.1:8080/health
```

Compose builds the sandbox image (`design-agent-sandbox:local`), starts Postgres, and runs the API
on `127.0.0.1:8080`. Put your brand pack in `workspace/brand/` and licensed fonts in
`private-fonts/`; both are mounted read-only.

`DESIGN_AGENT_API_TOKENS` is `token:caller,token:caller`. `config generate` writes one random token
for a caller named `me`; add one per person or service. Show your token with care: it is a
password.

## The API

| Request | Does |
| --- | --- |
| `POST /threads/{id}/messages` `{"text": "…"}` | runs one turn; returns `reply`, the thread's delivered `files`, and `working` (background work running) |
| `POST /threads/{id}/attachments` (multipart `files`) | puts up to 10 files (200 MiB each) in the thread's `/workspace/attachments/`; mention them in the next message |
| `GET /threads/{id}/updates?after=N` | what background work posted since cursor `N` (finished renders, check-ins) |
| `GET /threads/{id}/files/{name}` | downloads a delivered file |
| `GET /health` | liveness |

Every route but `/health` needs `Authorization: Bearer <token>`. A thread belongs to the caller who
started it; anyone else gets 404. A turn can take minutes (a render runs in the turn only when the
agent chose to wait); use a generous client timeout and poll `updates` for background work.

## Slack

Create a Slack app from `config/slack-manifest.example.yaml`, install it, and set
`SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN` (Socket Mode) in `.env`, then:

```bash
docker compose -f deploy/self-host/compose.yaml --profile slack up -d --build
```

The Slack service shares Postgres and the sandbox with the API. Files people attach reach the
thread's sandbox under `/workspace/attachments/`; finals are uploaded to the thread.

## Durability and restarts

- Conversations, the helper ledger, transcripts, check-ins, watches, pipeline memos, observations
  and delivery ledgers live in Postgres (`DATABASE_URL`, set by Compose).
- On start the server sweeps what a restart killed (helpers are reported interrupted on their
  thread's next turn and can be resumed from their saved transcripts) and re-arms check-ins; one
  that came due while it was down fires at once. The sweep repeats every 15 minutes.
- Sandbox containers and their per-thread volumes persist between turns; idle ones are stopped.

## Security

- The agent starts sandbox containers through the host's Docker socket, which is root-equivalent on
  that host. Run the stack on a machine dedicated to it, or use LangSmith sandboxes instead
  (`DESIGN_AGENT_SANDBOX=langsmith`, `DESIGN_AGENT_SANDBOX_SNAPSHOT` from `sandbox publish`) and
  remove the socket mount.
- Sandbox containers run without network, with all capabilities dropped except file ownership,
  no new privileges, and CPU, memory and process limits.
- Keys stay in the agent process; the sandbox never receives credentials.
- The API binds to `127.0.0.1`. Put a TLS-terminating proxy in front of it before exposing it.

## Without Docker Compose

`uv sync --extra self-host --extra slack`, set `DATABASE_URL` (or leave it unset for SQLite files
in `workspace/state/`), build the sandbox image (`uv run design-agent sandbox build`), then run
`uv run design-agent serve` and, for Slack, `uv run design-agent slack`.
