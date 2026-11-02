"""Shared test configuration: offline by default.

`render` tests need Docker and the sandbox image (`design-agent sandbox build`); they skip with a
reason when either is missing. `live` tests call real providers and run only with
DESIGN_AGENT_LIVE_TESTS=1.
"""

from __future__ import annotations

import functools
import os
import shutil
import subprocess

import pytest

SANDBOX_IMAGE = os.environ.get("DESIGN_AGENT_SANDBOX_IMAGE", "design-agent-sandbox:local")


@functools.cache
def sandbox_image_available() -> tuple[bool, str]:
    docker = shutil.which("docker")
    if docker is None:
        return False, "docker is not installed"
    found = subprocess.run(
        [docker, "image", "inspect", SANDBOX_IMAGE], capture_output=True, check=False
    )
    if found.returncode != 0:
        return False, f"sandbox image {SANDBOX_IMAGE} is not built (design-agent sandbox build)"
    return True, ""


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    live = os.environ.get("DESIGN_AGENT_LIVE_TESTS") == "1"
    for item in items:
        if "live" in item.keywords and not live:
            item.add_marker(
                pytest.mark.skip(reason="live provider test; set DESIGN_AGENT_LIVE_TESTS=1")
            )
        if "render" in item.keywords:
            ok, reason = sandbox_image_available()
            if not ok:
                item.add_marker(pytest.mark.skip(reason=reason))


@pytest.fixture(autouse=True)
def _no_ambient_keys(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    """Offline tests never see real provider keys from the developer's shell."""
    if "live" in request.keywords:
        return
    for name in (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GOOGLE_API_KEY",
        "ELEVENLABS_API_KEY",
        "LANGSMITH_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
