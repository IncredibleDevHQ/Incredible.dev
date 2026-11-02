"""Parity (SPEC §15, §23): every runtime assembles the same agent.

The CLI and the self-hosted API differ only in what each supplies: the sandbox backend, file
delivery, how the lead is woken, and how runs reach the agent. The prompt, skills, tools,
middleware order and helpers are the same object graph. A presenter adds its middleware where the
hook puts it and changes nothing else.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from langchain.agents.middleware import AgentMiddleware

from design_agent.assembly import AgentComponents, build_agent_components
from design_agent.config import Settings
from design_agent.middleware.background import BackgroundServices
from design_agent.runtime.local import local_profile
from design_agent.runtime.waker.local import InProcessWaker
from design_agent.surfaces.presenter import Presenter
from design_agent.testing.fakes import folder_binding
from design_agent.testing.scripted_model import ScriptedChatModel

ROOT = Path(__file__).resolve().parents[2]


def shape(components: AgentComponents) -> dict[str, Any]:
    return {
        "prompt": components.system_prompt,
        "skills": components.skills,
        "tools": sorted(t.name for t in components.tools),
        "middleware": [type(m).__name__ for m in components.middleware],
        "helpers": [s["name"] for s in components.subagents],
        "helper_middleware": [
            [type(m).__name__ for m in s.get("middleware", [])] for s in components.subagents
        ],
        "brand": components.brand.brand.name,
        "manifest": components.manifest.digest,
    }


class Steering(AgentMiddleware):
    pass


class Progress(AgentMiddleware):
    pass


class HelperLane(AgentMiddleware):
    pass


class FakePresenter:
    """A channel UI's presenter: steering and progress for the lead, a lane for each helper."""

    def __init__(self) -> None:
        self.services: list[BackgroundServices | None] = []

    def lead_middleware(
        self, *, settings: Settings, services: BackgroundServices | None
    ) -> Sequence[AgentMiddleware[Any, Any, Any]]:
        self.services.append(services)
        return [Steering(), Progress()]

    def helper_middleware(self, *, settings: Settings) -> Sequence[AgentMiddleware[Any, Any, Any]]:
        return [HelperLane()]


def assemble(
    tmp_path: Path, *, surface: str, presenter: Presenter | None = None
) -> tuple[AgentComponents, BackgroundServices]:
    settings = Settings(_env_file=None, workspace_root=tmp_path / "ws")  # type: ignore[call-arg]

    async def run_turn(*_: Any) -> None:
        return None

    waker = InProcessWaker(run_turn)
    services = BackgroundServices(waker=waker, capture_target=waker.capture)
    binding = folder_binding(tmp_path / "sb", ROOT)
    profile = local_profile(
        ROOT, binding, tmp_path / "out", services, presenter=presenter, surface=surface
    )
    components = build_agent_components(
        settings=settings,
        runtime=profile,
        model=ScriptedChatModel(steps=[]),
        role_models={"helper": ScriptedChatModel(steps=[]), "look": ScriptedChatModel(steps=[])},
    )
    return components, services


def test_the_cli_and_the_self_hosted_api_assemble_the_same_agent(tmp_path: Path) -> None:
    cli, _ = assemble(tmp_path / "cli", surface="cli")
    api, _ = assemble(tmp_path / "api", surface="api")
    assert shape(cli) == shape(api)
    assert "upload_files" in {t.name for t in cli.tools}, "both bring delivery"


def test_a_presenter_adds_its_middleware_where_the_hook_puts_it(tmp_path: Path) -> None:
    """The lead's after the run tags and before background work, outside the model guards; each
    helper's after its stagger gate, just inside the guards. Nothing else moves."""
    presenter = FakePresenter()
    headless, _ = assemble(tmp_path / "headless", surface="api")
    shown, services = assemble(tmp_path / "shown", surface="web", presenter=presenter)
    assert presenter.services == [services]

    lead = shape(headless)["middleware"]
    at = lead.index("RunTagsMiddleware") + 1
    assert lead[at] == "BackgroundTaskMiddleware"
    assert shape(shown)["middleware"] == [*lead[:at], "Steering", "Progress", *lead[at:]]

    helpers = shape(headless)["helper_middleware"]
    assert helpers, "the helpers are assembled"
    expected = []
    for names in helpers:
        after = names.index("StaggerMiddleware") + 1
        expected.append([*names[:after], "HelperLane", *names[after:]])
    assert shape(shown)["helper_middleware"] == expected

    rest = {k: v for k, v in shape(shown).items() if k not in ("middleware", "helper_middleware")}
    assert rest == {
        k: v for k, v in shape(headless).items() if k not in ("middleware", "helper_middleware")
    }
