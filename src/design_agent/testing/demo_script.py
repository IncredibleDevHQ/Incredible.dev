"""The offline demo's scripted model: the steps a designer would take, through the real graph.

Each step reads what the previous tool printed and stops with `DEMO FAILED:` if a gate did not
pass, so the demo proves the gates, not just the script.
"""

from __future__ import annotations

from collections.abc import Sequence
from importlib.resources import files

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from design_agent.testing.scripted_model import (
    Step,
    last_json,
    last_tool_results,
    reply,
    tool_call,
    tool_calls,
)

STILL_ASK = (
    'Make a launch card announcing Example Studio 2.0 with the line "Every size, one pass." '
    "for LinkedIn portrait, square and landscape."
)
PROJECT = "/workspace/projects/launch-card"
SIZES: tuple[tuple[int, int], ...] = ((1080, 1350), (1080, 1080), (1600, 900))
FAILED = "DEMO FAILED:"


def card_html() -> str:
    return (
        files("design_agent.testing").joinpath("demo/launch-card.html").read_text(encoding="utf-8")
    )


def outputs() -> list[str]:
    return [f"{PROJECT}/renders/card-{w}x{h}.png" for w, h in SIZES]


def _exit_code(messages: Sequence[BaseMessage]) -> int | None:
    for message in last_tool_results(messages):
        text = str(message.content)
        marker = "exit code "
        if marker in text:
            tail = text.rsplit(marker, 1)[1].split()[0].strip(".]")
            if tail.lstrip("-").isdigit():
                return int(tail)
        if isinstance(message, ToolMessage) and message.status == "error":
            return -1
    return None


def _gate_failure(messages: Sequence[BaseMessage], gate: str) -> AIMessage | None:
    result = last_json(messages)
    if result.get("ok") is True:
        return None
    detail = "; ".join(
        str(f.get("message")) for f in result.get("findings", [])[:3] if isinstance(f, dict)
    )
    return reply(
        f"{FAILED} {gate} did not pass ({detail or 'no JSON summary, exit ' + str(_exit_code(messages))})."
    )


def still_steps() -> list[Step]:
    """Brief, compose, lint, render three sizes, check them, deliver, reply."""
    brief = (
        '# Launch card\n\nAnnounce Example Studio 2.0. Copy, exactly: "Example Studio 2.0" and '
        '"Every size, one pass." Sizes: 1080x1350, 1080x1080, 1600x900.\n'
    )

    def compose(_: Sequence[BaseMessage]) -> AIMessage:
        return tool_calls(
            ("write_file", {"file_path": f"{PROJECT}/BRIEF.md", "content": brief}),
            ("write_file", {"file_path": f"{PROJECT}/card.html", "content": card_html()}),
        )

    def lint(_: Sequence[BaseMessage]) -> AIMessage:
        return tool_call(
            "execute",
            {"command": f"node /workspace/tools/brand-lint.mjs {PROJECT}/card.html --json"},
        )

    def render(messages: Sequence[BaseMessage]) -> AIMessage:
        if failure := _gate_failure(messages, "brand-lint"):
            return failure
        sizes = " ".join(f"--size {w}x{h}" for w, h in SIZES)
        return tool_call(
            "execute",
            {
                "command": (
                    f"node /workspace/tools/html2png.mjs {PROJECT}/card.html --out {PROJECT}/renders "
                    f'--name card {sizes} --require-font "Geist" --require-font "Fragment Mono"'
                ),
                "timeout": 300,
            },
        )

    def check(messages: Sequence[BaseMessage]) -> AIMessage:
        if failure := _gate_failure(messages, "the renderer"):
            return failure
        expects = " ".join(
            f"--expect {path}:{w}x{h}" for path, (w, h) in zip(outputs(), SIZES, strict=True)
        )
        return tool_call(
            "execute", {"command": f"node /workspace/tools/artifact-contract.mjs {expects} --json"}
        )

    def deliver(messages: Sequence[BaseMessage]) -> AIMessage:
        if failure := _gate_failure(messages, "artifact-contract"):
            return failure
        return tool_call("upload_files", {"paths": outputs()})

    def answer(messages: Sequence[BaseMessage]) -> AIMessage:
        results = last_tool_results(messages)
        if not results or "Files uploaded." not in str(results[-1].content):
            return reply(f"{FAILED} delivery was not confirmed.")
        return reply(
            "Here's the launch card in portrait, square and landscape. I set the name in the display "
            "face with your line under the horizon rule, and kept the mark small in the corner so "
            "the announcement leads."
        )

    return [compose, lint, render, check, deliver, answer]


