"""Prepare the mounted workspace and the remote Docker client before starting the Railway web service."""

import os
import pwd
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit


def configure_runner() -> None:
    endpoint = urlsplit(os.environ.get("DOCKER_HOST", ""))
    if (
        endpoint.scheme != "tcp"
        or not endpoint.hostname
        or not endpoint.port
        or endpoint.username is not None
        or endpoint.path
        or endpoint.query
        or endpoint.fragment
    ):
        raise SystemExit("Set DOCKER_HOST to the TLS endpoint of the dedicated Docker runner")
    keys = {name: f"RUNNER_{name.upper()}_PEM" for name in ("ca", "cert", "key")}
    for key in keys.values():
        if not os.environ.get(key, "").strip():
            raise SystemExit(f"Set {key} for Docker mutual TLS")
    directory = Path(tempfile.mkdtemp(prefix="docker-client-"))
    for name, key in keys.items():
        path = directory / f"{name}.pem"
        path.touch(mode=0o600)
        path.write_text(os.environ.pop(key))
    os.environ.pop("DOCKER_CONTEXT", None)
    os.environ.update(DOCKER_TLS_VERIFY="1", DOCKER_CERT_PATH=str(directory))


def main() -> None:
    origin = urlsplit(os.environ.get("DESIGN_AGENT_APP_URL", ""))
    if (
        origin.scheme != "https"
        or not origin.hostname
        or origin.username is not None
        or origin.path not in ("", "/")
        or origin.query
        or origin.fragment
    ):
        raise SystemExit("Set DESIGN_AGENT_APP_URL to the public HTTPS origin")
    if (
        os.environ.get("DESIGN_AGENT_AUTH_REQUIRED") != "1"
        or os.environ.get("DESIGN_AGENT_SANDBOX") != "docker"
    ):
        raise SystemExit("Railway requires authenticated workspaces and the Docker sandbox")
    data = Path("/data")
    if os.environ.get("RAILWAY_VOLUME_MOUNT_PATH") != str(data) or not data.is_mount():
        raise SystemExit("Mount the workspace volume at /data")
    # Only the root of the newly mounted volume needs ownership. Tenant files may already exist.
    user = pwd.getpwnam("agent")
    if os.geteuid() == 0:
        os.chown(data, user.pw_uid, user.pw_gid)
        os.setgroups([])
        os.setgid(user.pw_gid)
        os.setuid(user.pw_uid)
    (data / "workspace").mkdir(mode=0o700, exist_ok=True)
    configure_runner()
    port = os.environ.get("PORT", "")
    if not port.isascii() or not port.isdecimal() or not 1 <= int(port) <= 65535:
        raise SystemExit("Railway must supply a valid PORT")
    args = [sys.executable, "-m", "design_agent.surfaces.web", "--host", "0.0.0.0", "--port", port]  # noqa: S104
    os.execv(sys.executable, args)  # noqa: S606


if __name__ == "__main__":
    main()
