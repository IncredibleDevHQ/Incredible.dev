"""Research on the canvas: a frame that reads one of the person's repositories, questions asked of
a coding agent on this computer (read-only, signed in as the person), conversations that branch
from a passage, notes kept from the answers, and the frame's assets made from those notes."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest

from design_agent.config import Settings
from design_agent.surfaces.web.agent import AgentHost
from design_agent.surfaces.web.hub import Hub
from design_agent.surfaces.web.research import (
    CLAUDE_BLOCKED,
    GUIDE,
    HARNESSES,
    Event,
    clean_env,
    command,
    find_repos,
    parse,
)
from design_agent.surfaces.web.research_desk import RESEARCH, ResearchDesk
from design_agent.surfaces.web.store import AGENT_ID, CONVERSATION, Store
from tests.unit.test_web_surface import FakeBackend, FakeRuntime

ANSWER = "Sessions outlive requests.\n\n## Why\n\nA Durable Object renews them."


class FakeRunner:
    """Plays a run's events; `hold` keeps it answering until released."""

    def __init__(self, script: list[Event] | None = None) -> None:
        self.script = script or [
            Event("session", "s-1"),
            Event("step", "Reading README.md"),
            Event("note", "Reading the session code."),
            Event("step", "Searching for “expiry”"),
            Event("answer", ANSWER),
        ]
        self.calls: list[dict[str, Any]] = []
        self.hold: asyncio.Event | None = None

    async def __call__(
        self, harness: str, *, repo: Path, prompt: str, session: str, profile: Path
    ) -> AsyncGenerator[Event, None]:
        self.calls.append({"harness": harness, "repo": repo, "prompt": prompt, "session": session})
        for event in self.script:
            if self.hold is not None and event.kind == "answer":
                await self.hold.wait()
            yield event


def _repo(root: Path, name: str, *, branch: str = "main") -> Path:
    folder = root / name
    (folder / ".git").mkdir(parents=True)
    (folder / ".git" / "HEAD").write_text(f"ref: refs/heads/{branch}\n")
    return folder


@pytest.fixture
def house(tmp_path: Path) -> tuple[AgentHost, FakeRunner, Path]:
    code = tmp_path / "code"
    repo = _repo(code, "streamline")
    runtime = FakeRuntime(FakeBackend({}))
    agent = AgentHost(
        settings=Settings(), store=Store(tmp_path / "house.sqlite"), hub=Hub(), data_dir=tmp_path
    )
    agent.runtime = runtime  # type: ignore[assignment]
    runner = FakeRunner()
    agent.research = ResearchDesk(
        store=agent.store,
        hub=agent.hub,
        data_dir=tmp_path,
        roots=[code],
        runner=runner,
        ready=lambda harness: True,
    )
    return agent, runner, repo


async def _settle(desk: ResearchDesk) -> None:
    await asyncio.gather(*list(desk._runs.values()))


def _channel(agent: AgentHost) -> str:
    return str(agent.store.channels()[0]["id"])


# -- each CLI's stream, read --------------------------------------------------------------


def test_claude_codes_stream_is_read_as_steps_and_an_answer(tmp_path: Path) -> None:
    lines = [
        {"type": "system", "subtype": "init", "session_id": "d574", "permissionMode": "plan"},
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "thinking", "thinking": ""},
                    {
                        "type": "tool_use",
                        "name": "Read",
                        "input": {"file_path": f"{tmp_path}/src/a.go"},
                    },
                    {"type": "tool_use", "name": "Grep", "input": {"pattern": "onActivityExpired"}},
                ]
            },
        },
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": "..."}]}},
        {"type": "result", "subtype": "success", "is_error": False, "result": "It renews."},
    ]
    events = [e for line in lines for e in parse("claude", json.dumps(line), tmp_path)]
    assert events == [
        Event("session", "d574"),
        Event("step", "Reading src/a.go"),
        Event("step", "Searching for “onActivityExpired”"),
        Event("answer", "It renews."),
    ]
    failed = {"type": "result", "subtype": "error_max_turns", "is_error": True, "result": ""}
    assert parse("claude", json.dumps(failed), tmp_path) == [
        Event("error", "It stopped before answering.")
    ]


