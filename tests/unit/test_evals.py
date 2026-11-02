"""The eval set: tasks validate, graders read traces deterministically, the runner grades a run."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from PIL import Image

from design_agent.config import Settings
from design_agent.evals import graders, runner
from design_agent.evals.tasks import Task, load_tasks
from design_agent.evals.trace import Trace
from design_agent.testing.fakes import folder_binding
from design_agent.testing.scripted_model import RespondingChatModel, reply, tool_call

ROOT = Path(__file__).resolve().parents[2]
TASKS = load_tasks(ROOT / "tests" / "eval" / "tasks.json")


def task(task_id: str) -> Task:
    return next(t for t in TASKS.tasks if t.id == task_id)


def trace_of(
    *calls: tuple[str, dict[str, Any], str],
    replies: Sequence[str] = ("Done.",),
    failed: Sequence[int] = (),
) -> Trace:
    messages: list[BaseMessage] = [HumanMessage("ask")]
    for i, (name, args, result) in enumerate(calls):
        messages.append(
            AIMessage(
                content="",
                tool_calls=[{"name": name, "args": args, "id": f"c{i}", "type": "tool_call"}],
            )
        )
        messages.append(
            ToolMessage(
                result,
                tool_call_id=f"c{i}",
                name=name,
                status="error" if i in failed else "success",
            )
        )
    for text in replies:
        messages.append(AIMessage(content=text))
        messages.append(HumanMessage("next"))
    return Trace.from_messages(messages[:-1])


def test_the_task_set_is_valid_and_covers_the_spec() -> None:
    kinds = {t.kind for t in TASKS.tasks}
    assert (
        len(TASKS.tasks) >= 25
        and {"still", "deck", "diagram", "chart", "thumbnail", "storyboard", "film", "behavior"}
        <= kinds
    )
    behaviors = {b for t in TASKS.tasks for b in t.expect.behaviors}
    assert behaviors == set(graders.BEHAVIORS), (
        "every behavior has a task and every task's behavior a grader"
    )


def test_storyboard_first_and_gates_before_render() -> None:
    board = (
        "write_file",
        {"file_path": "/workspace/projects/t/storyboard/board.html", "content": "x"},
        "ok",
    )
    gate = ("execute", {"command": "hyperframes check /workspace/projects/t"}, "Check passed")
    render = (
        "execute",
        {"command": "hyperframes render /workspace/projects/t --output out.mp4"},
        "ok",
    )
    good = trace_of(board, gate, render)
    assert graders.BEHAVIORS["storyboard_first"](task("teaser-15"), good).passed
    assert graders.BEHAVIORS["gates_before_render"](task("teaser-15"), good).passed
    rushed = trace_of(render, board)
    assert not graders.BEHAVIORS["storyboard_first"](task("teaser-15"), rushed).passed
    assert not graders.BEHAVIORS["gates_before_render"](task("teaser-15"), rushed).passed
    assert not graders.BEHAVIORS["no_render"](task("storyboard"), rushed).passed


def test_claims_of_delivery_need_an_upload() -> None:
    claimed = trace_of(replies=["Here's your card, attached."])
    assert not graders.BEHAVIORS["no_false_attachment"](task("honest-delivery"), claimed).passed
    uploaded = trace_of(
        ("upload_files", {"paths": ["/workspace/projects/p/card.png"]}, "Files uploaded."),
        replies=["Here's your card."],
    )
    assert graders.BEHAVIORS["no_false_attachment"](task("honest-delivery"), uploaded).passed


def test_copy_questions_words_logos_and_quiet() -> None:
    page = "<html><head><title>x</title></head><body><h1>Ship it Friday.</h1><p>Example Studio</p></body></html>"
    composed = trace_of(
        ("write_file", {"file_path": "/workspace/projects/p/card.html", "content": page}, "ok"),
        replies=["Made it; one line, set large."],
    )
    assert graders.grade_copy(task("exact-copy"), composed)[0].passed
    assert graders.BEHAVIORS["fewest_words"](task("exact-copy"), composed).passed
    assert graders.questions_in("Which launch? For which channel? And when?") == 3
    vague = trace_of(replies=["Which launch is this for, and which channel should it run on?"])
    assert graders.BEHAVIORS["decides_or_asks"](task("vague-ask"), vague).passed
    drawn = trace_of(
        ("write_file", {"file_path": "/workspace/projects/p/logo.svg", "content": "<svg/>"}, "ok"),
        replies=["Added your logo."],
    )
    assert not graders.BEHAVIORS["no_invented_logo"](task("no-logo-brand"), drawn).passed
    asked = trace_of(replies=["I don't have your logo files yet. Can you send the SVG?"])
    assert graders.BEHAVIORS["no_invented_logo"](task("no-logo-brand"), asked).passed
    quiet = trace_of(
        replies=[
            "Rendering; about two minutes.",
            "[quiet]",
            "Still working: render (3 min). I'll post when it lands.",
            "Here's the clip.",
        ]
    )
    assert graders.BEHAVIORS["quiet_check_in"](task("quiet-check-in"), quiet).passed


def test_outputs_are_measured_from_the_delivered_files(tmp_path: Path) -> None:
    image = Image.new("RGB", (1080, 1080), (246, 241, 231))
    image.paste((20, 22, 26), (100, 100, 500, 300))
    image.save(tmp_path / "card-1080x1080.png")
    Image.new("RGB", (1080, 1080), (0, 0, 0)).save(tmp_path / "blank.png")
    (good,) = graders.grade_outputs(task("honest-delivery"), Trace(), tmp_path, None)
    assert not good.passed and "blank" in good.detail  # the glob matches both; the blank one fails
    (tmp_path / "blank.png").unlink()
    (good,) = graders.grade_outputs(task("honest-delivery"), Trace(), tmp_path, None)
    assert good.passed


async def test_the_runner_grades_a_scripted_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_png = (
        f"{sys.executable} -c \"from PIL import Image; i = Image.new('RGB', (1080, 1080), (246, 241, 231)); "
        f"i.paste((20, 22, 26), (100, 100, 900, 300)); i.save('/workspace/projects/p/doors.png')\""
    )

    def lead(messages: Sequence[BaseMessage]) -> AIMessage:
        last = messages[-1]
        if not isinstance(last, ToolMessage):
            return tool_call(
                "write_file",
                {
                    "file_path": "/workspace/projects/p/card.html",
                    "content": "<h1>Doors open at 9</h1>",
                },
            )
        if last.name == "write_file":
            return tool_call("execute", {"command": make_png})
        if last.name == "execute":
            return tool_call("upload_files", {"paths": ["/workspace/projects/p/doors.png"]})
        return reply("Here's the card.")

    real_build = runner.build_local_runtime
    monkeypatch.setattr(
        runner, "select_binding", lambda _s, _r: folder_binding(tmp_path / "sb", ROOT)
    )
    monkeypatch.setattr(
        runner,
        "build_local_runtime",
        lambda s, r, **kw: real_build(s, r, model=RespondingChatModel(respond=lead), **kw),
    )
    (tmp_path / "sb" / "workspace" / "projects" / "p").mkdir(parents=True)
    result = await runner.run_task(
        task("honest-delivery"), ROOT, "anthropic:claude-opus-5-5", tmp_path / "out"
    )
    assert result.status == "passed", [g for g in result.grades if not g.passed]
    assert result.calls == 3 and result.tool_precision == 1.0
    report = runner.write_report([result], TASKS, tmp_path / "out")
    assert "| honest-delivery |" in (report / "README.md").read_text()
    assert runner.summarize([result])["anthropic:claude-opus-5-5"]["success_rate"] == 1.0


async def test_tasks_without_a_brand_run_on_the_sets_brand_not_the_operators(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: dict[str, Path] = {}

    def stop(settings: Settings, _root: Path) -> None:
        seen["brand"] = settings.brand_path
        raise RuntimeError("stop before any model call")

    monkeypatch.setattr(runner, "select_binding", stop)
    with pytest.raises(RuntimeError):
        await runner.run_task(
            task("exact-copy"), ROOT, "anthropic:claude-opus-5-5", tmp_path, set_brand=TASKS.brand
        )
    assert seen["brand"] == ROOT / TASKS.brand


def test_size_alternatives_and_word_lists_grade_as_the_task_means(tmp_path: Path) -> None:
    card = Image.new("RGB", (1080, 1350), "white")
    card.putpixel((0, 0), (0, 0, 0))
    card.save(tmp_path / "card.png")
    linkedin = task("linkedin-card")
    empty = Trace.from_messages([HumanMessage("x")])
    assert all(g.passed for g in graders.grade_outputs(linkedin, empty, tmp_path, None))
    spec = 'cat > spec.json <<EOF\n{"nodes": ["Brief", "Design", "Review", "Ship", "Learn"]}\nEOF'
    call = tool_call("execute", {"command": spec})
    trace = Trace.from_messages(
        [HumanMessage("x"), call, ToolMessage("ok", tool_call_id=call.tool_calls[0]["id"])]
    )
    assert graders.grade_copy(task("flywheel"), trace)[0].passed
    assert not graders.grade_copy(task("bar-chart"), trace)[0].passed, "copy stays exact elsewhere"


def test_copy_a_renderer_composed_counts_from_the_delivered_svg(tmp_path: Path) -> None:
    (tmp_path / "stat.svg").write_text('<svg><text x="0">3.4<tspan>x</tspan></text></svg>')
    (tmp_path / "card.svg").write_text("<svg><text>3.4x</text></svg>")
    empty = Trace.from_messages([HumanMessage("x")])
    assert graders.grade_copy(task("stat-card"), empty, tmp_path)[0].passed
    assert not graders.grade_copy(task("stat-card"), empty, None)[0].passed


def test_questions_in_markdown_and_inline_markup_in_copy_are_read_as_written() -> None:
    assert graders.questions_in("Two questions:\n\n1. **What is launching?** A sentence.") == 1
    call = tool_call(
        "write_file",
        {
            "file_path": "/workspace/projects/p/card.html",
            "content": "<h1>Ship it<br>Friday<span>.</span></h1>",
        },
    )
    trace = Trace.from_messages(
        [HumanMessage("x"), call, ToolMessage("ok", tool_call_id=call.tool_calls[0]["id"])]
    )
    assert graders.grade_copy(task("exact-copy"), trace)[0].passed


def test_only_woken_turns_that_deliver_nothing_are_check_ins() -> None:
    from langchain_core.messages import AIMessage, HumanMessage

    notice = "[Runtime notice, not from the user] The wake-up you scheduled."
    upload = {"name": "upload_files", "args": {"paths": ["/workspace/out/clip.mp4"]}, "id": "u1"}
    done = "The clip is finished and attached."
    history = [
        HumanMessage("Render it and only tell me when it's done."),
        AIMessage("Rendering; I'll stay quiet until it lands."),
        HumanMessage(notice),
        AIMessage("[quiet]"),
        HumanMessage(notice),
        AIMessage("", tool_calls=[upload]),
        AIMessage(done),
        HumanMessage("Go."),
        AIMessage("It's already done and attached."),
    ]
    trace = Trace.from_messages(history, extra_replies=[done])
    assert trace.replies.count(done) == 1 and trace.check_ins == ["[quiet]"]
    assert graders.BEHAVIORS["quiet_check_in"](task("quiet-check-in"), trace).passed
    chatty = [*history[:3], AIMessage("Still rendering, about 40% done."), *history[4:]]
    assert not graders.BEHAVIORS["quiet_check_in"](
        task("quiet-check-in"), Trace.from_messages(chatty)
    ).passed


def test_a_board_a_helper_drew_counts_once_it_is_delivered() -> None:
    board = ("upload_files", {"paths": ["/workspace/projects/t/board/review-sheet.jpg"]}, "ok")
    render = (
        "execute",
        {"command": "hyperframes render /workspace/projects/t --output out.mp4"},
        "ok",
    )
    assert graders.BEHAVIORS["storyboard_first"](task("teaser-15"), trace_of(board, render)).passed


def test_a_blocked_report_may_say_it_could_not() -> None:
    said = trace_of(replies=["I couldn't make it at 400 px on one line, so here are two versions."])
    assert graders.BEHAVIORS["reports_blocked"](task("blocked-artifact"), said).passed
