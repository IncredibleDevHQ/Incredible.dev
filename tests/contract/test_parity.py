"""Parity (SPEC §15, §23): every runtime assembles the same agent.

Managed Deep Agents, the CLI and the self-hosted API differ only in what each platform supplies:
the sandbox backend, file delivery (MDA's channel brings its own `upload_files`), how the lead is
woken, and what a `[quiet]` reply becomes. The prompt, skills, tools, middleware order and helpers
are the same object graph.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from design_agent.assembly import AgentComponents, build_agent_components
from design_agent.config import Settings
from design_agent.middleware.background import BackgroundServices
from design_agent.runtime.local import local_profile
from design_agent.runtime.profiles import mda_profile
from design_agent.runtime.waker.local import InProcessWaker
from design_agent.surfaces.slack import BoltSlackResolver, SlackSurface
from design_agent.testing.fakes import folder_binding
from design_agent.testing.scripted_model import ScriptedChatModel

ROOT = Path(__file__).resolve().parents[2]


def shape(components: AgentComponents) -> dict[str, Any]:
    return {
        "prompt": components.system_prompt,
        "skills": components.skills,
        "tools": sorted(t.name for t in components.tools if t.name != "upload_files"),
        "middleware": [type(m).__name__ for m in components.middleware],
        "helpers": [s["name"] for s in components.subagents],
        "helper_middleware": [
            [type(m).__name__ for m in s.get("middleware", [])] for s in components.subagents
        ],
        "brand": components.brand.brand.name,
        "manifest": components.manifest.digest,
    }


def test_mda_local_and_self_hosted_assemble_the_same_agent(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, workspace_root=tmp_path / "ws")  # type: ignore[call-arg]
    model = ScriptedChatModel(steps=[])
    roles = {"helper": ScriptedChatModel(steps=[]), "look": ScriptedChatModel(steps=[])}

    async def run_turn(*_: Any) -> None:
        return None

    waker = InProcessWaker(run_turn)
    services = BackgroundServices(waker=waker, capture_target=waker.capture)
    binding = folder_binding(tmp_path / "sb", ROOT)
    slack = SlackSurface(
        BoltSlackResolver("xoxb-test")
    )  # self-hosted Slack, as `design-agent slack` builds it
    profile = local_profile(ROOT, binding, tmp_path / "out", services, slack=slack, surface="api")
    local = build_agent_components(
        settings=settings, runtime=profile, model=model, role_models=roles
    )
    mda = build_agent_components(
        settings=settings, runtime=mda_profile(ROOT), model=model, role_models=roles
    )

    mda_shape = shape(mda)
    # MDA's Slack channel brings `upload_files`; the fallback covers runs without a channel.
    assert "UploadFallbackMiddleware" in mda_shape["middleware"]
    mda_shape["middleware"].remove("UploadFallbackMiddleware")
    assert shape(local) == mda_shape
    assert "upload_files" in {t.name for t in local.tools}, "local and self-hosted bring delivery"
    assert "upload_files" not in {t.name for t in mda.tools}, "MDA's Slack channel brings its own"
