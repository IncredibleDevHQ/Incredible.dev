"""Opt-in checks against the local MinIO test service; remove only randomly owned test keys."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import httpx
import pytest
from dotenv import dotenv_values

from design_agent.config import Settings
from design_agent.surfaces.web.blobs import BlobFiles, s3_client

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_S3_CONFIG"),
    reason="set TEST_S3_CONFIG and TEST_MINIO_ADMIN_CONFIG for real MinIO tests",
)


def remove_test_objects(namespaces: list[str]) -> None:
    storage = Settings(_env_file=os.environ["TEST_S3_CONFIG"])
    admin = dotenv_values(os.environ["TEST_MINIO_ADMIN_CONFIG"])
    from pydantic import SecretStr

    storage = storage.model_copy(
        update={
            "s3_access_key": SecretStr(admin["MINIO_ROOT_USER"]),
            "s3_secret_key": SecretStr(admin["MINIO_ROOT_PASSWORD"]),
        }
    )
    client = s3_client(storage)
    try:
        for namespace in namespaces:
            assert uuid.UUID(namespace).hex == namespace
            prefix = f"accounts/{namespace}/blobs/"
            for page in client.get_paginator("list_object_versions").paginate(
                Bucket=storage.s3_bucket, Prefix=prefix
            ):
                for entry in [*page.get("Versions", []), *page.get("DeleteMarkers", [])]:
                    client.delete_object(
                        Bucket=storage.s3_bucket, Key=entry["Key"], VersionId=entry["VersionId"]
                    )
    finally:
        client.close()


def test_private_objects_ranges_and_reopening(tmp_path: Path) -> None:
    settings = Settings(_env_file=os.environ["TEST_S3_CONFIG"])
    namespace = uuid.uuid4().hex
    blobs = BlobFiles(settings, tmp_path, namespace)
    try:
        blobs.check()
        row = blobs.save("", "clip.mp4", b"0123456789")
        body = blobs.open(row, 2, 5)
        assert body.read() == b"2345"
        body.close()
        anonymous = httpx.get(
            settings.s3_endpoint + "/" + settings.s3_bucket + "/" + row["rel_path"]
        )
        assert anonymous.status_code == 403
        blobs.close()
        blobs = BlobFiles(settings, tmp_path / "new-process", namespace)
        assert blobs.read(row) == b"0123456789"
        assert not list(tmp_path.rglob("clip.mp4"))
        # MinIO filters ListBuckets to accessible buckets rather than rejecting it.
        assert {b["Name"] for b in blobs.client.list_buckets()["Buckets"]} == {settings.s3_bucket}
        with pytest.raises(Exception) as denied:
            blobs.client.get_bucket_policy(Bucket=settings.s3_bucket)
        assert denied.value.response["Error"]["Code"] == "AccessDenied"
    finally:
        blobs.close()
        remove_test_objects([namespace])
