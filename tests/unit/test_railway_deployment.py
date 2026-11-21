import os
from contextlib import closing
from pathlib import Path
from runpy import run_path
from urllib.parse import urlsplit

import pytest
from pydantic import SecretStr

from design_agent.config import Settings
from design_agent.surfaces.web.blobs import s3_client

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "style,host", [("virtual", "files-test.objects.example"), ("path", "objects.example")]
)
def test_bucket_addressing(monkeypatch, style, host):
    monkeypatch.setenv("DESIGN_AGENT_BLOB_S3_ADDRESSING_STYLE", style)
    settings = Settings(
        _env_file=None,
        s3_endpoint="https://objects.example",
        s3_bucket="files-test",
        s3_access_key=SecretStr("fixture"),
        s3_secret_key=SecretStr("fixture"),
    )
    with closing(s3_client(settings)) as client:
        url = client.generate_presigned_url(
            "get_object", Params={"Bucket": "files-test", "Key": "a"}
        )
    assert urlsplit(url).hostname == host


def test_runner_tls_files_are_private(tmp_path, monkeypatch):
    start = run_path(str(ROOT / "deploy/railway/start.py"))
    monkeypatch.setenv("DOCKER_HOST", "tcp://runner.example:2376")
    for key in ("CA", "CERT", "KEY"):
        monkeypatch.setenv(f"RUNNER_{key}_PEM", key)
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    for name in ("DOCKER_CERT_PATH", "DOCKER_TLS_VERIFY", "DOCKER_CONTEXT"):
        monkeypatch.setenv(name, "previous-value")
    start["configure_runner"]()
    assert "DOCKER_CONTEXT" not in os.environ
    directory = Path(os.environ["DOCKER_CERT_PATH"])
    assert directory.parent == tmp_path
    assert directory.stat().st_mode & 0o077 == 0
    assert os.environ["DOCKER_TLS_VERIFY"] == "1"
    for name in ("ca", "cert", "key"):
        cert = directory / f"{name}.pem"
        assert cert.read_text() == name.upper()
        assert cert.stat().st_mode & 0o077 == 0
        assert f"RUNNER_{name.upper()}_PEM" not in os.environ


@pytest.mark.parametrize(
    "host", ["", "unix:///var/run/docker.sock", "tcp://user:password@runner:2376"]
)
def test_runner_rejects_missing_or_invalid_endpoint(monkeypatch, host):
    start = run_path(str(ROOT / "deploy/railway/start.py"))
    monkeypatch.setenv("DOCKER_HOST", host)
    with pytest.raises(SystemExit, match="DOCKER_HOST"):
        start["configure_runner"]()


def test_runner_rejects_missing_tls_material(monkeypatch):
    start = run_path(str(ROOT / "deploy/railway/start.py"))
    monkeypatch.setenv("DOCKER_HOST", "tcp://runner.example:2376")
    monkeypatch.delenv("RUNNER_KEY_PEM", raising=False)
    with pytest.raises(SystemExit, match="RUNNER_"):
        start["configure_runner"]()


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"DESIGN_AGENT_APP_URL": "http://app.example"}, "HTTPS"),
        ({"DESIGN_AGENT_AUTH_REQUIRED": "0"}, "authenticated"),
        ({"DESIGN_AGENT_SANDBOX": "host"}, "Docker"),
        ({"RAILWAY_VOLUME_MOUNT_PATH": "/tmp"}, "volume"),
    ],
)
def test_unsafe_web_configuration_stops_before_startup(monkeypatch, overrides, message):
    for name, value in {
        "DESIGN_AGENT_APP_URL": "https://app.example",
        "DESIGN_AGENT_AUTH_REQUIRED": "1",
        "DESIGN_AGENT_SANDBOX": "docker",
        **overrides,
    }.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(SystemExit, match=message):
        run_path(str(ROOT / "deploy/railway/start.py"))["main"]()


@pytest.mark.parametrize(
    "overrides,error",
    [
        ({"MINIO_ROOT_PASSWORD": ""}, "MINIO_ROOT_PASSWORD"),
        ({"DESIGN_AGENT_S3_ACCESS_KEY": "admin-fixture"}, "distinct"),
        ({"RAILWAY_VOLUME_MOUNT_PATH": "/tmp"}, "volume"),
    ],
)
def test_minio_rejects_incomplete_or_unsafe_configuration(overrides, error):
    import subprocess

    env = {
        "PATH": os.defpath,
        "MINIO_ROOT_USER": "admin-fixture",
        "MINIO_ROOT_PASSWORD": "private-admin-fixture",
        "DESIGN_AGENT_S3_ACCESS_KEY": "web-fixture",
        "DESIGN_AGENT_S3_SECRET_KEY": "private-web-fixture",
        "RAILWAY_VOLUME_MOUNT_PATH": "/data",
        **overrides,
    }
    result = subprocess.run(
        ["/bin/sh", str(ROOT / "deploy/railway/minio.sh")],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert error in result.stderr
    assert "private-" not in result.stderr
