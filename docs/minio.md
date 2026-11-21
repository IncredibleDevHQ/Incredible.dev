# Private S3 files with MinIO

Root Compose stores attachments, source documents, generated deliverables, board images, and
Episode Studio media in MinIO. Episode media includes original chapter recordings, converted
video and audio, previews, and rendered films. Supabase PostgreSQL keeps file IDs, names, sizes, hashes and object
locations. Browser download URLs stay `/api/files/<id>`: the backend verifies the Supabase
session and looks up the file in that account's private schema before accessing S3. No storage
credential or public bucket URL is sent to the browser.

## Railway

The Railway configuration runs the same MinIO image as a private service with a dedicated persistent volume. At startup it provisions the bucket and application policy before accepting traffic from the web service. See the [Railway setup](railway.md) for variables, deployment order and backups.

## Run locally

After configuring [Supabase](supabase.md), run:

```bash
uv run python scripts/setup_minio.py
docker compose up -d --build --wait
```

The setup script creates Git-ignored, mode-600 `.env.minio` (administrator credentials) and
`.env.storage` (application credentials). It retains existing complete configurations and
refuses to overwrite an incomplete pair. Keep both files backed up securely. The app receives
only `.env.storage`; the one-shot initializer uses administrator credentials to create the
private `incredible-files` bucket and a separate user allowed to read/write `accounts/*`.
Anonymous access is disabled and bucket versioning is enabled. The application cannot list
other buckets, administer MinIO, change policies or delete object versions.

The S3 endpoint is `http://127.0.0.1:19000`; the console is
`http://127.0.0.1:19001`. The console's administrator credentials are in `.env.minio`.
Inside Compose the backend uses `http://minio:9000`. All published ports bind to localhost.
The first build compiles the official server and client from pinned commits, including the
server's October 2025 security release. Their license texts are included in the image.
MinIO's community repository is archived; this local setup does not provide ongoing upstream
security maintenance. See the [official release](https://github.com/minio/minio/releases/tag/RELEASE.2025-10-15T17-29-55Z).

## Files and migration

Object keys are `accounts/<verified-user-uuid>/blobs/<sha256>/<filename>`. Different contents
never overwrite the same key. Every download checks the account namespace as well as the
database record. Downloads stream through the backend and support single byte ranges for media.
Original chapter recordings stream to `accounts/<verified-user-uuid>/blobs/recordings/`
under the take ID. The take and its playback files are registered in PostgreSQL. A storage
failure returns 503 and leaves the previous take selected. Temporary FFmpeg files are cleaned up
after the conversion. Chat messages and replies stay in PostgreSQL and can be reopened from a
fresh application workspace.

When an existing account is first opened after enabling S3, its registered local files are
uploaded and read back to verify the hash before their metadata pointers change. Migration is
repeatable; failures leave the original pointer intact. Original local files remain as backup
copies. Unclaimed legacy SQLite workspaces are not migrated or assigned to anyone.

## Editable brand packs

With S3 storage enabled, each saved brand is a complete, immutable `brand-pack.zip` in
MinIO. The object key is `accounts/<owner-uuid-without-hyphens>/blobs/<sha256>/brand-pack.zip`.
The workspace's `brand_packs` table in Supabase has one row per brand. Its `slug` identifies
the brand and its `version` is the digest of the current archive. Channel selections refer
to the slug, so the next render picks up a saved edit.

On first opening a workspace, the backend imports its existing default pack and named packs
from its legacy brand folders. It uploads each archive, reads it back, verifies its digest,
then sets the database pointer. Reopening the workspace retries unfinished imports. Original
folders remain available as backups. After import, the app reads the MinIO revision and uses
temporary files to view, edit or stage it. New packs captured from websites follow the same
save path. The bundled Example Studio pack ships with the app; its first edit creates a
workspace-owned revision.

To edit via the authenticated API, fetch `GET /api/brands/<slug>`, then send
`PATCH /api/brands/<slug>` with that version and the full text of each file you want to
replace. Supported files are `voice.md`, `graphic-language.md` and `tokens.json`.
For example, a first edit to the bundled default uses:

```json
{"version": null, "files": {"voice.md": "Use a warm, direct voice."}}
```

A successful edit returns the new version. A stale version returns HTTP 409; reopen the
brand before reapplying the edit. A failed upload or verification leaves the current version
intact. Back up both the MinIO volume and Supabase to restore editable brands.

The agent still uses disk for sandbox working files, renders, operator-provided fonts and
runtime configuration. Standalone filesystem setups continue to use local brand folders.

MinIO's bytes live in the Docker volume `incredible-local_minio-data`. They survive container
recreation, but remain on this machine. Back up that volume, Supabase and any working data you
need. Do not run `docker compose down -v` unless intentionally deleting the storage volume.

## Verify

Run the unit/regression suite normally. Set `TEST_S3_CONFIG` to the protected application env
file and `TEST_MINIO_ADMIN_CONFIG` to the administrator env file to opt into real MinIO tests.
With `TEST_DATABASE_URL` set too, the private-workspace integration test exercises Supabase and
MinIO together, including cross-account denial and generated-file downloads. Tests remove only
their own randomly named schemas and object prefixes. Paid model calls are not required.
