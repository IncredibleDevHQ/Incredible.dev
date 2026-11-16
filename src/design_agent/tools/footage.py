"""Raw footage in a bucket: S3 in production, MinIO or another S3-compatible store in development.

A take is cut to the film's format and the film uses the cut. The recording as it arrived (a
browser's take, a camera's own file, a voice alone) is the footage itself. With a bucket
configured it is kept there under its take's name, so a film can be cut again from what was
shot and a server's disk is not where footage lives.

This runs on the host with the host's credentials; the sandbox holds no key and never reaches
the bucket. On AWS the credentials are the machine's own (its role, or the usual AWS files), so
none are set here. A development store takes an endpoint and a key pair. Nothing is ever
deleted from the bucket by this code: how long footage is kept is the bucket's own rule.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from typing import IO, Any

from design_agent.config import Settings

#: The type a recording is stored under, by its file's ending.
TYPES = {
    "mp4": "video/mp4",
    "mov": "video/quicktime",
    "mkv": "video/x-matroska",
    "webm": "video/webm",
    "mxf": "application/mxf",
    "m4a": "audio/mp4",
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "ogg": "audio/ogg",
    "flac": "audio/flac",
}


class FootageError(Exception):
    """The bucket did not take a recording. The message is safe to show: it holds no key."""


def _sdk() -> tuple[Any, type[Exception], tuple[type[Exception], ...]]:
    """boto3, the error a refused request raises, and every error a transfer can end in."""
    try:
        import boto3
        from boto3.exceptions import Boto3Error
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError:
        raise FootageError(
            "keeping footage needs boto3: install the s3 extra (uv sync --extra s3)"
        ) from None
    return boto3, ClientError, (ClientError, BotoCoreError, Boto3Error, OSError)


@dataclass(frozen=True)
class Bucket:
    """Where footage is kept, and what opens it."""

    name: str
    endpoint: str | None = None
    region: str | None = None
    key_id: str | None = None
    secret: str | None = None
    token: str | None = None

    @classmethod
    def from_settings(cls, settings: Settings) -> Bucket | None:
        """The configured bucket, or None when footage is not kept."""
        if not settings.footage_bucket.strip():
            return None

        def secret(value: Any) -> str | None:
            return (value.get_secret_value() or None) if value is not None else None

        return cls(
            name=settings.footage_bucket.strip(),
            endpoint=settings.s3_endpoint,
            region=settings.s3_region,
            key_id=secret(settings.aws_access_key_id),
            secret=secret(settings.aws_secret_access_key),
            token=secret(settings.aws_session_token),
        )

    def _client(self, boto3: Any) -> Any:
        from botocore.config import Config

        # A person waits on the take while this runs: a store that does not answer is given
        # up on in seconds, not minutes.
        options: dict[str, Any] = {
            "retries": {"max_attempts": 3, "mode": "standard"},
            "connect_timeout": 10,
            "read_timeout": 60,
        }
        if self.endpoint:
            # MinIO and its kind answer at one address, with the bucket in the path.
            options["s3"] = {"addressing_style": "path"}
        return boto3.client(
            "s3",
            endpoint_url=self.endpoint,
            # a store of one's own signs for any region; S3's own default is the same
            region_name=self.region or ("us-east-1" if self.endpoint else None),
            aws_access_key_id=self.key_id,
            aws_secret_access_key=self.secret,
            aws_session_token=self.token,
            config=Config(**options),
        )

    def put(self, key: str, source: IO[bytes], *, name: str = "") -> str:
        """Keep one recording, read from an open file from its start, and say where it is
        (`s3://bucket/key`). It is sent in parts, so its size is never held in memory. `name`
        is the file's own name, kept with it."""
        boto3, refused, errors = _sdk()
        extra: dict[str, Any] = {
            "ContentType": TYPES.get(
                posixpath.splitext(key)[1].lstrip(".").lower(), "application/octet-stream"
            )
        }
        label = re.sub(r"[^A-Za-z0-9._ -]", "_", posixpath.basename(name)).strip()[:200]
        if label:
            extra["Metadata"] = {"name": label}
        try:
            client = self._client(boto3)
            if self.endpoint:
                # A development store starts empty. On AWS a bucket is made on purpose, by
                # whoever owns the account, and is never made here.
                try:
                    client.head_bucket(Bucket=self.name)
                except refused as error:
                    if _code(error) not in ("404", "NoSuchBucket", "NotFound"):
                        raise
                    client.create_bucket(Bucket=self.name)
            source.seek(0)
            client.upload_fileobj(source, self.name, key, ExtraArgs=extra)
        except errors as error:
            raise FootageError(_reason(error)) from None
        return f"s3://{self.name}/{key}"


def _code(error: Exception) -> str:
    response = getattr(error, "response", None)
    return str((response or {}).get("Error", {}).get("Code") or "")


def _reason(error: Exception) -> str:
    """What went wrong, in the store's own words where it gave any. Never a credential: boto's
    errors name the operation, the address and the store's reply."""
    said = " ".join(str(error).split())[:240]
    return f"{type(error).__name__}: {said}" if said else type(error).__name__
