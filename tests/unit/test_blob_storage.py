from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest

from design_agent.config import Settings
from design_agent.surfaces.web.blobs import BlobFiles, StorageUnavailable, byte_range
from design_agent.surfaces.web.store import Store


def test_s3_upload_download_ranges_and_failure_responses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi.testclient import TestClient

    from design_agent.surfaces.web import blobs
    from design_agent.surfaces.web.app import create_app

    s3 = S3()
    monkeypatch.setattr(blobs, "s3_client", lambda _: s3)
    settings = configured().model_copy(update={"workspace_root": tmp_path / "workspace"})
    app = create_app(tmp_path, settings, demo=True)
    client = TestClient(app)
    uploaded = client.post(
        "/api/uploads", files={"files": ("video.mp4", b"0123456789", "video/mp4")}
    )
    assert uploaded.status_code == 200
    item = uploaded.json()[0]
    assert "rel_path" not in item and "storage" not in item
    assert client.get(item["url"]).content == b"0123456789"
    part = client.get(item["url"], headers={"Range": "bytes=2-5"})
    assert part.status_code == 206 and part.content == b"2345"
    assert part.headers["content-range"] == "bytes 2-5/10"
    assert client.get(item["url"], headers={"Range": "bytes=10-"}).status_code == 416
    assert client.get("/api/files/unknown").status_code == 404
    before = len(app.state.host.store.files(""))
    s3.fail = True
    failed = client.post("/api/uploads", files={"files": ("failed.txt", b"secret")})
    assert failed.status_code == 503
    assert "credentials" not in failed.text
    assert len(app.state.host.store.files("")) == before
    assert client.get(item["url"]).status_code == 503
    app.state.host.store.close()


class S3:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.fail = False
        self.closed = False

    def put_object(self, **args: Any) -> None:
        if self.fail:
            raise OSError("secret endpoint credentials")
        self.objects[args["Key"]] = args["Body"]

    def get_object(self, **args: Any) -> dict[str, Any]:
        if self.fail:
            raise OSError("secret endpoint credentials")
        data = self.objects[args["Key"]]
        if "Range" in args:
            start, end = map(int, args["Range"][6:].split("-"))
            data = data[start : end + 1]
        return {"Body": io.BytesIO(data)}

    def close(self) -> None:
        self.closed = True


def configured() -> Settings:
    return Settings(
        _env_file=None,
        blob_backend="s3",
        s3_endpoint="http://minio:9000",
        s3_access_key="test-key",
        s3_secret_key="test-secret",
    )


def test_objects_have_private_immutable_keys_and_do_not_write_local_copies(tmp_path: Path) -> None:
    client = S3()
    a = BlobFiles(configured(), tmp_path / "a", "a" * 32, client=client)
    b = BlobFiles(configured(), tmp_path / "b", "b" * 32, client=client)
    first = a.save("", "clip.mp4", b"first")
    second = a.save("", "clip.mp4", b"second")
    other = b.save("", "clip.mp4", b"first")
    assert first["rel_path"] != second["rel_path"]
    assert first["rel_path"] != other["rel_path"]
    assert a.read(first) == b"first"
    with pytest.raises(FileNotFoundError):
        b.read(first)
    assert not list(tmp_path.rglob("clip.mp4"))
    body = a.open(first, 1, 3)
    assert body.read() == b"irs"
    body.close()


@pytest.mark.parametrize(
    "path", ["../secret", "/secret", "uploads/../../secret", "uploads/evil\\path", "uploads/\x00"]
)
def test_local_paths_cannot_escape(tmp_path: Path, path: str) -> None:
    blobs = BlobFiles(Settings(_env_file=None), tmp_path, "local")
    with pytest.raises(FileNotFoundError):
        blobs.read({"storage": "local", "rel_path": path})


def test_failed_upload_never_falls_back_to_disk_or_leaks_credentials(tmp_path: Path) -> None:
    client = S3()
    client.fail = True
    blobs = BlobFiles(configured(), tmp_path, "a" * 32, client=client)
    with pytest.raises(StorageUnavailable, match="^File storage is unavailable$"):
        blobs.save("", "clip.mp4", b"private")
    assert not list(tmp_path.rglob("clip.mp4"))


def test_migration_uploads_before_switching_metadata_and_is_repeatable(tmp_path: Path) -> None:
    store = Store(tmp_path / "db.sqlite")
    local = BlobFiles(Settings(_env_file=None), tmp_path / "files", "local")
    row = store.add_file(
        {
            "thread_id": "",
            "origin": "upload",
            "author_id": "you",
            **local.save("", "note.txt", b"kept"),
        }
    )
    client = S3()
    remote = BlobFiles(configured(), tmp_path / "files", "a" * 32, client=client)
    client.fail = True
    with pytest.raises(StorageUnavailable):
        remote.migrate(store)
    assert store.file(row["id"])["storage"] == "local"
    client.fail = False
    assert remote.migrate(store) == 1
    assert remote.migrate(store) == 0
    kept = store.file(row["id"])
    assert kept["storage"] == "s3"
    assert remote.read(kept) == b"kept"
    assert (tmp_path / "files" / row["rel_path"]).read_bytes() == b"kept"
    store.close()


def test_corrupt_remote_copy_never_replaces_local_metadata(tmp_path: Path) -> None:
    store = Store(tmp_path / "db.sqlite")
    local = BlobFiles(Settings(_env_file=None), tmp_path / "files", "local")
    row = store.add_file(
        {
            "thread_id": "",
            "origin": "upload",
            "author_id": "you",
            **local.save("", "note.txt", b"kept"),
        }
    )

    class CorruptS3(S3):
        def get_object(self, **args: Any) -> dict[str, Any]:
            return {"Body": io.BytesIO(b"corrupted")}

    remote = BlobFiles(configured(), tmp_path / "files", "a" * 32, client=CorruptS3())
    with pytest.raises(StorageUnavailable):
        remote.migrate(store)
    assert store.file(row["id"])["storage"] == "local"
    assert local.read(store.file(row["id"])) == b"kept"
    store.close()


@pytest.mark.parametrize(
    "endpoint",
    [
        "",
        "ftp://minio:9000",
        "http://user:password@minio:9000",
        "http://minio:9000/path",
        "http://minio:9000?secret=x",
    ],
)
def test_invalid_storage_configuration_fails_closed(tmp_path: Path, endpoint: str) -> None:
    with pytest.raises(ValueError, match="S3 storage requires"):
        BlobFiles(configured().model_copy(update={"s3_endpoint": endpoint}), tmp_path, "local")


@pytest.mark.parametrize(
    ("header", "size", "expected"),
    [
        (None, 5, (0, 4)),
        ("bytes=1-3", 5, (1, 3)),
        ("bytes=3-", 5, (3, 4)),
        ("bytes=-2", 5, (3, 4)),
        (None, 0, (0, -1)),
    ],
)
def test_download_ranges(header: str | None, size: int, expected: tuple[int, int]) -> None:
    assert byte_range(header, size) == expected


@pytest.mark.parametrize(
    "header", ["bytes=5-", "bytes=3-1", "bytes=-0", "bytes=a-b", "bytes=0-1,3-4"]
)
def test_invalid_ranges_are_rejected(header: str) -> None:
    with pytest.raises(ValueError):
        byte_range(header, 5)
