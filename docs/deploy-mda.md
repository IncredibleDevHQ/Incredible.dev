# Deploy with Managed Deep Agents

Managed Deep Agents (MDA) runs the agent, a sandbox computer for every thread, its Slack app and
its schedules in your LangSmith workspace, with tracing built in. This repository is an MDA project,
so `mda deploy` deploys it as it is:

```bash
git clone https://github.com/langchain-ai/design-agent.git && cd design-agent
uv run design-agent config set LANGSMITH_API_KEY=lsv2_… ANTHROPIC_API_KEY=sk-ant-…
uv run design-agent sandbox publish
uv run mda deploy
```

`uv run` uses the `mda` CLI pinned in `uv.lock`, so the CLI matches the SDK the agent is built on.

## What you need

- A LangSmith Cloud account (Managed Deep Agents is in public beta) and an API key with deployment permission
  (`LANGSMITH_API_KEY`; region via `LANGSMITH_ENDPOINT`). [Hosting is paid](https://www.langchain.com/pricing).
- A model key for your configured model ([Models](models.md)).
- [uv](https://docs.astral.sh/uv/). Docker only if you want to test the sandbox recipe locally first.

## 1. Publish the computer once

Each thread gets its own sandbox cloned from a snapshot of the recipe in `sandbox/setup.sh`
(Chrome, ffmpeg, HyperFrames, D2, sharp, ECharts, fonts). The computer is about 1.3 GiB, more than
the 1 GiB filesystem MDA gives a sandbox baked from a Docker image, so publish it as a snapshot with
room for renders:

```bash
uv run design-agent sandbox publish --fs-gib 16
```

`publish` builds the snapshot in your workspace (sandbox time is billed), runs the recipe's probe
in it, and rewrites `sandbox/__init__.py` to declare it. Publish again whenever the recipe changes;
the snapshot name follows the recipe's hash. To prove the recipe locally first:
`uv run design-agent sandbox build && uv run design-agent sandbox test`. Sizes and egress for MDA
sandboxes are the constants in `sandbox/__init__.py` (MDA reads that file statically). Egress is
default-deny: the agent's host tools fetch and generate, the sandbox only renders.

## 2. Keys

`mda deploy` forwards every key in `.env` as a deployment secret, except LangSmith's own
(`LANGSMITH_API_KEY` signs the deploy and stays home). It never reads keys from your shell for
the deployment. So keep `.env` to what the deployed agent uses: the model key, and optionally
`OPENAI_API_KEY` (images, unless you use the LangSmith Gateway), `ELEVENLABS_API_KEY` (voice and music), `DESIGN_AGENT_*` and `PAPER_*`
settings. Self-hosting keys (`SLACK_*`, `DATABASE_URL`, `DESIGN_AGENT_API_TOKENS`) don't belong in
the `.env` you deploy from.

## 3. Deploy

```bash
uv run mda deploy
```

MDA compiles the project, syncs `instructions.md` and `skills/` to Context Hub, uploads the source,
bakes the sandbox recipe on your snapshot and waits until the deployment is live. On the first
deploy it provisions the Slack app; authorize it in your Slack workspace when prompted. Channels
require `identity.py` (LangSmith API-key authentication by default; see MDA's identity docs for
per-person identities).

What ships is the project directory without `.env` and virtualenvs: code, `instructions.md`,
`skills/` (Context Hub takes only UTF-8 text, so skills' binary files live in `skill-binaries/` and
reach the sandbox through the workspace stager), your Git-ignored `workspace/brand/` and
`private-fonts/` (licensed fonts reach the sandbox as deployment files, never through Git), the
sandbox recipe and the MDA declarations. Git-ignored renders in `workspace/out/` ship too and count
toward MDA's 200 MB archive limit, so clear old ones before deploying.

To try a change without touching the deployment people use, deploy a separate copy:
`uv run mda deploy --name design-agent-test`.

**Before you deploy,** `uv run design-agent doctor` names what would make `mda deploy` fail or ship
the wrong thing (`mda-deploy` and `mda-project`): the unpublished sandbox, a binary file under
`skills/`, self-hosting keys in `.env`, a large `workspace/out/`. `uv run mda build` compiles what
would ship into `.mda/build/` without deploying. Without a `LANGSMITH_API_KEY` in `.env`, `mda deploy`
offers a browser sign-in; `sandbox publish` needs the key.

## 4. Verify

In Slack, mention the agent with a quick ask ("a square card announcing …"), then a short
storyboarded teaser. You should see live progress in the thread, the files attached at the end,
and, for the teaser, a check-in while it renders. `uv run mda logs` tails the deployment.

Without Slack, call the deployment's Agent Server (the URL `mda deploy` prints) with your LangSmith key:

```python
from langgraph_sdk import get_client

client = get_client(url="https://<deployment>.langgraph.app", api_key="<LANGSMITH_API_KEY>")
thread = await client.threads.create()
await client.runs.wait(
    thread["thread_id"],
    "design-agent",
    input={"messages": [{"role": "user", "content": "A 1200x630 card announcing …"}]},
)
```

Runs without a channel (the API, Studio) have no Slack to attach files to, so `upload_files`
attaches them to the run's trace in LangSmith; open them from the trace or Studio.

Background work reports back only where MDA can schedule a wake-up on the thread: in Slack (the
channel) or for a signed-in person. A thread started with an API key has neither, since MDA does not
count an API key as a person, so helpers, render watchers and check-ins finish their work but the
agent is never woken to deliver it. Use Slack for jobs that run in the background (films, parallel
looks, long decks), or keep API requests to work that finishes in one turn.

## How it behaves on MDA

In Slack the agent streams its steps into one message per turn, ends replies with a short footer
(agents running, time, estimated cost; a trace link with `DESIGN_AGENT_TRACE_HOST`), and takes
follow-ups while a job runs ([surfaces](architecture/surfaces.md)).

- **Background work.** Helpers run inside the deployment process; the lead is woken with a
  one-time schedule on its own thread, which lands 60–120 s after the event (MDA rounds a
  schedule to the next minute). See [orchestration](architecture/orchestration.md).
- **Restarts.** A redeploy stops running helpers. Each thread with background work keeps a
  sentinel schedule 15 minutes ahead that the running process keeps pushing back; after a restart
  it fires, and the agent tells the thread what stopped and offers to resume it from its saved
  transcript.
- **Quiet check-ins.** MDA posts every scheduled run's reply, so a check-in with nothing new posts
  one status line ("Still working: act 2 (12 min).") rather than nothing.
- **Housekeeping.** `schedules/housekeeping.py` runs every 15 minutes, sweeps what a restart killed
  and tidies expired schedules, with no model call.
- **Memory.** `memory.py` turns on two layers. `/memories/agent/` is the team's: anyone who
  mentions the agent can add a rule to it, so it never holds private data. `/memories/user/`
  belongs to the person asking and follows them anywhere in Slack; MDA mounts it only when a
  verified person is behind the run. Each layer's `AGENTS.md` loads on every turn. To keep personal
  memory to DMs (MDA's default), drop the `allow` policy; to turn memory off, delete the file.
- **MCP servers** come from `config/mcp.toml` through `tools/mcp.py`. A server that needs
  credentials names an agent-owned workspace connection (`connection = "slug"`); header values are
  never compiled into the deployment.
- **Studio.** `uv run mda dev` runs the project locally in LangSmith Studio.

## Upstream asks

- A public "start a run on this thread now" API, to wake the lead in seconds instead of 60–120 s.
- A way for a scheduled run to end without posting.
- Async subagents that share the lead's sandbox, to replace the in-process helper runner.
