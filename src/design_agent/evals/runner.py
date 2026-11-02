"""Run eval tasks against a real model and the Docker sandbox, then grade and report.

Each task runs on a fresh thread: the prompt, then each scripted follow-up (an approval at a
storyboard gate, say) once the agent has answered and its background work has settled. The run
stops at 1.5x the task's time budget. Results, delivered files and a human review checklist go to
the output folder (`docs/gallery/<run>/` for a published run).

This spends model and media money: `design-agent eval run` states the budget and asks first.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from design_agent.config import Settings
from design_agent.evals.graders import Exec, Grade, grade
from design_agent.evals.tasks import Task, TaskSet
from design_agent.evals.trace import Trace
from design_agent.middleware.meter import METER
from design_agent.runtime.local import LocalRuntime, build_local_runtime
from design_agent.runtime.sandbox import select_binding
from design_agent.runtime.sandbox.docker import tar_of

EVAL_ROOT = Path("tests") / "eval"


@dataclass
class TaskResult:
    task: str
    model: str
    status: str  # passed | failed | skipped | error
    seconds: float = 0.0
    usd: float = 0.0
    calls: int = 0
    failed_calls: int = 0
    repeated_calls: int = 0
    grades: list[Grade] = field(default_factory=list)
    note: str = ""

    @property
    def tool_precision(self) -> float:
        return 1.0 - (self.failed_calls / self.calls) if self.calls else 1.0


@contextmanager
def _environ(updates: Mapping[str, str]) -> Iterator[None]:
    saved = {k: os.environ.get(k) for k in updates}
    os.environ.update(updates)
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _repeated(trace: Trace) -> int:
    seen: set[str] = set()
    repeats = 0
    for call in trace.calls:
        key = json.dumps([call.name, call.args], sort_keys=True, default=str)
        repeats += key in seen
        seen.add(key)
    return repeats


async def run_task(
    task: Task, project_root: Path, model: str, out_root: Path, *, set_brand: str | None = None
) -> TaskResult:
    """Run one task. Its brand is its own (beside tasks.json), else the set's (from the project
    root), never the operator's: the prompts name the sample brand's product and copy."""
    missing = [name for name in task.needs if not os.environ.get(name)]
    if missing:
        return TaskResult(task.id, model, "skipped", note=f"needs {', '.join(missing)}")
    env = {**task.env, "DESIGN_AGENT_MODEL": model}
    if task.brand:
        env["DESIGN_AGENT_BRAND_PATH"] = str(project_root / EVAL_ROOT / task.brand)
    elif set_brand:
        env["DESIGN_AGENT_BRAND_PATH"] = str(project_root / set_brand)
    with _environ(env):
        settings = Settings()
    thread = f"eval-{task.id}-{int(time.time())}"
    posted: list[str] = []
    binding = select_binding(settings, project_root)
    runtime = build_local_runtime(
        settings,
        project_root,
        binding=binding,
        out_dir=out_root / "files",
        replies=lambda _t, text: posted.append(text),
    )
    started = time.monotonic()
    deadline = started + task.budget.minutes * 60 * 1.5
    result = TaskResult(task.id, model, "error")
    try:
        await _attach(runtime, task, project_root, thread)
        turns = [task.prompt, *task.follow_ups]
        for turn in turns:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                result.note = "time budget exceeded"
                break
            await asyncio.wait_for(runtime.ask(turn, thread_id=thread), timeout=remaining)
            await runtime.settle(
                timeout_seconds=max(1.0, deadline - time.monotonic()), poll_seconds=5
            )
        state = await runtime.graph.aget_state({"configurable": {"thread_id": thread}})
        trace = Trace.from_messages(
            list((state.values or {}).get("messages", [])), extra_replies=posted
        )
        run = _exec(runtime, thread)
        result.grades = grade(task, trace, runtime.out_dir / thread, run)
        result.calls = len(trace.calls)
        result.failed_calls = sum(1 for c in trace.calls if not c.ok)
        result.repeated_calls = _repeated(trace)
        result.usd = METER.summary(thread).usd
        within = result.usd <= task.budget.usd and not result.note
        result.status = "passed" if within and all(g.passed for g in result.grades) else "failed"
        (out_root / "traces").mkdir(parents=True, exist_ok=True)
        (out_root / "traces" / f"{task.id}.json").write_text(
            json.dumps(
                {"replies": trace.replies, "calls": [asdict(c) for c in trace.calls]},
                indent=1,
                default=str,
            )
        )
    except TimeoutError:
        result.note = "time budget exceeded"
        result.status = "failed"
    finally:
        result.seconds = time.monotonic() - started
        if binding.runner is not None:
            binding.runner.stop_all()
    return result


async def _attach(runtime: LocalRuntime, task: Task, project_root: Path, thread: str) -> None:
    """Put the task's attachments where a channel would: the thread's `/workspace/attachments/`."""
    if not task.attachments:
        return
    runner = runtime.binding.runner
    if runner is None:
        raise RuntimeError("attachments need the Docker sandbox (DESIGN_AGENT_SANDBOX=docker)")
    files = [
        (f"/workspace/attachments/{Path(a).name}", (project_root / EVAL_ROOT / a).read_bytes())
        for a in task.attachments
    ]
    await asyncio.to_thread(runner.put_archive, thread, tar_of(files), root=False)


def _exec(runtime: LocalRuntime, thread: str) -> Exec | None:
    runner = runtime.binding.runner
    if runner is None:
        return None

    def run(command: str) -> tuple[int, str]:
        response = runner.exec(thread, command, timeout=300)
        return int(response.exit_code or 0), str(response.output)

    return run


def summarize(results: Sequence[TaskResult]) -> dict[str, Any]:
    """Per model: success rate, cost per accepted task, time, tool precision, repeated calls."""
    by_model: dict[str, list[TaskResult]] = {}
    for result in results:
        by_model.setdefault(result.model, []).append(result)
    summary: dict[str, Any] = {}
    for model, rows in by_model.items():
        ran = [r for r in rows if r.status != "skipped"]
        passed = [r for r in ran if r.status == "passed"]
        spent = sum(r.usd for r in ran)
        summary[model] = {
            "ran": len(ran),
            "passed": len(passed),
            "success_rate": round(len(passed) / len(ran), 3) if ran else 0.0,
            "usd": round(spent, 2),
            "usd_per_accepted_task": round(spent / len(passed), 2) if passed else None,
            "minutes": round(sum(r.seconds for r in ran) / 60, 1),
            "tool_precision": round(sum(r.tool_precision for r in ran) / len(ran), 3)
            if ran
            else None,
            "repeated_calls": sum(r.repeated_calls for r in ran),
        }
    return summary


def write_report(results: Sequence[TaskResult], tasks: TaskSet, out_root: Path) -> Path:
    out_root.mkdir(parents=True, exist_ok=True)
    summary = summarize(results)
    (out_root / "report.json").write_text(
        json.dumps(
            {"summary": summary, "results": [asdict(r) for r in results]}, indent=2, default=str
        )
    )
    lines = [
        "# Eval run",
        "",
        "| Model | Ran | Passed | Cost (est.) | Per accepted task | Minutes | Tool precision |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for model, row in summary.items():
        per = (
            f"${row['usd_per_accepted_task']}" if row["usd_per_accepted_task"] is not None else "-"
        )
        lines.append(
            f"| `{model}` | {row['ran']} | {row['passed']} | ${row['usd']} | {per} | {row['minutes']} | {row['tool_precision']} |"
        )
    lines += [
        "",
        "## Tasks",
        "",
        "| Task | Model | Status | Failed checks |",
        "| --- | --- | --- | --- |",
    ]
    for r in results:
        failed = "; ".join(f"{g.name}: {g.detail}" for g in r.grades if not g.passed) or r.note
        lines.append(f"| {r.task} | `{r.model}` | {r.status} | {failed} |")
    lines += [
        "",
        "## Human review (fill in; no model judges taste)",
        "",
        "For each delivered file in `files/`: on brand (palette, type, logo use)? Concept, not wallpaper?",
        "Copy exact and no extra words? Would you send it? Note the reviewer and date outside the repository.",
        "",
        *(f"- [ ] {t.id}: " for t in tasks.tasks),
    ]
    (out_root / "README.md").write_text("\n".join(lines) + "\n")
    return out_root


def copy_task_files(out_root: Path) -> None:
    """Flatten delivered files into `files/<task>/` for review (they arrive per thread)."""
    files = out_root / "files"
    for thread_dir in [p for p in files.glob("eval-*") if p.is_dir()]:
        task = thread_dir.name.removeprefix("eval-").rsplit("-", 1)[0]
        target = files / task
        target.mkdir(exist_ok=True)
        for item in thread_dir.iterdir():
            shutil.move(str(item), target / item.name)
        thread_dir.rmdir()