TEASER_ASK = "Now a 4-second 1920x1080 teaser of the same card for the launch post."
TEASER = f"{PROJECT}/teaser"
TEASER_OUT = f"{PROJECT}/renders/teaser.mp4"
TEASER_SECONDS = 4


def teaser_html() -> str:
    return files("design_agent.testing").joinpath("demo/teaser.html").read_text(encoding="utf-8")


def teaser_steps() -> list[Step]:
    """Compose a HyperFrames composition with local GSAP, gate it, render it, measure it, deliver."""

    def compose(_: Sequence[BaseMessage]) -> AIMessage:
        return tool_call(
            "write_file", {"file_path": f"{TEASER}/index.html", "content": teaser_html()}
        )

    def assets_and_gate(_: Sequence[BaseMessage]) -> AIMessage:
        # The sandbox renders offline: the brand files and GSAP are copied next to the composition.
        return tool_call(
            "execute",
            {
                "command": (
                    "cp /workspace/brand/tokens.css /workspace/brand/logos/mark.svg "
                    f"/opt/design-agent/render/node_modules/gsap/dist/gsap.min.js {TEASER}/ && "
                    f"node /workspace/tools/video-gate.mjs {TEASER}/index.html --json"
                )
            },
        )

    def lint(messages: Sequence[BaseMessage]) -> AIMessage:
        if failure := _gate_failure(messages, "video-gate"):
            return failure
        return tool_call(
            "execute",
            {"command": f"node /workspace/tools/brand-lint.mjs {TEASER}/index.html --json"},
        )

    def check(messages: Sequence[BaseMessage]) -> AIMessage:
        if failure := _gate_failure(messages, "brand-lint"):
            return failure
        return tool_call("execute", {"command": f"hyperframes check {TEASER}", "timeout": 300})

    def render(messages: Sequence[BaseMessage]) -> AIMessage:
        if _exit_code(messages) not in (0, None) or "Check passed" not in str(messages[-1].content):
            return reply(f"{FAILED} hyperframes check did not pass.")
        return tool_call(
            "execute",
            {
                "command": (
                    f"hyperframes render {TEASER} --quality draft --fps 30 --output {TEASER_OUT} --quiet"
                ),
                "timeout": 600,
            },
        )

    def measure(messages: Sequence[BaseMessage]) -> AIMessage:
        if _exit_code(messages) not in (0, None):
            return reply(f"{FAILED} the render exited {_exit_code(messages)}.")
        return tool_call(
            "execute",
            {
                "command": (
                    "node /workspace/tools/artifact-contract.mjs "
                    f"--expect {TEASER_OUT}:1920x1080@{TEASER_SECONDS} --json"
                )
            },
        )

    def deliver(messages: Sequence[BaseMessage]) -> AIMessage:
        if failure := _gate_failure(messages, "artifact-contract"):
            return failure
        return tool_call("upload_files", {"paths": [TEASER_OUT]})

    def answer(messages: Sequence[BaseMessage]) -> AIMessage:
        results = last_tool_results(messages)
        if not results or "Files uploaded." not in str(results[-1].content):
            return reply(f"{FAILED} delivery was not confirmed.")
        return reply(
            "Here's the 4-second teaser: the name rises in, the signal rule draws under it, and the "
            "line lands with almost two seconds left to read it."
        )

    return [compose, assets_and_gate, lint, check, render, measure, deliver, answer]