def test_codex_and_kimi_streams_are_read_too(tmp_path: Path) -> None:
    codex = [
        {"type": "thread.started", "thread_id": "01a1"},
        {"type": "item.completed", "item": {"type": "agent_message", "text": "I'll read it."}},
        {
            "type": "item.started",
            "item": {"type": "command_execution", "command": "/bin/zsh -lc 'cat README.md'"},
        },
        {"type": "item.completed", "item": {"type": "agent_message", "text": "A pipeline."}},
        {"type": "turn.completed", "usage": {}},
    ]
    assert [e for line in codex for e in parse("codex", json.dumps(line), tmp_path)] == [
        Event("session", "01a1"),
        Event("note", "I'll read it."),
        Event("step", "Running cat README.md"),
        Event("note", "A pipeline."),
    ]
    kimi = [
        {"role": "meta", "type": "system.version", "version": "2.2.0"},
        {
            "role": "assistant",
            "tool_calls": [
                {"function": {"name": "Read", "arguments": json.dumps({"path": "README.md"})}}
            ],
        },
        {"role": "tool", "content": "..."},
        {"role": "assistant", "content": "A design agent."},
        {"role": "meta", "type": "session.resume_hint", "session_id": "session_6e0e"},
    ]
    assert [e for line in kimi for e in parse("kimi", json.dumps(line), tmp_path)] == [
        Event("step", "Reading README.md"),
        Event("note", "A design agent."),
        Event("session", "session_6e0e"),
    ]
    assert parse("kimi", "not json", tmp_path) == []


def test_every_agent_runs_read_only_with_the_prompt_kept_out_of_its_options(
    tmp_path: Path,
) -> None:
    profile = tmp_path / "researcher.md"
    claude, said = command(
        HARNESSES["claude"], "claude", repo=tmp_path, prompt="-why?", session="", profile=profile
    )
    assert claude[:2] == ["claude", "-p"]
    assert "plan" in claude and f"--disallowedTools={CLAUDE_BLOCKED}" in claude
    assert "-why?" not in claude and said == "-why?"
    again, _ = command(
        HARNESSES["claude"], "claude", repo=tmp_path, prompt="and?", session="s1", profile=profile
    )
    assert again[-2:] == ["--resume", "s1"]

    codex, said = command(
        HARNESSES["codex"], "codex", repo=tmp_path, prompt="why?", session="", profile=profile
    )
    assert codex[codex.index("--sandbox") + 1] == "read-only"
    assert codex[codex.index("--cd") + 1] == str(tmp_path)
    assert codex[-1] == "-" and said == f"{GUIDE}\n\nwhy?"
    resumed, said = command(
        HARNESSES["codex"], "codex", repo=tmp_path, prompt="and?", session="01a1", profile=profile
    )
    assert resumed[1:3] == ["exec", "resume"] and 'sandbox_mode="read-only"' in resumed
    assert resumed[-2:] == ["01a1", "-"] and said == "and?"

    kimi, said = command(
        HARNESSES["kimi"], "kimi", repo=tmp_path, prompt="-why?", session="", profile=profile
    )
    assert kimi[kimi.index("--agent-file") + 1] == str(profile)
    assert "--prompt=-why?" in kimi and said is None


def test_an_agent_gets_none_of_the_houses_environment() -> None:
    env = clean_env(
        {
            "HOME": "/Users/k",
            "PATH": "/usr/bin",
            "CLAUDECODE": "1",
            "CLAUDE_CODE_SESSION_ID": "x",
            "ANTHROPIC_BASE_URL": "http://proxy",
            "OPENAI_API_KEY": "sk-test",
            "DESIGN_AGENT_MODEL": "openai:gpt",
        }
    )
    assert env["HOME"] == "/Users/k"
    assert env["PATH"].split(os.pathsep)[0] == os.path.expanduser("~/.local/bin")
    assert env["PATH"].endswith("/usr/bin")
    assert not {
        "CLAUDECODE",
        "CLAUDE_CODE_SESSION_ID",
        "ANTHROPIC_BASE_URL",
        "OPENAI_API_KEY",
    } & set(env)
    assert "DESIGN_AGENT_MODEL" not in env


