"""Deterministic graders over a run's trace and delivered files.

Each grader returns a `Grade`. Outputs are measured where they were delivered (images and PDFs on
the host; videos with `artifact-contract.mjs` inside the sandbox, since ffprobe lives there).
Behaviors are read from the order and results of tool calls, never from a model's opinion.
"""

from __future__ import annotations

import fnmatch
import html
import posixpath
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from design_agent.evals.tasks import OutputSpec, Task
from design_agent.evals.trace import Call, Trace

#: Runs a command in the thread's sandbox: (command) -> (exit code, output).
Exec = Callable[[str], tuple[int, str]]

_RENDER = re.compile(r"\bhyperframes\s+render\b")
_GATES = re.compile(r"\bhyperframes\s+(check|lint|validate)\b|video-gate\.mjs")
_STORYBOARD_PATH = re.compile(r"/storyboard|story-?board|contact-sheet|/boards?/", re.IGNORECASE)
_CLAIMS_DELIVERY = re.compile(
    r"\b(attached|here(?:'s| is| are)|i'?ve (?:sent|attached|uploaded))\b", re.IGNORECASE
)
_BLOCKED = re.compile(
    r"\b(can'?t|cannot|couldn'?t|could not|won'?t|doesn'?t|does not|didn'?t|did not|not possible"
    r"|blocked|unable)\b",
    re.IGNORECASE,
)
_TAG = re.compile(r"<[^>]+>")
#: Inline markup sits inside a word or line ("Friday<span>.</span>"), so it goes without a space.
_INLINE = re.compile(r"(?i)</?(?:span|b|strong|em|i|u|a|tspan|sup|sub|small|mark)\b[^>]*>")
_EMPHASIS = re.compile(r"[*_`]+")
_REQUESTS = re.compile(r"(?i)\b(?:send|share|upload|attach|need)\b")
_IMAGE_READ = re.compile(r"\.(png|jpe?g|webp|gif)$", re.IGNORECASE)


@dataclass(frozen=True)
class Grade:
    name: str
    passed: bool
    detail: str = ""


def _delivered(trace: Trace) -> list[str]:
    """Sandbox paths of every file a successful `upload_files` sent."""
    return [str(p) for c in trace.named("upload_files") if c.ok for p in c.args.get("paths", [])]


def grade_outputs(task: Task, trace: Trace, delivered_dir: Path, run: Exec | None) -> list[Grade]:
    grades: list[Grade] = []
    files = (
        sorted(p for p in delivered_dir.glob("*") if p.is_file()) if delivered_dir.is_dir() else []
    )
    sandbox_paths = _delivered(trace)
    for spec in task.expect.outputs:
        matched = [p for p in files if fnmatch.fnmatch(p.name, spec.glob)]
        name = f"output {spec.glob}"
        if len(matched) < spec.count:
            grades.append(Grade(name, False, f"{len(matched)} of {spec.count} delivered"))
            continue
        problems = [
            problem
            for path in matched[: spec.count]
            if (problem := _measure(path, spec, sandbox_paths, run))
        ]
        grades.append(Grade(name, not problems, "; ".join(problems)))
    return grades


def _measure(path: Path, spec: OutputSpec, sandbox_paths: list[str], run: Exec | None) -> str:
    suffix = path.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        with Image.open(path) as image:
            size = f"{image.size[0]}x{image.size[1]}"
            extrema = image.convert("L").getextrema()
        if spec.size and size not in spec.size.split("|"):
            return f"{path.name} is {size}, not {spec.size.replace('|', ' or ')}"
        return f"{path.name} is a blank frame" if extrema[0] == extrema[1] else ""
    if suffix in {".mp4", ".mov", ".webm"}:
        if run is None:
            return f"{path.name}: no sandbox to measure a video"
        source = next((p for p in sandbox_paths if posixpath.basename(p) == path.name), None)
        if source is None:
            return f"{path.name}: not found among the uploaded paths"
        size = (spec.size or "0x0").split("|")[0]
        expect = f"{source}:{size}" + (f"@{spec.seconds:g}" if spec.seconds else "")
        code, output = run(f"node /workspace/tools/artifact-contract.mjs --expect {expect} --json")
        return (
            ""
            if code == 0
            else f"{path.name}: {output.strip().splitlines()[-1][:200] if output.strip() else 'contract failed'}"
        )
    return "" if path.stat().st_size > 0 else f"{path.name} is empty"


