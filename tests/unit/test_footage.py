"""Raw footage in a bucket: where it goes for S3 and for a development store, and what is said
when the bucket does not take it."""

from __future__ import annotations

import io
from typing import Any

import pytest
from pydantic import SecretStr

from design_agent.config import Settings
from design_agent.envfile import EnvKey
from design_agent.tools import footage
from design_agent.tools.footage import Bucket, FootageError


class Refused(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(f"An error occurred ({code}) when calling the operation")
        self.response = {"Error": {"Code": code}}


class Client:
    def __init__(self, *, missing: bool = False, fails: Exception | None = None) -> None:
        self.missing, self.fails = missing, fails
        self.calls: list[tuple[Any, ...]] = []

    def head_bucket(self, *, Bucket: str) -> None:
        self.calls.append(("head", Bucket))
        if self.missing:
            raise Refused("404")

    def create_bucket(self, *, Bucket: str) -> None:
        self.calls.append(("create", Bucket))

    def upload_fileobj(self, source: Any, bucket: str, key: str, *, ExtraArgs: Any) -> None:
        if self.fails is not None:
            raise self.fails
        self.calls.append(("upload", bucket, key, source.read(), ExtraArgs))


class Boto:
    def __init__(self, client: Client) -> None:
        self.made, self.asked = client, {}

    def client(self, service: str, **options: Any) -> Client:
        self.asked = {"service": service, **options}
        return self.made


class Config:
    """botocore's client configuration, as far as these tests read it."""

    def __init__(self, **options: Any) -> None:
        self.options = options
        self.s3 = options.get("s3")


def sdk(monkeypatch: pytest.MonkeyPatch, client: Client) -> Boto:
    boto = Boto(client)
    monkeypatch.setattr(footage, "_sdk", lambda: (boto, Config, Refused, (Refused, OSError)))
    return boto


def test_footage_is_kept_only_where_a_bucket_is_set() -> None:
    assert Bucket.from_settings(Settings(_env_file=None)) is None
    settings = Settings(
        _env_file=None,
        footage_bucket=" footage ",
        s3_endpoint="http://127.0.0.1:9000",
        aws_access_key_id=SecretStr("dev-user"),
        aws_secret_access_key=SecretStr("dev-pass"),
    )  # type: ignore[call-arg]
    assert Bucket.from_settings(settings) == Bucket(
        name="footage", endpoint="http://127.0.0.1:9000", key_id="dev-user", secret="dev-pass"
    )
    # the pair that opens a bucket is never shown by the settings view
    assert EnvKey("AWS_ACCESS_KEY_ID", "", "raw footage").secret
    assert EnvKey("AWS_SECRET_ACCESS_KEY", "", "raw footage").secret
    assert not EnvKey("DESIGN_AGENT_FOOTAGE_BUCKET", "", "raw footage").secret


def test_a_development_store_gets_its_bucket_made_and_the_recording_from_its_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Client(missing=True)
    boto = sdk(monkeypatch, client)
    bucket = Bucket("footage", endpoint="http://127.0.0.1:9000", key_id="u", secret="p")
    recording = io.BytesIO(b"a camera's own file")
    recording.seek(0, 2)
    kept = bucket.put("episodes/ep_1/takes/tk_1.mov", recording, name="../IMG 0042 (1).MOV")
    assert kept == "s3://footage/episodes/ep_1/takes/tk_1.mov"
    assert client.calls == [
        ("head", "footage"),
        ("create", "footage"),
        (
            "upload",
            "footage",
            "episodes/ep_1/takes/tk_1.mov",
            b"a camera's own file",
            {"ContentType": "video/quicktime", "Metadata": {"name": "IMG 0042 _1_.MOV"}},
        ),
    ]
    assert boto.asked["service"] == "s3"
    assert boto.asked["endpoint_url"] == "http://127.0.0.1:9000"
    assert boto.asked["region_name"] == "us-east-1"
    assert boto.asked["aws_access_key_id"] == "u" and boto.asked["aws_secret_access_key"] == "p"
    assert boto.asked["config"].s3 == {"addressing_style": "path"}


def test_on_aws_the_bucket_is_never_made_and_the_machines_own_credentials_are_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Client()
    boto = sdk(monkeypatch, client)
    kept = Bucket("prod-footage", region="ap-south-1").put(
        "episodes/ep_1/takes/tk_2.webm", io.BytesIO(b"take")
    )
    assert kept == "s3://prod-footage/episodes/ep_1/takes/tk_2.webm"
    assert [call[0] for call in client.calls] == ["upload"]
    assert client.calls[0][4] == {"ContentType": "video/webm"}
    assert boto.asked["endpoint_url"] is None and boto.asked["region_name"] == "ap-south-1"
    assert boto.asked["aws_access_key_id"] is None and boto.asked["aws_secret_access_key"] is None


def test_a_bucket_that_does_not_take_it_says_why_and_shows_no_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sdk(monkeypatch, Client(fails=Refused("AccessDenied")))
    bucket = Bucket("footage", key_id="key-id-not-shown", secret="never-shown")
    with pytest.raises(FootageError) as refused:
        bucket.put("episodes/ep_1/takes/tk_3.m4a", io.BytesIO(b"voice"))
    assert "AccessDenied" in str(refused.value)
    assert "not-shown" not in str(refused.value) and "never-shown" not in str(refused.value)
    # a store that is down is the same: the take is the desk's to keep either way
    sdk(monkeypatch, Client(fails=OSError("Could not connect to the endpoint URL")))
    with pytest.raises(FootageError, match="Could not connect"):
        bucket.put("episodes/ep_1/takes/tk_3.m4a", io.BytesIO(b"voice"))
