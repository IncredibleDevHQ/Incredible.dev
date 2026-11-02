"""`run_pipeline` and `answer_pipeline`: the lead's tools for pipelines (docs/architecture/orchestration.md).

A pipeline is a production whose order, reviews and retries are code (`harness.workflow`,
`design_agent.pipelines`). Each step is a helper run inline in the pipeline's own task, in this thread's sandbox:
the pipeline reports each step (`PIPELINE_STEP`, held for the lead's next wake-up) and wakes the lead
once when it finishes, fails, or asks something. A run that failed, was cancelled or was interrupted
continues with `resume_task` and its id: finished steps replay from the store, only the rest runs.
"""

from __future__ import annotations

import json
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.tools import ToolRuntime
from langchain_core.tools import BaseTool, StructuredTool

from design_agent.harness import notices
from design_agent.harness.protocols import WakeTarget
from design_agent.harness.workflow import RunRecord, WorkflowError, WorkflowRunner
from design_agent.middleware.background import (
    CANCELLERS,
    RESUMERS,
    BackgroundHelpers,
    BackgroundTaskMiddleware,
)
from design_agent.pipelines import catalog, register_all

#: One runner per store: a deployment has one store, but a process can host several runtimes (the
#: CLI's successive invocations, tests), and a runner must never outlive the store it writes to.
_RUNNERS: dict[int, tuple[Any, WorkflowRunner]] = {}


def pipeline_runner(store: Any) -> WorkflowRunner:
    """The runner for this store, built on first use."""
    entry = _RUNNERS.get(id(store))
    if entry is None or entry[0] is not store:
        entry = (store, register_all(WorkflowRunner(store)))
        _RUNNERS[id(store)] = entry
    return entry[1]


def _running_lines(thread_id: str) -> list[str]:
    return [line for _, runner in _RUNNERS.values() for line in runner.running_lines(thread_id)]


def _cancel(task_id: str, thread_id: str) -> str | None:
    for _, runner in _RUNNERS.values():
        if (said := runner.canceller(task_id, thread_id)) is not None:
            return said
    return None


if _running_lines not in notices.RUNNING_PROVIDERS:
    notices.RUNNING_PROVIDERS.append(_running_lines)
if _cancel not in CANCELLERS:
    CANCELLERS.append(_cancel)


RUN_PIPELINE = """Run a pipeline: a production whose order, reviews and retries are code, each step a
helper in this thread's computer. It returns at once. You are woken when it finishes or fails, and
when it asks you something (answer with answer_pipeline); each step's report reaches you with your
next wake-up, so tell the person what runs and when to expect it, and end your turn. A run that
failed, was cancelled or was interrupted continues with resume_task and its id: finished steps
replay, and only the rest runs.

`args_json` is a JSON object of the pipeline's arguments. Pipelines:
{catalog}"""


class PipelineToolsMiddleware(AgentMiddleware[Any, Any, Any]):
    """`run_pipeline` and `answer_pipeline`, on the lead's background middleware."""

    def __init__(self, *, background: BackgroundTaskMiddleware) -> None:
        super().__init__()
        self._background = background
        background.services.sweepers.append(self._sweep)
        if self._resume not in RESUMERS:
            RESUMERS.append(self._resume)
        self.tools = self._build_tools()

    @property
    def name(self) -> str:
        return "DesignAgentPipelineTools"

    async def _sweep(self, store: Any) -> int:
        """Tell the leads about pipeline runs a restart ended."""
        inbox = self._background.services.inbox

        async def wake_here(record: RunRecord) -> None:
            if inbox.box(record.thread_id) is None:
                inbox.set_target(
                    record.thread_id, WakeTarget(record.thread_id, channel=record.meta.get("wake"))
                )

        return len(await pipeline_runner(store).sweep(on_found=wake_here))

    async def _here(
        self, runtime: Any
    ) -> tuple[WorkflowRunner, str, BackgroundHelpers, dict[str, Any]]:
        target = await self._background.services.attach(runtime)
        thread_id = target.thread_id if target is not None else ""
        helpers = BackgroundHelpers(self._background, runtime, inline=True)
        return (
            pipeline_runner(runtime.store),
            thread_id,
            helpers,
            {"wake": target.channel if target else None},
        )

    def _build_tools(self) -> list[BaseTool]:
        middleware = self

        async def run_pipeline(name: str, args_json: str, runtime: ToolRuntime) -> str:
            runner, thread_id, helpers, meta = await middleware._here(runtime)
            if not thread_id:
                return "Pipelines need a thread."
            try:
                args = json.loads(args_json or "{}")
                run_id = await runner.start(name, args, thread_id, runner=helpers, meta=meta)
            except (json.JSONDecodeError, WorkflowError) as error:
                return f"Not started: {error}"
            return f"Started {run_id} ({name}) in the background."

        async def answer_pipeline(run_id: str, answer: str, runtime: ToolRuntime) -> str:
            """Answer the question a pipeline is waiting on with the person's decision (one of the
            options it gave, and any detail after it: "changes: the logo lands late"). It
            continues from where it stopped: finished steps replay, only the rest runs."""
            runner, _thread_id, helpers, _meta = await middleware._here(runtime)
            try:
                record = await runner.answer(run_id, answer, runner=helpers)
            except WorkflowError as error:
                return str(error)
            return f"{run_id} continues with your answer. {record.describe()}"

        return [
            StructuredTool.from_function(
                coroutine=run_pipeline,
                name="run_pipeline",
                description=RUN_PIPELINE.format(catalog=catalog()),
            ),
            StructuredTool.from_function(coroutine=answer_pipeline, name="answer_pipeline"),
        ]

    async def _resume(self, task_id: str, runtime: Any) -> str | None:
        """`resume_task` for a pipeline run; None for any other id."""
        if not task_id.startswith("p-"):
            return None
        runner, _thread_id, helpers, _meta = await self._here(runtime)
        try:
            record = await runner.resume(task_id, runner=helpers, reason="at the lead's request")
        except WorkflowError as error:
            return str(error)
        return record.describe()