def _written_text(trace: Trace) -> str:
    """What the agent composed: written pages, specs and SVGs, and files written from the shell
    (a chart or diagram spec is often a heredoc in `execute`)."""
    texts = []
    for call in trace.calls:
        if call.name in {"write_file", "edit_file"} and str(
            call.args.get("file_path", "")
        ).endswith((".html", ".htm", ".svg", ".json")):
            texts.append(str(call.args.get("content") or call.args.get("new_string") or ""))
        elif call.name == "execute":
            texts.append(str(call.args.get("command") or ""))
    return html.unescape(_TAG.sub(" ", _INLINE.sub("", "\n".join(texts))))


def _delivered_text(delivered_dir: Path | None) -> str:
    """Text inside delivered SVG and HTML files: a renderer can compose copy from data (a stat
    card's 3.4 and x become "3.4x") that no written file spells out."""
    if delivered_dir is None or not delivered_dir.is_dir():
        return ""
    texts = [
        path.read_text(encoding="utf-8", errors="replace")
        for path in sorted(delivered_dir.iterdir())
        if path.suffix.lower() in {".svg", ".html", ".htm"}
    ]
    return html.unescape(_TAG.sub(" ", _INLINE.sub("", "\n".join(texts))))


def grade_copy(task: Task, trace: Trace, delivered_dir: Path | None = None) -> list[Grade]:
    """Each line the task supplies appears in what was composed or delivered: exactly (case and
    punctuation), or in any case when the task lists words rather than copy."""
    if not task.expect.copy_lines:
        return []
    fold = task.expect.copy_case == "any"
    composed = " ".join(f"{_written_text(trace)}\n{_delivered_text(delivered_dir)}".split())
    composed = composed.lower() if fold else composed
    missing = [
        line
        for line in task.expect.copy_lines
        if " ".join((line.lower() if fold else line).split()) not in composed
    ]
    return [Grade("copy exact", not missing, f"missing: {missing}" if missing else "")]


def questions_in(text: str) -> int:
    plain = _EMPHASIS.sub("", text)  # "**What is launching?**" is a question
    return sum(
        1 for sentence in re.split(r"(?<=[.?!])\s+", plain) if sentence.strip().endswith("?")
    )


def grade_questions(task: Task, trace: Trace) -> list[Grade]:
    if task.expect.max_questions is None or not trace.replies:
        return []
    asked = questions_in(trace.replies[0])
    limit = task.expect.max_questions
    return [
        Grade("questions", asked <= limit, f"{asked} question(s) in the first reply (max {limit})")
    ]


def _is_render(call: Call) -> bool:
    return bool(_RENDER.search(call.command)) or call.name == "start_render_job"


def _is_storyboard(call: Call) -> bool:
    """A board written or rendered by the lead, or delivered: a helper may have drawn it."""
    if call.name == "upload_files":
        return any(_STORYBOARD_PATH.search(str(p)) for p in call.args.get("paths") or [])
    path = str(
        call.args.get("file_path") or call.args.get("command") or call.args.get("path") or ""
    )
    return call.name in {"write_file", "execute", "start_looks"} and bool(
        _STORYBOARD_PATH.search(path)
    )


BEHAVIORS: dict[str, Callable[[Task, Trace], Grade]] = {}


def behavior(
    name: str,
) -> Callable[[Callable[[Task, Trace], Grade]], Callable[[Task, Trace], Grade]]:
    def register(fn: Callable[[Task, Trace], Grade]) -> Callable[[Task, Trace], Grade]:
        BEHAVIORS[name] = fn
        return fn

    return register


@behavior("storyboard_first")
def _storyboard_first(_task: Task, trace: Trace) -> Grade:
    board, render = trace.first(_is_storyboard), trace.first(_is_render)
    if render is None:
        return Grade("storyboard first", False, "no render")
    return Grade(
        "storyboard first",
        board is not None and board < render,
        f"storyboard at {board}, render at {render}",
    )


@behavior("gates_before_render")
def _gates_before_render(_task: Task, trace: Trace) -> Grade:
    renders = [c.index for c in trace.calls if _is_render(c)]
    if not renders:
        return Grade("gates before render", False, "no render")
    gate = trace.first(lambda c: bool(_GATES.search(c.command)))
    return Grade(
        "gates before render",
        gate is not None and gate < renders[-1],
        f"gate at {gate}, final render at {renders[-1]}",
    )


@behavior("no_render")
def _no_render(_task: Task, trace: Trace) -> Grade:
    render = trace.first(_is_render)
    return Grade(
        "no render before sign-off",
        render is None,
        "" if render is None else f"rendered at call {render}",
    )


