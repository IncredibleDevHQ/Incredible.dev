"""`design-agent sandbox publish`: the designer's computer as a LangSmith snapshot.

MDA bakes `sandbox/setup.sh` on the declared base. A `docker_image` base gets a 1 GiB filesystem,
and the computer unpacks to about 1.3 GiB, so production uses a snapshot with room for renders:

1. a base snapshot from the pinned Node image with `--fs-gib` of filesystem;
2. a short-lived sandbox from it that runs `setup.sh` (network allowed: it installs packages) and
   then the recipe's probe;
3. a snapshot captured from that sandbox, named after the recipe's hash, so the same recipe
   publishes the same name and a changed recipe a new one;
4. `sandbox/__init__.py` rewritten to declare that snapshot (MDA then re-runs `setup.sh` on it,
   which only re-runs the probe, because the recipe stamp matches).

Every step talks to LangSmith with the operator's key, costs sandbox time, and is run only on
request. The temporary sandbox is deleted whether or not publishing succeeded. Snapshots are found
by name, so publishing a recipe that is already published does nothing, and a run that stopped
part-way picks up the base snapshot it started.
"""

from __future__ import annotations

import hashlib
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

GIB = 1024**3
SETUP_PATH = "/tmp/design-agent-setup.sh"
#: Building a snapshot from a Docker image takes minutes; the SDK's own default is 60 s.
SNAPSHOT_TIMEOUT_SECONDS = 1800
PROBE = "/opt/design-agent/probe/probe.sh"
SETUP_TIMEOUT_SECONDS = 3600
DECLARATION = Path("sandbox") / "__init__.py"


class PublishError(RuntimeError):
    """A step failed; the message says which, without secrets or provider text."""


@dataclass(frozen=True)
class Published:
    snapshot_name: str
    snapshot_id: str
    recipe_sha: str
    probe: str


def recipe_sha(project_root: Path) -> str:
    return hashlib.sha256((project_root / "sandbox" / "setup.sh").read_bytes()).hexdigest()


def base_image(project_root: Path) -> str:
    match = re.search(
        r'^BASE_IMAGE = "([^"]+)"', (project_root / DECLARATION).read_text(), re.MULTILINE
    )
    if match is None:
        raise PublishError("sandbox/__init__.py declares no BASE_IMAGE")
    return match.group(1)


def publish(
    client: Any,
    project_root: Path,
    *,
    fs_gib: int = 16,
    vcpus: int = 8,
    mem_gib: int = 16,
    say: Callable[[str], None] = print,
) -> Published:
    """Build and capture the computer snapshot (module doc). `client` is a `SandboxClient`."""
    sha = recipe_sha(project_root)
    name = f"design-agent-computer-{sha[:12]}"
    published = _named(client, name)
    if published is not None and getattr(published, "status", "") == "ready":
        say(f"{name} is already published in this workspace.")
        return Published(name, str(published.id), sha, "")
    setup = (project_root / "sandbox" / "setup.sh").read_bytes()
    base_name = f"design-agent-base-{sha[:12]}"
    base = _named(client, base_name)
    if base is None:
        say(f"[1/3] Base snapshot from {base_image(project_root)} with {fs_gib} GiB of filesystem…")
        base = client.create_snapshot(
            base_name, base_image(project_root), fs_gib * GIB, timeout=SNAPSHOT_TIMEOUT_SECONDS
        )
    base = client.wait_for_snapshot(base.id, timeout=SNAPSHOT_TIMEOUT_SECONDS)
    if getattr(base, "status", "ready") != "ready":
        raise PublishError("the base snapshot did not become ready")
    builder = f"design-agent-publish-{sha[:12]}-{int(time.time())}"
    sandbox = client.create_sandbox(
        snapshot_id=base.id,
        name=builder,
        vcpus=vcpus,
        mem_bytes=mem_gib * GIB,
        fs_capacity_bytes=fs_gib * GIB,
    )
    try:
        say(
            "[2/3] Running the recipe (installs the browser, ffmpeg, fonts and the render "
            "toolchain; the longest step)…"
        )
        sandbox.write(SETUP_PATH, setup)
        result = sandbox.run(f"bash {SETUP_PATH}", timeout=SETUP_TIMEOUT_SECONDS)
        if getattr(result, "exit_code", 1) != 0:
            raise PublishError(
                "setup.sh failed in the publishing sandbox; run `design-agent sandbox test` locally"
            )
        probe = sandbox.run(PROBE, timeout=600)
        if getattr(probe, "exit_code", 1) != 0:
            raise PublishError("the recipe's probe failed after setup")
        say("[3/3] Capturing the snapshot…")
        snapshot = client.capture_snapshot(
            builder, name, fs_capacity_bytes=fs_gib * GIB, timeout=SNAPSHOT_TIMEOUT_SECONDS
        )
        snapshot = client.wait_for_snapshot(snapshot.id, timeout=SNAPSHOT_TIMEOUT_SECONDS)
        if getattr(snapshot, "status", "ready") != "ready":
            raise PublishError("the captured snapshot did not become ready")
    finally:
        try:
            client.delete_sandbox(builder)
        except Exception:  # noqa: BLE001 - it expires on its own; publishing already decided
            say(f"Could not delete the temporary sandbox {builder}; it will idle out.")
    return Published(name, str(snapshot.id), sha, str(getattr(probe, "stdout", "")).strip()[-300:])


def _named(client: Any, name: str) -> Any | None:
    """The workspace's snapshot called exactly `name`, a ready one first (names can repeat), or
    None."""
    matches = [snap for snap in client.list_snapshots(name_contains=name) if snap.name == name]
    ready = [snap for snap in matches if getattr(snap, "status", "") == "ready"]
    return (ready or matches or [None])[0]


def declare_snapshot(project_root: Path, snapshot_name: str) -> None:
    """Point `sandbox/__init__.py` at the snapshot: a literal MDA reads statically."""
    path = project_root / DECLARATION
    text = path.read_text()
    if "SNAPSHOT_NAME = " in text:
        text = re.sub(
            r'^SNAPSHOT_NAME = "[^"]*"',
            f'SNAPSHOT_NAME = "{snapshot_name}"',
            text,
            flags=re.MULTILINE,
        )
    else:
        text = text.replace("\nVCPUS = ", f'\nSNAPSHOT_NAME = "{snapshot_name}"\nVCPUS = ', 1)
    text = text.replace("    docker_image=BASE_IMAGE,\n", "    snapshot_name=SNAPSHOT_NAME,\n")
    path.write_text(text)


def declared_base(project_root: Path) -> str:
    """`docker_image` or `snapshot`: what MDA would bake `setup.sh` on."""
    text = (project_root / DECLARATION).read_text()
    if "snapshot_name=SNAPSHOT_NAME" in text or "snapshot_id=" in text:
        return "snapshot"
    return "docker_image"
