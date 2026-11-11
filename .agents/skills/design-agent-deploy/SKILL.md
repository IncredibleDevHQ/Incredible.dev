---
name: design-agent-deploy
description: Run Design Agent for a team, self-hosted with Docker Compose (the HTTP API, Postgres and the sandbox), verify it with a real request, and ship updates. Use when someone wants the agent running for their team.
---

# Deploy Design Agent

A deployment is what the team uses. Ask before anything that bills (hosting, model and media
spend). Never print a key; name missing settings. Setup comes first: `uv run design-agent doctor`
should pass and the brand pack should validate (`design-agent-onboarding`, `brand-onboarding`).

This fork runs self-hosted, behind its own web UI. It needs Docker with Compose v2.24+.

For the browser app, follow [local Compose](../../../docs/local-compose.md) and
[Supabase](../../../docs/supabase.md), using the root `compose.yaml`. It builds React and the
web backend together, requires Supabase Auth/Postgres, and mounts the existing workspace.
Keep keys in `.env.supabase`; never put a service-role key or database credential in frontend
code. Set host UID/GID/socket settings in `.env`. New accounts start private and empty; do not
claim or import legacy SQLite data without an explicit owner decision. Verify unauthenticated
401 responses, cross-user resource denial, private agent memory/events/files, Google PKCE and
email confirmation. Run real Postgres integration and scripted render tests before replacing
the local app. Google provider credentials and email delivery must be configured in Supabase;
never silently disable confirmation or authentication to work around missing configuration.
A lost idle connection should recover on the next checkout. Verify recovery in the private
workspace integration tests and check the signed-in Settings usage summary after a rollout.
The Postgres/token API below is a different deployment surface.

Root Compose also requires private MinIO storage: run `uv run python scripts/setup_minio.py`
before the first build. Follow [MinIO](../../../docs/minio.md); keep administrator credentials
out of the app environment and sandbox. Verify private bucket access, authenticated uploads and
downloads, range requests, migration checksums, and cross-account file denial against real
MinIO. Preserve the named data volume, legacy data and local migration backup copies.

1. `uv run design-agent config set DESIGN_AGENT_MODEL=…` (the person types the key or sets it in
   `.env`), then `uv run design-agent config generate DESIGN_AGENT_API_TOKENS POSTGRES_PASSWORD`.
2. `docker compose -f deploy/self-host/compose.yaml up -d --build`, then
   `curl -s http://127.0.0.1:8080/health`.
3. **Verify with real requests:** a quick still, then a short storyboarded teaser.
   `POST /threads/{id}/messages` with `Authorization: Bearer <token>`, then poll
   `GET /threads/{id}/updates` for background work; finals download from
   `GET /threads/{id}/files/{name}`.
4. **Updates:** pull the change, run the compose command again, and verify with a real request. A
   restart stops running helpers; each affected thread hears of it and can resume them from their
   saved transcripts.
5. **Security:** the API starts sandboxes through the Docker socket, which is root-equivalent. Use a
   dedicated host.

A local preflight does not prove a deployment: only a real request does. Details:
[Self-hosting](../../../docs/self-hosting.md).
