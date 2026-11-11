"""Create local MinIO credentials once, outside Git and Docker images."""

from __future__ import annotations

import os
import secrets
from pathlib import Path


def setup(root: Path) -> None:
    admin, app = root / ".env.minio", root / ".env.storage"
    if admin.exists() and app.exists():
        print("Existing MinIO configuration retained.")
        return
    if admin.exists() or app.exists():
        raise SystemExit(
            "Only one MinIO configuration file exists; restore the matching file before continuing."
        )
    values = {
        admin: "MINIO_ROOT_USER=incredible-root\nMINIO_ROOT_PASSWORD="
        + secrets.token_urlsafe(48)
        + "\n",
        app: "DESIGN_AGENT_BLOB_BACKEND=s3\nDESIGN_AGENT_S3_ENDPOINT=http://127.0.0.1:19000\n"
        "DESIGN_AGENT_S3_BUCKET=incredible-files\nDESIGN_AGENT_S3_REGION=us-east-1\n"
        "DESIGN_AGENT_S3_ACCESS_KEY=incredible-app-"
        + secrets.token_hex(8)
        + "\nDESIGN_AGENT_S3_SECRET_KEY="
        + secrets.token_urlsafe(48)
        + "\n",
    }
    for path, value in values.items():
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as output:
            output.write(value)
    print("Created protected .env.minio and .env.storage files. Credentials were not printed.")


if __name__ == "__main__":
    setup(Path(__file__).resolve().parents[1])
