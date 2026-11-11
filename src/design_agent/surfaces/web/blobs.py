"""Private durable blobs; local files remain available for native development and migration."""

from __future__ import annotations

import hashlib
import mimetypes
import re
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, cast
from urllib.parse import urlparse

from design_agent.config import Settings
from design_agent.surfaces.web.store import Store


class StorageUnavailable(OSError):
    def __init__(self) -> None:
        super().__init__("File storage is unavailable")


def byte_range(header: str | None, size: int) -> tuple[int, int]:
    if header is None:
        return 0, size - 1
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", header)
    if not match or size == 0 or not any(match.groups()):
        raise ValueError("Invalid range")
    a, b = match.groups()
    start = int(a) if a else max(0, size - int(b))
    end = min(int(b), size - 1) if a and b else size - 1
    if start >= size or start > end:
        raise ValueError("Unsatisfiable range")
    return start, end


def s3_client(settings: Settings) -> Any:
    import boto3
    from botocore.config import Config

    endpoint = urlparse(settings.s3_endpoint or "")
    if (
        endpoint.scheme not in {"http", "https"}
        or not endpoint.netloc
        or endpoint.username
        or endpoint.password
        or endpoint.path not in {"", "/"}
        or endpoint.query
        or endpoint.fragment
        or not settings.s3_access_key
        or not settings.s3_secret_key
        or not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", settings.s3_bucket)
    ):
        raise ValueError("S3 storage requires an endpoint, private bucket and server credentials")
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        region_name=settings.s3_region,
        aws_access_key_id=settings.s3_access_key.get_secret_value(),
        aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            connect_timeout=5,
            read_timeout=60,
            retries={"mode": "standard", "total_max_attempts": 3},
        ),
    )


class BlobFiles:
    def __init__(
        self, settings: Settings, root: Path, namespace: str, *, client: Any = None
    ) -> None:
        if namespace != "local" and not re.fullmatch(r"[0-9a-f]{32}", namespace):
            raise ValueError("Invalid private blob namespace")
        self.root = root.resolve()
        self.backend = settings.blob_backend
        self.bucket = settings.s3_bucket
        self.prefix = f"accounts/{namespace}/blobs/"
        self.client = (client or s3_client(settings)) if self.backend == "s3" else None

    def check(self) -> None:
        if self.client is not None:
            try:
                self.client.head_bucket(Bucket=self.bucket)
            except Exception:  # noqa: BLE001 - never expose endpoint credentials in errors
                raise StorageUnavailable() from None

    def close(self) -> None:
        if self.client is not None:
            self.client.close()

    def local_path(self, key: str) -> Path:
        if (
            not key
            or "\x00" in key
            or "\\" in key
            or PurePosixPath(key).is_absolute()
            or ".." in PurePosixPath(key).parts
        ):
            raise FileNotFoundError("No such file")
        path = (self.root / key).resolve()
        if self.root not in path.parents:
            raise FileNotFoundError("No such file")
        return path

    def save(self, thread: str, name: str, content: bytes) -> dict[str, Any]:
        clean = re.sub(r"[^a-zA-Z0-9._ -]+", "-", Path(name).name).strip(" .") or "file"
        digest = hashlib.sha256(content).hexdigest()
        mime = mimetypes.guess_type(clean)[0] or "application/octet-stream"
        if self.client is not None:
            key = self.prefix + digest + "/" + clean
            try:
                self.client.put_object(
                    Bucket=self.bucket,
                    Key=key,
                    Body=content,
                    ContentType=mime,
                    Metadata={"sha256": digest},
                )
            except Exception:  # noqa: BLE001 - sanitize SDK/transport errors
                raise StorageUnavailable() from None
        else:
            folder = self.local_path((thread or "uploads") + "/placeholder").parent
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / clean
            stem, suffix, n = target.stem, target.suffix, 1
            while target.exists() and target.read_bytes() != content:
                n += 1
                target = folder / f"{stem}-{n}{suffix}"
            target.write_bytes(content)
            clean, key = target.name, str(target.relative_to(self.root))
        return {
            "name": clean,
            "mime": mime,
            "size": len(content),
            "storage": self.backend,
            "rel_path": key,
            "sha256": digest,
        }

    def open(self, row: Mapping[str, Any], start: int = 0, end: int | None = None) -> BinaryIO:
        key = str(row["rel_path"])
        if row.get("storage", "local") == "local":
            body = self.local_path(key).open("rb")
            body.seek(start)
            return body
        if row.get("storage") != "s3" or self.client is None or not key.startswith(self.prefix):
            raise FileNotFoundError("No such file")
        if ".." in PurePosixPath(key).parts or "\x00" in key or "\\" in key:
            raise FileNotFoundError("No such file")
        try:
            args: dict[str, Any] = {"Bucket": self.bucket, "Key": key}
            if start or end is not None:
                args["Range"] = f"bytes={start}-{end if end is not None else int(row['size']) - 1}"
            return cast(BinaryIO, self.client.get_object(**args)["Body"])
        except Exception as error:  # noqa: BLE001 - sanitize SDK/transport errors
            code = getattr(error, "response", {}).get("Error", {}).get("Code")
            if code in {"NoSuchKey", "404"} or isinstance(error, KeyError):
                raise FileNotFoundError("No such file") from None
            raise StorageUnavailable() from None

    def read(self, row: Mapping[str, Any], limit: int | None = None) -> bytes:
        with self.open(row) as body:
            return body.read() if limit is None else body.read(limit)

    def migrate(self, store: Store) -> int:
        if self.client is None:
            return 0
        count = 0
        for row in store.local_files():
            content = self.read(row)
            if len(content) != row["size"] or hashlib.sha256(content).hexdigest() != row["sha256"]:
                raise StorageUnavailable()
            saved = self.save(row["thread_id"], row["name"], content)
            # Verify the remote bytes before changing the pointer. Retain the original copy.
            if hashlib.sha256(self.read(saved)).hexdigest() != row["sha256"]:
                raise StorageUnavailable()
            store.relocate_file(row["id"], saved["rel_path"])
            count += 1
        return count
