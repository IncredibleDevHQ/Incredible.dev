"""Observe an episode render on its own computer, even across a container restart."""

from __future__ import annotations

import json
import shlex
from typing import Any

from design_agent.surfaces.web.computer import GSAP


def launch(folder: str, attempt: str, size: str = "hd") -> str:
    # The shell stays with the child and publishes its exit code before it can disappear. A film
    # in 4K is the same page rendered at twice the density (HyperFrames' own 4K).
    density = " --resolution 4k" if size == "4k" else ""
    worker = (
        f"hyperframes render . --quality looks --fps 30{density} --output out/episode.mp4 "
        '>render.log 2>&1; echo "$?" >render.exit.tmp && mv render.exit.tmp render.exit'
    )
    return (
        f"cd {shlex.quote(folder)} && cp -n {GSAP} gsap.min.js && "
        f"(nohup sh -c {shlex.quote(worker)} {shlex.quote(attempt)} </dev/null >/dev/null 2>&1 & "
        'echo "$!" >render.pid)'
    )


def probe(folder: str, attempt: str) -> str:
    # A PID can be reused after a restart. Match the supervisor's unique final argument.
    # Recheck the exit file on disappearance to cover an exit during the process check.
    return (
        f"cd {shlex.quote(folder)} || exit 1; "
        "if test -s render.exit; then cat render.exit; echo; "
        "else pid=$(cat render.pid 2>/dev/null); "
        'case "$(ps -ww -p "$pid" -o args= 2>/dev/null)" in '
        f'*" "{shlex.quote(attempt)}) echo running ;; '
        "*) if test -s render.exit; then cat render.exit; echo; else echo stopped; fi ;; esac; fi; "
        "tail -c 16384 render.log 2>/dev/null | tr '\\r' '\\n' | grep '^@hf-progress ' | tail -1"
    )


def progress(output: str) -> dict[str, Any]:
    for line in reversed(output.splitlines()):
        if line.startswith("@hf-progress "):
            try:
                event = json.loads(line.removeprefix("@hf-progress "))
            except ValueError:
                continue
            if not isinstance(event, dict) or type(event.get("pct")) not in (int, float):
                continue
            pct = event["pct"]
            if not 0 <= pct <= 100:
                continue
            phase = event.get("code")
            update = {"fraction": pct / 100, "phase": phase if isinstance(phase, str) else "render"}
            done, total = event.get("done"), event.get("total")
            if (
                phase == "capture"
                and type(done) is int
                and type(total) is int
                and 0 <= done <= total
                and total > 0
            ):
                update.update(frames_done=done, frames_total=total)
            return update
    return {}