def test_repositories_are_found_newest_first_without_dependencies(tmp_path: Path) -> None:
    old = _repo(tmp_path, "old")
    new = _repo(tmp_path, "new", branch="feat/x")
    nested = _repo(tmp_path / "group", "inner")
    _repo(tmp_path / "node_modules", "pkg")
    _repo(tmp_path / ".hidden", "secret")
    worktree = tmp_path / "wt"
    worktree.mkdir()
    gitdir = old / ".git" / "worktrees" / "wt"
    gitdir.mkdir(parents=True)
    (gitdir / "HEAD").write_text("ref: refs/heads/review\n")
    (worktree / ".git").write_text(f"gitdir: {gitdir}\n")
    os.utime(old / ".git" / "HEAD", (1, 1))
    os.utime(nested / ".git" / "HEAD", (2, 2))
    repos = find_repos([tmp_path])
    by_name = {r.name: r for r in repos}
    assert set(by_name) == {"old", "new", "inner", "wt"}
    assert by_name["new"].branch == "feat/x" and by_name["wt"].branch == "review"
    assert repos[-1].path == old.resolve()
    assert find_repos([new]) == [by_name["new"]]


# -- a research frame on the canvas ---------------------------------------------------------


async def test_a_research_frame_asks_its_first_question_and_files_the_answer(
    house: tuple[AgentHost, FakeRunner, Path],
) -> None:
    agent, runner, repo = house
    frame, conversation = agent.research.open(
        _channel(agent), by="you", repo=str(repo), harness="claude", question="Why sessions?"
    )
    await _settle(agent.research)

    assert frame["task"] and frame["kind"] == RESEARCH and frame["title"] == "Research: streamline"
    assert runner.calls == [
        {"harness": "claude", "repo": repo.resolve(), "prompt": "Why sessions?", "session": ""}
    ]
    thread = agent.store.thread(conversation["id"])
    assert thread is not None and thread["kind"] == CONVERSATION and thread["status"] == "idle"
    question, turn, answer = agent.store.messages(conversation["id"])
    assert question["text"] == "Why sessions?" and question["author_id"] == "you"
    assert turn["kind"] == "turn" and turn["data"]["state"] == "done"
    assert [s["title"] for s in turn["data"]["steps"]] == [
        "Reading README.md",
        "Searching for “expiry”",
    ]
    assert {s["status"] for s in turn["data"]["steps"]} == {"done"}
    assert answer["kind"] == "agent" and answer["author_id"] == AGENT_ID
    assert answer["text"] == ANSWER and answer["data"]["mark"] == "claude"
    assert agent.store.conversation(conversation["id"])["session"] == "s-1"  # type: ignore[index]

    # The frame is on the canvas with its research; the conversation is not in the channel.
    [task] = agent.canvas_view(_channel(agent))
    view = task["research"]
    assert view["repo"]["name"] == "streamline" and view["repo"]["branch"] == "main"
    [shown] = view["conversations"]
    assert shown["question"] == "Why sessions?" and shown["answer"] == ANSWER
    assert shown["status"] == "idle" and shown["answer_id"] == answer["id"]
    assert [m["thread_id"] for m in agent.store.roots(_channel(agent))] == [frame["id"]]