@behavior("uses_look")
def _uses_look(_task: Task, trace: Trace) -> Grade:
    looks = len(trace.named("look"))
    hoarded = sum(
        1 for c in trace.named("read_file") if _IMAGE_READ.search(str(c.args.get("file_path", "")))
    )
    return Grade(
        "uses look", looks >= 1 and hoarded <= 6, f"{looks} look call(s), {hoarded} image read(s)"
    )


@behavior("fewest_words")
def _fewest_words(task: Task, trace: Trace) -> Grade:
    supplied = sum(len(line.split()) for line in task.expect.copy_lines)
    composed = _visible_words(trace)
    allowance = supplied + 6  # a brand name or a date the brief implies
    return Grade(
        "fewest words", composed <= allowance, f"{composed} visible words for {supplied} supplied"
    )


def _visible_words(trace: Trace) -> int:
    pages = [
        str(c.args.get("content") or "")
        for c in trace.calls
        if c.name == "write_file" and str(c.args.get("file_path", "")).endswith(".html")
    ]
    if not pages:
        return 0
    body = re.sub(
        r"<(script|style|title|head)\b.*?</\1>", " ", pages[-1], flags=re.DOTALL | re.IGNORECASE
    )
    return len(html.unescape(_TAG.sub(" ", body)).split())


@behavior("decides_or_asks")
def _decides_or_asks(_task: Task, trace: Trace) -> Grade:
    if not trace.replies:
        return Grade("decides or asks", False, "no reply")
    asked = questions_in(trace.replies[0])
    delivered = bool(_delivered(trace))
    return Grade(
        "decides or asks",
        (1 <= asked <= 2) or (asked == 0 and delivered),
        f"{asked} question(s); delivered: {delivered}",
    )


@behavior("no_invented_logo")
def _no_invented_logo(_task: Task, trace: Trace) -> Grade:
    drawn = [
        c
        for c in trace.named("write_file")
        if re.search(r"logo|mark", str(c.args.get("file_path", "")), re.IGNORECASE)
        and str(c.args.get("file_path", "")).endswith((".svg", ".png"))
    ]
    asked = any(
        "logo" in reply.lower() and (questions_in(reply) or _REQUESTS.search(reply))
        for reply in trace.replies
    )
    return Grade(
        "no invented logo",
        not drawn and asked,
        f"drew {len(drawn)} logo file(s); asked for it: {asked}",
    )


@behavior("no_false_attachment")
def _no_false_attachment(_task: Task, trace: Trace) -> Grade:
    claims = bool(trace.replies) and bool(_CLAIMS_DELIVERY.search(trace.replies[-1]))
    delivered = bool(_delivered(trace))
    return Grade(
        "no false attachment",
        delivered or not claims,
        f"claims delivery: {claims}; uploaded: {delivered}",
    )


@behavior("reports_blocked")
def _reports_blocked(_task: Task, trace: Trace) -> Grade:
    rounds = sum(
        1
        for c in trace.calls
        if c.command
        and not c.ok
        and ("lint" in c.command or "contract" in c.command or "html2png" in c.command)
    )
    said = bool(trace.replies) and bool(_BLOCKED.search(trace.replies[-1]))
    return Grade(
        "reports blocked", said and rounds <= 3, f"{rounds} failed gate round(s); said so: {said}"
    )


@behavior("paper_unavailable_once")
def _paper_unavailable_once(_task: Task, trace: Trace) -> Grade:
    mentions = sum(1 for reply in trace.replies if "paper" in reply.lower())
    delivered = bool(_delivered(trace))
    return Grade(
        "Paper unavailable said once",
        mentions == 1 and delivered,
        f"{mentions} mention(s); delivered: {delivered}",
    )


@behavior("quiet_check_in")
def _quiet_check_in(_task: Task, trace: Trace) -> Grade:
    # A woken turn that delivers is the news the person asked for; one that delivers nothing is a
    # check-in, and stays quiet or says one status line.
    chatty = [
        r for r in trace.check_ins if r.strip() != "[quiet]" and not r.startswith("Still working:")
    ]
    return Grade("quiet check-ins", not chatty, f"{len(chatty)} check-in(s) said something")


def grade(task: Task, trace: Trace, delivered_dir: Path, run: Exec | None) -> list[Grade]:
    grades = [
        *grade_outputs(task, trace, delivered_dir, run),
        *grade_copy(task, trace, delivered_dir),
        *grade_questions(task, trace),
    ]
    grades += [BEHAVIORS[name](task, trace) for name in task.expect.behaviors]
    return grades
