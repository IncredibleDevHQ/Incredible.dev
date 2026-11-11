from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from design_agent.harness import tasks
from design_agent.middleware import background


@pytest.mark.parametrize("status", ["running", "failed", "done"])
async def test_resume_rejects_another_threads_helper_before_reading_transcripts(
    monkeypatch: pytest.MonkeyPatch, status: tasks.Status
) -> None:
    record = tasks.TaskRecord("t-private", "other-thread", "low", "Private label", None, 0)
    record.status = status
    monkeypatch.setattr(tasks, "REGISTRY", {record.id: record})
    monkeypatch.setattr(background, "REGISTRY", tasks.REGISTRY)
    transcript = AsyncMock(return_value=False)
    monkeypatch.setattr(background.durable, "can_resume", transcript)
    middleware = object.__new__(background.BackgroundTaskMiddleware)
    runtime = SimpleNamespace(config={"configurable": {"thread_id": "my-thread"}})

    result = await middleware.resume(record.id, runtime)

    assert result == "No task t-private on this thread."
    transcript.assert_not_awaited()
    assert tasks.REGISTRY[record.id] is record