async def test_follow_ups_resume_where_the_agent_can_and_retell_where_it_cannot(
    house: tuple[AgentHost, FakeRunner, Path],
) -> None:
    agent, runner, repo = house
    channel = _channel(agent)
    frame, claude = agent.research.open(
        channel, by="you", repo=str(repo), harness="claude", question="Why sessions?"
    )
    await _settle(agent.research)
    agent.post(
        channel_id=channel,
        author_id="you",
        text="And expiry?",
        to_agent=True,
        thread_id=claude["id"],
    )
    await _settle(agent.research)
    assert runner.calls[-1]["session"] == "s-1" and runner.calls[-1]["prompt"] == "And expiry?"

    # The card's answer reads with the question it answers; a note kept from it says so too.
    [shown] = agent.research.view(frame["id"])["conversations"]  # type: ignore[index]
    assert shown["question"] == "Why sessions?" and shown["follow_up"] == "And expiry?"
    first, later = [m for m in agent.store.messages(claude["id"]) if m["kind"] == "agent"]
    for text, message in ((ANSWER, first), ("It renews.", later)):
        agent.research.keep(
            frame["id"], by="you", text=text, conversation_id=claude["id"], message_id=message["id"]
        )
    notes = agent.research.view(frame["id"])["notes"]  # type: ignore[index]
    assert [[(s["kind"], s["label"]) for s in n["lineage"]][1:] for n in notes] == [
        [("conversation", "Why sessions?")],
        [("conversation", "Why sessions?"), ("follow_up", "And expiry?")],
    ]
    written = agent.research.notes_markdown(frame["id"])
    assert "› “Why sessions?”; answered by Claude Code._" in written
    assert "_The whole answer:_" in written
    assert "_A passage of the answer to the follow-up “And expiry?”:_\nIt renews." in written

    kimi = agent.research.ask(frame["id"], by="you", question="What are the parts?", harness="kimi")
    await _settle(agent.research)
    agent.research.follow_up(kimi["id"], by="you", text="Which is newest?")
    await _settle(agent.research)
    retold = runner.calls[-1]
    assert retold["harness"] == "kimi" and retold["session"] == ""
    assert retold["prompt"].startswith("Earlier in this conversation:")
    assert "Asked: What are the parts?" in retold["prompt"] and ANSWER in retold["prompt"]
    assert retold["prompt"].endswith("Now: Which is newest?")


async def test_a_branch_starts_on_a_passage_of_its_parents_answer(
    house: tuple[AgentHost, FakeRunner, Path],
) -> None:
    agent, runner, repo = house
    frame, root = agent.research.open(
        _channel(agent), by="you", repo=str(repo), harness="claude", question="Why sessions?"
    )
    root = agent.research.ask(frame["id"], by="you", question="Why sessions?", harness="codex")
    await _settle(agent.research)
    branch = agent.research.ask(
        frame["id"],
        by="you",
        question="What decides it?",
        parent=root["id"],
        quote="A Durable Object  renews them.",
    )
    await _settle(agent.research)
    assert branch["parent_id"] == root["id"] and branch["harness"] == "codex"
    assert runner.calls[-1]["prompt"] == (
        "While researching “Why sessions?”, this came up:\n\n> A Durable Object renews them."
        "\n\nWhat decides it?"
    )
    with pytest.raises(KeyError):
        agent.research.ask("th_nope", by="you", question="?")
    note = agent.research.keep(
        frame["id"], by="you", text="It decides.", conversation_id=branch["id"]
    )
    [kept] = [n for n in agent.research.view(frame["id"])["notes"] if n["id"] == note["id"]]  # type: ignore[index]
    assert [(s["kind"], s["label"]) for s in kept["lineage"]] == [
        ("repo", "streamline"),
        ("conversation", "Why sessions?"),
        ("conversation", "What decides it?"),
    ]
    assert kept["lineage"][2]["detail"].startswith("from the passage “A Durable Object")


