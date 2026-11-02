"""`design-agent demo`: the real graph with a scripted model and no API keys.

Two turns on one thread: the sample brand's launch card in three sizes, then a 4-second HyperFrames
teaser of it. Everything renders inside the sandbox and passes the gates (brand-lint,
artifact-contract; video-gate and `hyperframes check` for the teaser) before it is delivered to
`workspace/out/demo/`. Docker (with the sandbox image) is the only requirement; when it is missing
the demo says exactly what to run.
"""

from __future__ import annotations

import asyncio
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from design_agent.config import SAMPLE_BRAND, Settings
from design_agent.runtime.local import build_local_runtime, final_text
from design_agent.runtime.sandbox import SandboxSelectionError, select_binding
from design_agent.testing.demo_script import (
    FAILED,
    SIZES,
    STILL_ASK,
    TEASER_ASK,
    still_steps,
    teaser_steps,
)
from design_agent.testing.scripted_model import ScriptedChatModel


@dataclass
class DemoResult:
    ok: bool
    reply: str
    outputs: list[Path] = field(default_factory=list)
    seconds: float = 0.0
    problems: list[str] = field(default_factory=list)


def _verify_outputs(folder: Path) -> tuple[list[Path], list[str]]:
    found: list[Path] = []
    problems: list[str] = []
    for width, height in SIZES:
        path = folder / f"card-{width}x{height}.png"
        if not path.is_file():
            problems.append(f"missing {path.name}")
            continue
        with Image.open(path) as image:
            if image.size != (width, height):
                problems.append(f"{path.name} is {image.size[0]}x{image.size[1]}")
            extrema = image.convert("L").getextrema()
            if extrema[0] == extrema[1]:
                problems.append(f"{path.name} is a blank frame")
        found.append(path)
    teaser = folder / "teaser.mp4"
    if teaser.is_file() and teaser.stat().st_size > 0:
        found.append(teaser)  # measured in the sandbox by artifact-contract before delivery
    else:
        problems.append("missing teaser.mp4")
    return found, problems


async def run_demo(project_root: Path, settings: Settings | None = None) -> DemoResult:
    # The scripted model writes the sample brand's tokens, fonts and logo, so the demo proves the
    # computer on that brand whatever pack is installed; `ask` is the first look at your own.
    settings = (settings or Settings()).model_copy(update={"brand_path": SAMPLE_BRAND})
    started = time.monotonic()
    binding = select_binding(settings, project_root)
    thread_id = f"demo-{uuid.uuid4().hex[:8]}"
    runtime = build_local_runtime(
        settings,
        project_root,
        model=ScriptedChatModel(steps=[*still_steps(), *teaser_steps()]),
        binding=binding,
    )
    replies: list[str] = []
    try:
        for ask in (STILL_ASK, TEASER_ASK):
            replies.append(final_text(await runtime.ask(ask, thread_id=thread_id)))
            if replies[-1].startswith(FAILED):
                break
    finally:
        if binding.runner is not None:
            binding.runner.stop_all()
    text = "\n\n".join(replies)
    failed = next((r for r in replies if r.startswith(FAILED)), "")
    delivered = runtime.out_dir / thread_id
    outputs, problems = _verify_outputs(delivered)
    if failed:
        problems.insert(0, failed.removeprefix(FAILED).strip())
    latest = runtime.out_dir / "demo"
    if outputs and not problems:
        shutil.rmtree(latest, ignore_errors=True)
        shutil.copytree(delivered, latest)
        outputs = [latest / p.name for p in outputs]
    return DemoResult(
        ok=not problems,
        reply=text,
        outputs=outputs,
        seconds=time.monotonic() - started,
        problems=problems,
    )


def demo_main(project_root: Path) -> int:
    try:
        result = asyncio.run(run_demo(project_root))
    except SandboxSelectionError as error:
        print(f"The demo needs a sandbox. {error}")
        print("Build the image once with:  uv run design-agent sandbox build")
        return 2
    print(result.reply)
    for path in result.outputs:
        print(f"  {path}")
    if not result.ok:
        print("Demo failed: " + "; ".join(result.problems))
        return 1
    print(
        f"Demo passed in {result.seconds:.0f} s: every gate green, 3 stills and a 4 s teaser delivered."
    )
    return 0
