"""Opt-in live checks against real providers (SPEC §20.6). Never run in CI by default.

    DESIGN_AGENT_LIVE_TESTS=1 uv run pytest -q -m live tests/live

Each test needs its own key and skips without it. They cost cents, except the LangSmith sandbox
check, which bills a few minutes of sandbox time.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from design_agent.config import Settings
from design_agent.models.factory import build_chat_model
from design_agent.runtime.local import build_local_runtime
from design_agent.testing.fakes import folder_binding
from design_agent.testing.scripted_model import ScriptedChatModel, reply, tool_call

pytestmark = pytest.mark.live
ROOT = Path(__file__).resolve().parents[2]


def needs(*names: str) -> None:
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        pytest.skip(f"needs {', '.join(missing)}")


async def test_the_configured_model_answers() -> None:
    settings = Settings()
    key = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "google_genai": "GOOGLE_API_KEY",
    }.get(settings.lead_model().upstream.provider)
    if key:
        needs(key)
    model = (
        build_chat_model(settings, "lead", effort="low")
        if settings.lead_model().upstream.provider == "anthropic"
        else build_chat_model(settings, "lead")
    )
    answer = await model.ainvoke("Reply with the single word OK.")
    assert "OK" in str(answer.content).upper()


async def _tool_once(tmp_path: Path, name: str, args: dict[str, object]) -> str:
    seen: list[str] = []

    def after(messages: Sequence[BaseMessage]) -> AIMessage:
        last = messages[-1]
        seen.append(str(last.content) if isinstance(last, ToolMessage) else "")
        return reply("done")

    lead = ScriptedChatModel(steps=[lambda _m: tool_call(name, args), after])
    settings = Settings(workspace_root=tmp_path / "ws")
    runtime = build_local_runtime(
        settings,
        ROOT,
        model=lead,
        binding=folder_binding(tmp_path / "sb", ROOT),
        replies=lambda *_: None,
    )
    await runtime.ask(f"Run {name}.", thread_id=f"live-{name}")
    return seen[-1]


async def test_image_generation_writes_a_file(tmp_path: Path) -> None:
    needs("OPENAI_API_KEY")
    result = await _tool_once(
        tmp_path,
        "generate_image",
        {
            "prompt": "A flat paper texture, warm off-white, soft light",
            "sandbox_path": "/workspace/projects/live/plate.png",
            "size": "1024x1024",
        },
    )
    assert (tmp_path / "sb/workspace/projects/live/plate.png").is_file(), result


async def test_voiceover_writes_audio(tmp_path: Path) -> None:
    needs("ELEVENLABS_API_KEY", "DESIGN_AGENT_LIVE_VOICE_ID")
    voice = os.environ["DESIGN_AGENT_LIVE_VOICE_ID"]
    result = await _tool_once(
        tmp_path,
        "generate_voiceover",
        {
            "text": "Every size, one pass.",
            "voice_id": voice,
            "sandbox_path": "/workspace/projects/live/vo.mp3",
        },
    )
    assert (tmp_path / "sb/workspace/projects/live/vo.mp3").stat().st_size > 1000, result


def test_a_langsmith_sandbox_from_the_published_snapshot_passes_the_probe() -> None:
    needs("LANGSMITH_API_KEY", "DESIGN_AGENT_SANDBOX_SNAPSHOT")
    from design_agent.runtime.sandbox.langsmith import LangSmithSandboxPool

    backend = LangSmithSandboxPool(Settings()).backend("live-probe")  # idles out on its own TTL
    result = backend.execute("/opt/design-agent/probe/probe.sh", timeout=900)
    assert result.exit_code == 0, result.output[-2000:]