async def test_a_run_can_be_stopped_and_a_failure_says_why(
    house: tuple[AgentHost, FakeRunner, Path],
) -> None:
    agent, runner, repo = house
    runner.hold = asyncio.Event()
    frame, conversation = agent.research.open(
        _channel(agent), by="you", repo=str(repo), harness="claude", question="Why?"
    )
    await asyncio.sleep(0.01)
    with pytest.raises(ValueError, match="still answering"):
        agent.research.follow_up(conversation["id"], by="you", text="And?")
    view = agent.research.view(frame["id"])
    assert view is not None and view["conversations"][0]["step"] == "Searching for “expiry”"
    agent._settle_status(conversation["id"])  # the footer ticker's recount leaves it answering
    assert agent.store.thread(conversation["id"])["status"] == "working"  # type: ignore[index]
    agent.stop(conversation["id"])
    await _settle(agent.research)
    messages = agent.store.messages(conversation["id"])
    assert [m["kind"] for m in messages] == ["person", "turn"]
    assert messages[-1]["data"]["state"] == "stopped"
    assert agent.store.thread(conversation["id"])["status"] == "idle"  # type: ignore[index]

    runner.hold = None
    runner.script = [Event("step", "Reading a.go"), Event("error", "Not signed in.")]
    failed = agent.research.ask(frame["id"], by="you", question="Again?")
    await _settle(agent.research)
    assert agent.store.messages(failed["id"])[-1]["text"] == "Not signed in."
    assert agent.store.thread(failed["id"])["status"] == "failed"  # type: ignore[index]
    shown = agent.research.view(frame["id"])["conversations"][-1]  # type: ignore[index]
    assert shown["problem"] == "Not signed in." and shown["answer"] == ""


async def test_notes_kept_from_answers_become_the_frames_notes_file(
    house: tuple[AgentHost, FakeRunner, Path],
) -> None:
    agent, runner, repo = house
    frame, root = agent.research.open(
        _channel(agent), by="you", repo=str(repo), harness="claude", question="Why sessions?"
    )
    await _settle(agent.research)
    answer = agent.store.messages(root["id"])[-1]
    agent.research.keep(
        frame["id"], by="you", text=ANSWER, conversation_id=root["id"], message_id=answer["id"]
    )
    agent.research.keep(frame["id"], by="maya", text="Open on moments against hours.")
    passage = agent.research.keep(
        frame["id"], by="you", text="It renews.", conversation_id=root["id"]
    )
    agent.research.edit_note(passage["id"], text="A Durable Object renews them.")
    with pytest.raises(KeyError):
        agent.research.keep(frame["id"], by="you", text="x", conversation_id="th_other")

    view = agent.research.view(frame["id"])
    assert view is not None
    assert [n["text"] for n in view["notes"]][1:] == [
        "Open on moments against hours.",
        "A Durable Object renews them.",
    ]
    assert view["notes"][0]["message_id"] == answer["id"]
    assert view["conversations"][0]["kept"] == 2
    text = agent.research.notes_markdown(frame["id"])
    assert text.startswith("# Research notes: streamline\n")
    assert (
        "## Why sessions?\n_Lineage: `streamline` (main) › “Why sessions?”; answered by Claude Code._"
        in text
    )
    assert "_The whole answer:_\n" in text and "_A passage of the answer:_\nA Durable" in text
    assert "#### Why" in text  # the answer's own heading sits under its question's
    assert text.index("A Durable Object renews them.") < text.index("## Written by the team")
    kinds = [(n["kind"], [s["kind"] for s in n["lineage"]]) for n in view["notes"]]
    assert kinds == [
        ("answer", ["repo", "conversation"]),
        ("own", ["repo"]),
        ("passage", ["repo", "conversation"]),
    ]
    agent.research.drop_note(view["notes"][1]["id"])
    assert "Written by the team" not in agent.research.notes_markdown(frame["id"])


