"""Pipelines: productions whose control flow is code (`harness.workflow`, docs/harness/pipelines.md).

Each module holds one pipeline function, `async def fn(ctx, **args)`. `PIPELINES` names them;
`register_all` registers every one with a runner, and the host calls it where it builds its runner.
`catalog` describes them for the lead's `run_pipeline` tool.
"""

from __future__ import annotations

import inspect

from design_agent.harness.workflow import Pipeline, WorkflowRunner
from design_agent.pipelines.launch_film import launch_film

PIPELINES: dict[str, Pipeline] = {
    "launch_film": launch_film,
}


def register_all(runner: WorkflowRunner) -> WorkflowRunner:
    for name, fn in PIPELINES.items():
        runner.register(name, fn)
    return runner


def catalog() -> str:
    """One line per pipeline: its name, its arguments, and what it does."""
    lines = []
    for name, fn in PIPELINES.items():
        params = list(inspect.signature(fn).parameters.values())[1:]  # after ctx
        args = ", ".join(
            p.name if p.default is inspect.Parameter.empty else f"{p.name}={p.default!r}"
            for p in params
        )
        summary = " ".join((inspect.getdoc(fn) or "").split())
        lines.append(f"- {name}({args}): {summary}")
    return "\n".join(lines)
