# Run the full app with Docker Compose

The root `compose.yaml` builds React and serves its production assets and FastAPI backend in
one `app` container at <http://127.0.0.1:8765>. It uses Supabase Auth and PostgreSQL; see
[Supabase setup](supabase.md) for Google/email login, private workspaces and database credentials.
The separate [self-hosted API stack](self-hosting.md) serves the token-authenticated API.

## Start

Use Docker with Compose v2.24+ (Docker Desktop, OrbStack or a local Linux daemon). From the
repository root:

```bash
# Preserve existing environment files. Fill .env.supabase using docs/supabase.md.
test -f .env.supabase || cp .env.example .env.supabase
mkdir -p private-fonts
# Set LOCAL_UID and LOCAL_GID in .env to your host's id -u and id -g.
# DOCKER_GID is the socket's group (usually 0 on Docker Desktop/OrbStack).
# For a nonstandard socket, set DOCKER_SOCKET_PATH in .env to the path reported by:
docker context inspect --format '{{.Endpoints.docker.Host}}'

docker compose up -d --build --wait
docker compose ps
```

The `sandbox` service builds the rendering image and exits successfully. The app starts its
own isolated sandbox containers for tasks. There is no local Postgres or SQLite service.
Stop a native app on port 8765 before starting Compose. Changing `.env.supabase` requires
`docker compose up -d --force-recreate app`; a plain restart does not reload environment values.

The app runs as `LOCAL_UID:LOCAL_GID` (defaults 1000:1000); match your host IDs so existing
workspace files stay writable. Do not make the workspace world-writable to fix permissions.
The image excludes keys, private config, local databases and uploads from its build context.

## Data and restarts

The host's entire `workspace/` is mounted at `/app/workspace`. New accounts use their own
`workspace/accounts/<uuid>/` folders; the legacy SQLite data remains untouched and inaccessible
to those accounts. Back up uploaded/generated files on disk as well as Supabase Postgres.
`private-fonts/` is mounted read-only. Rendering sandbox workspace volumes persist separately.

```bash
docker compose logs --tail=100 app
docker compose stop
docker compose up -d --wait
```

`docker compose down` removes app containers, not the host workspace or per-thread sandbox
volumes. Do not prune sandbox volumes if you need to resume their tasks.

## Verification and limitations

`/healthz` checks that startup completed; `/api/session` requires a valid Supabase session.
`docker compose exec app design-agent doctor` checks model and sandbox configuration without a
provider call. The automated scripted render tests use the actual sandbox without billing a
model. Do not run the legacy native CLI demo with the authenticated production environment:
it is a separate developer workflow and does not select a private user schema.

The published port binds only to localhost. The app has Docker-daemon access to start
sandboxes, while sandboxes receive neither the socket nor provider keys. Repository research
is disabled for private accounts. Editable HyperFrames Studio links use extra loopback ports
that this stack does not publish; storyboard review, file previews, video playback and downloads
use the main app port.
