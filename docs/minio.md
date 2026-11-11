# Private S3 files with MinIO

Root Compose stores uploaded attachments, linked source documents, generated deliverables and
board/proof images in MinIO. Supabase PostgreSQL keeps file IDs, names, sizes, hashes and object
locations. Browser download URLs stay `/api/files/<id>`: the backend verifies the Supabase
session and looks up the file in that account's private schema before accessing S3. No storage
credential or public bucket URL is sent to the browser.

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
Storage failures return 503 without silently writing a new local copy.

When an existing account is first opened after enabling S3, its registered local files are
uploaded and read back to verify the hash before their metadata pointers change. Migration is
repeatable; failures leave the original pointer intact. Original local files remain as backup
copies. Unclaimed legacy SQLite workspaces are not migrated or assigned to anyone.

The agent still uses local sandbox disks for working/render files, and local folders for
editable brand packs, fonts and runtime configuration. Delivered assets and attachments are
durable in S3; this is not a remote filesystem for the agent's whole computer.

MinIO's bytes live in the Docker volume `incredible-local_minio-data`. They survive container
recreation, but remain on this machine. Back up that volume, Supabase and any working data you
need. Do not run `docker compose down -v` unless intentionally deleting the storage volume.

## Verify

Run the unit/regression suite normally. Set `TEST_S3_CONFIG` to the protected application env
file and `TEST_MINIO_ADMIN_CONFIG` to the administrator env file to opt into real MinIO tests.
With `TEST_DATABASE_URL` set too, the private-workspace integration test exercises Supabase and
MinIO together, including cross-account denial and generated-file downloads. Tests remove only
their own randomly named schemas and object prefixes. Paid model calls are not required.
