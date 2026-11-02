---
name: design-agent-deploy
description: Put Design Agent in a team's Slack. Deploy it to Managed Deep Agents (one command, managed Slack app) or self-host it with Docker Compose, verify it with a real request, ship updates, and keep a separate test copy. Use when someone wants the agent running for their team.
---

# Deploy Design Agent

A deployment is what the team uses. Ask before `mda deploy`, before connecting Slack, and before
anything that bills (publishing a snapshot, hosting). Never print a key; name missing settings.
Setup comes first: `uv run design-agent doctor` should pass and the brand pack should validate
(`design-agent-onboarding`, `brand-onboarding`).

| | Managed Deep Agents (recommended) | Self-hosted |
| --- | --- | --- |
| Who runs it | LangSmith: runtime, sandboxes, Slack app, schedules | the person: API, Postgres, Docker host |
| Needs | a LangSmith Cloud account (MDA is in public beta) and a deployment-capable `LANGSMITH_API_KEY` | Docker with Compose v2.24+ |
| Cost | hosting is paid, plus model and media spend | their machine, plus model and media spend |

## Managed Deep Agents

1. **Publish the computer once.** `uv run design-agent sandbox build && uv run design-agent sandbox test`
   proves the recipe locally; `uv run design-agent sandbox publish --fs-gib 16` builds the snapshot
   in their workspace (sandbox time is billed). Publish again whenever `sandbox/setup.sh` changes.
2. **Check the keys.** `mda deploy` forwards every `.env` key except LangSmith's as a deployment
   secret. List the key *names* in `.env` and confirm they are only what the deployed agent uses
   (model, media, `DESIGN_AGENT_*`, `PAPER_*`); self-hosting keys (`SLACK_*`, `DATABASE_URL`,
   `DESIGN_AGENT_API_TOKENS`) must not be there. Renders in `workspace/out/` ship too and count
   toward MDA's 200 MB archive limit. `uv run design-agent doctor` names all of this
   (`mda-deploy`), and `uv run mda build` compiles what would ship into `.mda/build/`.
3. **Try a copy first.** `uv run mda deploy --name design-agent-test` is a separate deployment; the
   team's agent is untouched.
4. **Deploy** with `uv run mda deploy` after a yes. The first deploy provisions the Slack app; the
   person authorizes it in their Slack workspace. Without a `LANGSMITH_API_KEY`, `mda deploy`
   offers a browser sign-in.
5. **Verify with real requests:** a quick still, then a short storyboarded teaser. In Slack you
   should see live progress, a check-in while it renders, and files attached at the end. Without
   Slack, call the deployment's API ([docs/deploy-mda.md](../../../docs/deploy-mda.md) has the
   snippet); files attach to the run's LangSmith trace. `uv run mda logs` tails the deployment.
6. **Updates:** change, deploy the test copy, then `uv run mda deploy`. A redeploy stops running
   helpers; each affected thread offers to resume from its saved transcript.

## Self-hosted

1. `uv run design-agent config set DESIGN_AGENT_MODEL=…` (the person types the key or sets it in
   `.env`), then `uv run design-agent config generate DESIGN_AGENT_API_TOKENS POSTGRES_PASSWORD`.
2. `docker compose -f deploy/self-host/compose.yaml up -d --build`, then
   `curl -s http://127.0.0.1:8080/health`.
3. **Slack (optional):** create an app from `config/slack-manifest.example.yaml`, set
   `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN`, then add `--profile slack` to the compose command.
4. **Verify:** `POST /threads/{id}/messages` with `Authorization: Bearer <token>`, then poll
   `GET /threads/{id}/updates` for background work.
5. **Security:** the API starts sandboxes through the Docker socket, which is root-equivalent. Use a
   dedicated host, or LangSmith sandboxes (`DESIGN_AGENT_SANDBOX=langsmith`) without the socket.

A local preflight does not prove a deployment: only a real request does. Details:
[Deploy with MDA](../../../docs/deploy-mda.md), [Self-hosting](../../../docs/self-hosting.md).
