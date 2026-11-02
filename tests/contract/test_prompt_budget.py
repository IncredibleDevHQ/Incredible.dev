"""The lead's first model call stays small and stable (SPEC §5.4: ≤ 8k tokens of always-loaded
prompt, skill list included). Measured on the real graph with the sample brand."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage

from design_agent.config import Settings
from design_agent.runtime.local import build_local_runtime
from design_agent.testing.fakes import folder_binding
from design_agent.testing.scripted_model import ScriptedChatModel, reply

ROOT = Path(__file__).resolve().parents[2]
#: Characters per token for English prose and JSON schemas, rounded down so the estimate errs high.
CHARS_PER_TOKEN = 3.5
SYSTEM_BUDGET_TOKENS = 8_000
#: Not a SPEC target: a ceiling that catches a tool schema growing by accident.
TOOL_SCHEMA_BUDGET_TOKENS = 12_000


def text_of(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    return "".join(str(b.get("text", "")) if isinstance(b, dict) else str(b) for b in content)


async def test_the_first_call_fits_the_budget_and_carries_only_our_prompt(tmp_path: Path) -> None:
    seen: list[list[BaseMessage]] = []

    def first(messages: Sequence[BaseMessage]) -> AIMessage:
        seen.append(list(messages))
        return reply("ok")

    model = ScriptedChatModel(steps=[first])
    settings = Settings(_env_file=None, workspace_root=tmp_path / "ws")  # type: ignore[call-arg]
    runtime = build_local_runtime(
        settings,
        ROOT,
        model=model,
        binding=folder_binding(tmp_path / "sb", ROOT),
        replies=lambda *_: None,
    )
    await runtime.ask("Make a launch card.", thread_id="budget")

    system = seen[0][0]
    assert isinstance(system, SystemMessage)
    prompt = text_of(system)
    instructions = (ROOT / "instructions.md").read_text(encoding="utf-8")
    assert prompt.startswith(instructions.strip().splitlines()[0]), (
        "our prompt leads; no framework preamble"
    )
    assert "Mandatory entry point" not in prompt, "vendored skill descriptions are summarized"
    system_tokens = len(prompt) / CHARS_PER_TOKEN
    schema_tokens = len(json.dumps(model.bound_tool_batches[-1])) / CHARS_PER_TOKEN
    assert system_tokens <= SYSTEM_BUDGET_TOKENS, f"system prompt ~{system_tokens:.0f} tokens"
    assert schema_tokens <= TOOL_SCHEMA_BUDGET_TOKENS, f"tool schemas ~{schema_tokens:.0f} tokens"
