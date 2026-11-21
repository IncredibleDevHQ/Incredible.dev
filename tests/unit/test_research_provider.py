"""Research model picks must reach the selected provider in its own wire format."""

import json
from functools import partial
from unittest.mock import AsyncMock

import httpx
import httpx2
import pytest

from design_agent.config import Settings
from design_agent.surfaces.web import research_provider
from design_agent.surfaces.web.research_provider import ProviderResearch


@pytest.mark.parametrize(
    ("harness", "model", "effort", "field", "expected"),
    [
        ("codex", "", "", "reasoning", None),
        ("codex", "gpt-5.4-mini", "low", "reasoning", {"effort": "low"}),
        ("claude", "claude-opus-5-5", "high", "output_config", {"effort": "high"}),
        ("kimi", "kimi-k2.6", "instant", "thinking", {"type": "disabled"}),
        ("kimi", "kimi-k2.5", "thinking", "thinking", {"type": "enabled"}),
    ],
)
async def test_provider_model_and_effort_on_wire(
    monkeypatch, harness, model, effort, field, expected
):
    provider = ProviderResearch(
        Settings(
            _env_file=None, openai_api_key="test", anthropic_api_key="test", moonshot_api_key="test"
        ),
        "test",
    )
    monkeypatch.setattr(provider, "repos", lambda: [{"path": "sample"}])
    monkeypatch.setattr(provider, "read_sources", AsyncMock(return_value="test excerpt"))
    requests = []

    transport = httpx2 if harness == "claude" else httpx

    def send(request):
        requests.append(json.loads(request.content))
        if harness == "kimi":
            payload = {"choices": [{"message": {"role": "assistant", "content": "done"}}]}
        elif harness == "claude":
            payload = {"content": [{"type": "text", "text": "done"}]}
        else:
            payload = {
                "output": [
                    {"type": "message", "content": [{"type": "output_text", "text": "done"}]}
                ]
            }
        return transport.Response(200, json=payload, request=request)

    sdk = "AsyncAnthropic" if harness == "claude" else "AsyncOpenAI"
    http_client = transport.AsyncClient(transport=transport.MockTransport(send))
    monkeypatch.setattr(
        research_provider, sdk, partial(getattr(research_provider, sdk), http_client=http_client)
    )
    events = [
        event
        async for event in provider.run(
            harness, ["sample"], "Question", "", model=model, effort=effort
        )
    ]
    assert events[-1].text == "done"
    assert len(requests) == 1
    assert requests[0]["model"] == (model or "gpt-5.3-codex")
    if expected is None:
        assert field not in requests[0]
    else:
        assert requests[0][field] == expected