async def test_what_a_research_frame_makes_is_made_from_its_notes(
    house: tuple[AgentHost, FakeRunner, Path],
) -> None:
    agent, runner, repo = house
    channel = _channel(agent)
    frame, root = agent.research.open(
        channel, by="you", repo=str(repo), harness="claude", question="Why sessions?"
    )
    await _settle(agent.research)
    with pytest.raises(ValueError, match="Keep a note"):
        agent.request_asset(frame["id"], kind="board", by="you")
    agent.research.keep(frame["id"], by="you", text=ANSWER, conversation_id=root["id"])

    asset = agent.request_asset(frame["id"], kind="board", by="you")
    await asyncio.sleep(0.05)
    assert asset["thread_id"] == frame["id"] and asset["sources"] == []
    ask = next(
        m for m in agent.store.messages(frame["id"]) if m["kind"] == "person" and m["to_agent"]
    )
    assert ask["text"] == "Add “Storyboard”, made from the research notes."
    [notes] = ask["data"]["files"]
    assert notes["name"] == "research-notes.md" and notes["origin"] == "notes"
    thread_id, said = agent.runtime.asked[-1]  # type: ignore[union-attr]
    assert thread_id == frame["id"]
    assert "(attached: /workspace/attachments/research-notes.md)" in said

    message = agent.place_template(channel, "launch-kit", by="you", from_frame=frame["id"])
    assert message["thread_id"] == frame["id"]
    assert message["text"].endswith("from the research notes")
    slots = [a for a in agent.store.assets(frame["id"]) if a["template"] == "launch-kit"]
    assert slots and all(a["thread_id"] == frame["id"] for a in slots)
    [task] = agent.canvas_view(channel)
    assert task["files"] == []  # the notes file is what the frame starts from, not a delivery
    with pytest.raises(KeyError):
        agent.place_template(channel, "launch-kit", by="you", from_frame=root["id"])


async def test_a_restart_stops_a_conversation_that_was_answering(
    house: tuple[AgentHost, FakeRunner, Path],
) -> None:
    agent, _, repo = house
    _, conversation = agent.research.open(
        _channel(agent), by="you", repo=str(repo), harness="claude", question="Why?"
    )
    await _settle(agent.research)
    # As the store looked when the house went away mid-answer: still working, its card open.
    agent.store.update_thread(conversation["id"], status="working")
    turn = next(m for m in agent.store.messages(conversation["id"]) if m["kind"] == "turn")
    agent.store.update_message(turn["id"], data={**turn["data"], "state": "working"})

    agent.research.restore()
    assert agent.store.thread(conversation["id"])["status"] == "failed"  # type: ignore[index]
    messages = agent.store.messages(conversation["id"])
    assert messages[-1]["text"].startswith("Stopped when the house restarted")
    assert next(m for m in messages if m["kind"] == "turn")["data"]["state"] == "stopped"


async def test_research_needs_a_known_repository_and_an_installed_agent(
    house: tuple[AgentHost, FakeRunner, Path], tmp_path: Path
) -> None:
    agent, _, repo = house
    channel = _channel(agent)
    with pytest.raises(ValueError, match="repositories on this computer"):
        agent.research.open(channel, by="you", repo=str(tmp_path), harness="claude", question="?")
    agent.research.ready = lambda harness: harness != "kimi"
    with pytest.raises(ValueError, match="Kimi Code isn't installed"):
        agent.research.open(channel, by="you", repo=str(repo), harness="kimi", question="?")
    options = agent.research.options()
    assert [h["ready"] for h in options["harnesses"]] == [True, True, False]
    assert options["repos"] == [
        {"name": "streamline", "path": str(repo.resolve()), "branch": "main"}
    ]


async def test_a_folder_inside_a_repository_can_be_researched(
    house: tuple[AgentHost, FakeRunner, Path],
) -> None:
    agent, runner, repo = house
    (repo / "lily" / "src").mkdir(parents=True)
    (repo / "node_modules" / "pkg").mkdir(parents=True)
    frame, _ = agent.research.open(
        _channel(agent), by="you", repo=str(repo / "lily"), harness="claude", question="What is it?"
    )
    await _settle(agent.research)
    assert frame["title"] == "Research: lily"
    assert runner.calls[-1]["repo"] == (repo / "lily").resolve()
    view = agent.research.view(frame["id"])
    assert view is not None
    assert view["repo"] == {
        "name": "lily",
        "path": str((repo / "lily").resolve()),
        "branch": "main",
        "within": "streamline",
    }
    for refused in (repo / "node_modules" / "pkg", repo / ".git"):
        with pytest.raises(ValueError, match="a folder in one"):
            agent.research.open(
                _channel(agent), by="you", repo=str(refused), harness="claude", question="?"
            )
