"""The full local app uses Supabase and durable, private MinIO storage."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]


def compose(tmp_path: Path, overrides: str = "") -> dict[str, Any]:
    if shutil.which("docker") is None:
        pytest.skip("Docker CLI is needed to validate Compose")
    shutil.copyfile(ROOT / "compose.yaml", tmp_path / "compose.yaml")
    (tmp_path / ".env").write_text(overrides)
    (tmp_path / ".env.supabase").write_text(
        "\n".join(line for line in overrides.splitlines() if not line.startswith("MINIO_"))
    )
    (tmp_path / ".env.storage").write_text(
        "\n".join(
            line
            for line in overrides.splitlines()
            if line.startswith(("DESIGN_AGENT_S3_", "DESIGN_AGENT_BLOB_"))
        )
    )
    (tmp_path / ".env.minio").write_text(
        "\n".join(line for line in overrides.splitlines() if line.startswith("MINIO_"))
    )
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("COMPOSE_", "LOCAL_", "DOCKER_SOCKET_PATH", "DOCKER_GID"))
    }
    result = subprocess.run(
        ["docker", "compose", "--project-directory", str(tmp_path), "config", "--format", "json"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_supabase_database_is_used_and_auth_cannot_be_disabled(tmp_path: Path) -> None:
    config = compose(
        tmp_path,
        "DATABASE_URL=postgresql://invalid/unused\nDESIGN_AGENT_SANDBOX=host\nDESIGN_AGENT_WORKSPACE_ROOT=/lost\nDESIGN_AGENT_AUTH_REQUIRED=0\n",
    )
    assert set(config["services"]) == {"app", "sandbox", "minio", "minio-init"}
    app = config["services"]["app"]
    assert app["environment"]["DATABASE_URL"] == "postgresql://invalid/unused"
    assert app["environment"]["DESIGN_AGENT_AUTH_REQUIRED"] == "1"
    assert app["environment"]["DESIGN_AGENT_SANDBOX"] == "docker"
    assert app["environment"]["DESIGN_AGENT_WORKSPACE_ROOT"] == "/app/workspace"
    mounts = {v["target"]: v for v in app["volumes"]}
    assert mounts["/app/workspace"]["source"] == str(tmp_path / "workspace")
    assert mounts["/app/workspace"]["type"] == "bind"
    assert not mounts["/app/workspace"].get("read_only", False)
    assert "/app/.env" not in mounts


def test_minio_is_private_persistent_and_app_never_receives_root_credentials(
    tmp_path: Path,
) -> None:
    config = compose(
        tmp_path,
        "MINIO_ROOT_USER=root-test\nMINIO_ROOT_PASSWORD=root-secret\nDESIGN_AGENT_BLOB_BACKEND=local\n",
    )
    app = config["services"]["app"]
    assert app["environment"]["DESIGN_AGENT_BLOB_BACKEND"] == "s3"
    assert app["environment"]["DESIGN_AGENT_S3_ENDPOINT"] == "http://minio:9000"
    assert "MINIO_ROOT_PASSWORD" not in app["environment"]
    assert app["depends_on"]["minio-init"]["condition"] == "service_completed_successfully"
    minio = config["services"]["minio"]
    assert all(p["host_ip"] == "127.0.0.1" for p in minio["ports"])
    assert any(v["target"] == "/data" and v["type"] == "volume" for v in minio["volumes"])


def test_app_is_local_only_and_waits_for_the_sandbox(tmp_path: Path) -> None:
    config = compose(tmp_path)
    app = config["services"]["app"]
    assert len(app["ports"]) == 1
    assert app["ports"][0]["host_ip"] == "127.0.0.1"
    assert app["ports"][0]["target"] == 8765
    assert app["depends_on"]["sandbox"]["condition"] == "service_completed_successfully"
    assert app["init"] is True
    assert app["healthcheck"]["test"][0] == "CMD"
    assert app["restart"] == "unless-stopped"
    assert "env_file" not in config["services"]["sandbox"]
    assert not config["services"]["sandbox"].get("environment")


def test_host_permissions_and_socket_can_be_configured(tmp_path: Path) -> None:
    app = compose(
        tmp_path,
        "LOCAL_UID=501\nLOCAL_GID=20\nDOCKER_GID=998\nDOCKER_SOCKET_PATH=/custom/docker.sock\n",
    )["services"]["app"]
    assert app["user"] == "501:20"
    assert app["group_add"] == ["998"]
    mounts = {v["target"]: v for v in app["volumes"]}
    assert mounts["/var/run/docker.sock"]["source"] == "/custom/docker.sock"
    assert mounts["/app/private-fonts"]["read_only"] is True
