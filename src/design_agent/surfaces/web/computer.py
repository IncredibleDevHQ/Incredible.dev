"""An episode's use of its thread's computer: where stills are posed and the film is rendered.

The engine's agent reaches the sandbox through its tools. An episode's own code needs the same
computer for work no model does (posing a picture's stills, cutting a take to the film's
format, rendering the film), so this wraps the runtime's sandbox for one thread: files in,
commands, files out. With the Docker sandbox that is the thread's container; with the host
sandbox (development) it is a folder under `.host-sandbox/` and this machine's own tools.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from design_agent.middleware.workspace import stage
from design_agent.runtime.sandbox import SandboxBinding
from design_agent.runtime.sandbox.docker import DockerStagingTarget, tar_of
from design_agent.workspace.manifest import Manifest

#: Where the agent's projects live on the thread's computer.
PROJECTS = "/workspace/projects"
#: The render toolchain's own copy of GSAP, which every composition loads from beside itself.
GSAP = "/opt/design-agent/render/node_modules/gsap/dist/gsap.min.js"


@dataclass(frozen=True)
class Ran:
    output: str
    code: int

    @property
    def ok(self) -> bool:
        return self.code == 0


class Computer:
    """One thread's computer. Paths are given as the sandbox sees them (`/workspace/...`)."""

    def __init__(self, binding: SandboxBinding, thread_id: str, host_root: Path) -> None:
        self._runner = binding.runner
        self._thread_id = thread_id
        self._host_root = host_root / ".host-sandbox"

    @property
    def renders(self) -> bool:
        """Whether this computer has the render toolchain for certain (the sandbox image)."""
        return self._runner is not None

    def stage(self, manifest: Manifest) -> None:
        """Bring this computer up to the workspace the engine's own runs stage: the brand
        pack and its fonts. A computer already there is left alone."""
        if self._runner is not None:
            stage(DockerStagingTarget(self._runner, thread_id=lambda: self._thread_id), manifest)

    def _local(self, path: str) -> Path:
        return self._host_root / path.lstrip("/")

    def put(self, files: list[tuple[str, bytes]]) -> None:
        if not files:
            return
        if self._runner is None:
            for path, content in files:
                target = self._local(path)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
            return
        parents = sorted({str(Path(path).parent) for path, _ in files})
        self._runner.exec(self._thread_id, "mkdir -p " + " ".join(shlex.quote(p) for p in parents))
        self._runner.put_archive(self._thread_id, tar_of(files), root=False)

    def put_stream(self, path: str, source: IO[bytes]) -> None:
        """One file from an open file on this computer, from its start, copied across without
        being held in memory: a camera's own recording runs to gigabytes."""
        source.seek(0)
        if self._runner is None:
            target = self._local(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("wb") as out:
                shutil.copyfileobj(source, out, 1024 * 1024)
            return
        try:
            source.fileno()
        except (AttributeError, OSError):
            # no file behind it (bytes already in memory): sent the way small files are
            self.put([(path, source.read())])
            return
        self._runner.exec(self._thread_id, f"mkdir -p {shlex.quote(str(Path(path).parent))}")
        self._runner.put_file(self._thread_id, path, source)

    def get(self, path: str) -> bytes | None:
        if self._runner is None:
            target = self._local(path)
            return target.read_bytes() if target.is_file() else None
        return self._runner.get_file(self._thread_id, path)

    def run(self, command: str, *, timeout: int = 600) -> Ran:
        if self._runner is None:
            # The host sandbox: the same command, with the sandbox's paths under its folder.
            root = str(self._host_root)
            local = command.replace("/workspace/", f"{root}/workspace/")
            done = subprocess.run(  # noqa: S603 - a command this module composed, not a person's
                ["bash", "-c", local],  # noqa: S607 - bash from PATH, as the host sandbox runs
                capture_output=True,
                timeout=timeout,
                cwd=root,
                check=False,
            )
            return Ran((done.stdout + done.stderr).decode(errors="replace"), done.returncode)
        result = self._runner.exec(self._thread_id, command, timeout=timeout)
        return Ran(result.output, int(result.exit_code or 0))
