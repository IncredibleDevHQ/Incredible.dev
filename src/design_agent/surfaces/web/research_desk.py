"""The canvas's research: a frame that starts from one of the person's repositories, the questions
asked about it of a coding agent on this computer, and the notes the team keeps from the answers.

Each question is a conversation, a thread of its own kept on the frame rather than in the channel:
the question, each run's progress as a turn card of steps, and the answer. A conversation can
branch from a passage of another's answer, so a frame grows into a tree. What each run is told:
- a new question starts afresh, with the notes the team kept on the frame as what is already
  established (never another conversation's raw chat, which would make its answer depend on
  whichever happened to run before);
- a branch starts from a copy of its parent's session where the CLI can fork one, so nothing is
  read twice and the parent's session stays as it was; otherwise it starts again, told the
  question and answer its passage came from;
- a follow-up resumes the agent's own session where its CLI allows, and otherwise starts again,
  told what was said.

Once something is made from a research frame it is a task like any other, and its notes are what
it started from: `notes_markdown` is the file the engine is handed. Runs happen here, on the host,
through `research.run`; nothing of them reaches the engine's computer but the notes people keep.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time
from collections import Counter
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from design_agent.surfaces.web.hub import Hub
from design_agent.surfaces.web.research import (
    HARNESSES,
    KIMI_PROFILE,
    SKIP_DIRS,
    Repo,
    ResearchError,
    Runner,
    branch_of,
    find_repos,
    repo_root,
    run,
)
from design_agent.surfaces.web.store import AGENT_ID, CONVERSATION, Row, Store, new_id

_LOGGER = logging.getLogger(__name__)

#: A research frame's thread kind.
RESEARCH = "research"
#: How often a running conversation's latest step reaches its card (its thread gets every step).
CARD_SECONDS = 1.0
#: What a follow-up or a branch that starts afresh is told of the conversation so far.
CONTEXT_CHARS = 6_000
#: Each kept note, as a new question is told it: one line.
NOTE_CHARS = 600
#: Steps a turn card keeps.
STEPS_KEPT = 40


def _installed(harness: str) -> bool:
    return HARNESSES[harness].binary() is not None


class ResearchDesk:
    def __init__(
        self,
        *,
        store: Store,
        hub: Hub,
        data_dir: Path,
        roots: Sequence[Path],
        runner: Runner = run,
        ready: Callable[[str], bool] = _installed,
    ) -> None:
        self.store = store
        self.hub = hub
        self.roots = [Path(r).expanduser() for r in roots]
        self.runner = runner
        self.ready = ready
        self.profile = data_dir / "research" / "kimi-researcher.md"
        self._runs: dict[str, asyncio.Task[None]] = {}
        self._card_at: dict[str, float] = {}

    # -- what can be asked, of what --------------------------------------------------------

    def options(self) -> dict[str, Any]:
        return {
            "harnesses": [
                {"id": h.id, "title": h.title, "ready": self.ready(h.id)}
                for h in HARNESSES.values()
            ],
            "repos": [r.view() for r in find_repos(self.roots)],
        }

    def _repo(self, path: str) -> Repo:
        """A repository on this computer, or a folder inside one (a package of a monorepo)."""
        wanted = Path(path).expanduser().resolve()
        for repo in find_repos(self.roots):
            if repo.path == wanted:
                return repo
            if wanted.is_dir() and wanted.is_relative_to(repo.path):
                inside = wanted.relative_to(repo.path).parts
                if not any(part.startswith(".") or part in SKIP_DIRS for part in inside):
                    return Repo(wanted.name, wanted, repo.branch, repo.touched)
        raise ValueError("Pick one of the repositories on this computer, or a folder in one.")

    def _harness(self, harness: str) -> None:
        if harness not in HARNESSES:
            raise ValueError(f"There is no agent called {harness}.")
        if not self.ready(harness):
            raise ValueError(f"{HARNESSES[harness].title} isn't installed on this computer.")

    def _frame(self, frame_id: str) -> tuple[Row, Row]:
        research = self.store.research(frame_id)
        frame = self.store.thread(frame_id)
        if research is None or frame is None:
            raise KeyError(frame_id)
        return research, frame

    # -- frames and their conversations ------------------------------------------------------

    def open(
        self, channel_id: str, *, by: str, repo: str, harness: str, question: str
    ) -> tuple[Row, Row]:
        """A research frame on the channel's canvas, reading `repo`, with its first question."""
        found = self._repo(repo)
        self._harness(harness)
        if not question.strip():
            raise ValueError("Ask the first question.")
        frame = self.store.add_thread(
            thread_id=new_id("th"),
            channel_id=channel_id,
            task=True,
            title=f"Research: {found.name}",
            kind=RESEARCH,
            by=by,
        )
        self.store.add_research(frame["id"], repo=str(found.path), harness=harness)
        self.hub.publish("thread.created", thread=frame)
        root = self.store.add_message(
            message_id=frame["id"],
            channel_id=channel_id,
            thread_id=frame["id"],
            author_id=by,
            kind="person",
            text=f"Research on {found.name}",
            data={"kind": RESEARCH, "repo": found.view()},
        )
        self.hub.publish("message.created", message=root)
        return frame, self.ask(frame["id"], by=by, question=question, harness=harness)

    def ask(
        self,
        frame_id: str,
        *,
        by: str,
        question: str,
        harness: str = "",
        parent: str = "",
        quote: str = "",
        answer: str = "",
    ) -> Row:
        """A new conversation on the frame: from the research node, or branching from another
        conversation (on a passage of its answer, when `quote` is given; `answer` is the message
        the passage was taken from, else the latest)."""
        research, frame = self._frame(frame_id)
        above = self.store.conversation(parent) if parent else None
        if parent and (above is None or above["frame_id"] != frame_id):
            raise KeyError(parent)
        # A branch stays with the agent it branched from, unless another is asked for.
        harness = harness or str((above or research)["harness"])
        self._harness(harness)
        words = question.strip()
        if not words:
            raise ValueError("Ask something.")
        thread = self.store.add_thread(
            thread_id=new_id("th"),
            channel_id=frame["channel_id"],
            task=False,
            title=_title(words),
            kind=CONVERSATION,
            by=by,
        )
        passage = " ".join(quote.split())[:2_000]
        conversation = self.store.add_conversation(
            {
                "id": thread["id"],
                "frame_id": frame_id,
                "parent_id": parent,
                "quote": passage,
                "harness": harness,
                "repo": research["repo"],
            }
        )
        self.hub.publish("thread.created", thread=thread)
        message = self.store.add_message(
            message_id=thread["id"],
            channel_id=frame["channel_id"],
            thread_id=thread["id"],
            author_id=by,
            kind="person",
            text=words,
            to_agent=True,
            data={"quote": passage} if passage else {},
        )
        self.hub.publish("message.created", message=message)
        if above is None:
            self._start(conversation, self._fresh(frame_id, words), session="")
        elif self._forks(above, harness):
            self._start(
                conversation, _forked(words, passage), session=str(above["session"]), fork=True
            )
        else:
            self._start(conversation, self._retold(above, answer, words, passage), session="")
        return conversation

    def follow_up(self, conversation_id: str, *, by: str, text: str) -> Row:
        """A person's reply in a conversation: asked of the same agent, in the same session where
        its CLI can resume one."""
        conversation = self.store.conversation(conversation_id)
        thread = self.store.thread(conversation_id)
        if conversation is None or thread is None:
            raise KeyError(conversation_id)
        if self.running(conversation_id):
            raise ValueError("It's still answering. Wait for the answer, or stop it first.")
        words = text.strip()
        message = self.store.add_message(
            channel_id=thread["channel_id"],
            thread_id=conversation_id,
            author_id=by,
            kind="person",
            text=words,
            to_agent=True,
        )
        self.hub.publish("message.created", message=message)
        if HARNESSES[conversation["harness"]].resumes and conversation["session"]:
            self._start(conversation, words, session=str(conversation["session"]))
        else:
            self._start(conversation, self._so_far(conversation, words), session="")
        return message

    def _fresh(self, frame_id: str, question: str) -> str:
        """A new question, told what the team kept on the frame: the newest notes that fit, each
        on one line."""
        kept: list[str] = []
        for note in reversed(self.store.notes(frame_id)):
            line = f"- {_clip(str(note['text']), NOTE_CHARS)}"
            if sum(len(k) + 1 for k in kept) + len(line) > CONTEXT_CHARS:
                break
            kept.insert(0, line)
        if not kept:
            return question
        notes = "\n".join(kept)
        return (
            "What the team has kept from earlier answers about this repository, to build on "
            f"(check anything you rely on against the code):\n\n{notes}\n\nThe question: {question}"
        )

    def _forks(self, above: Row, harness: str) -> bool:
        """Whether a branch can start from a copy of its parent's session: the same agent, one
        whose CLI forks, a session to fork, and a parent not mid-answer."""
        return (
            HARNESSES[harness].forks
            and harness == above["harness"]
            and bool(above["session"])
            and not self.running(str(above["id"]))
        )

    def _retold(self, above: Row, answer_id: str, question: str, quote: str) -> str:
        """A branch that starts afresh, told what it branched from: the question and the answer
        its passage came from (the parent's latest unless `answer_id` names another), cut to
        CONTEXT_CHARS."""
        said = self.store.messages(str(above["id"]))
        answers = [i for i, m in enumerate(said) if m["kind"] == "agent"]
        at = next(
            (i for i in answers if said[i]["id"] == answer_id), answers[-1] if answers else -1
        )
        asked = next(
            (str(m["text"]) for m in reversed(said[: max(at, 0)]) if m["kind"] == "person"),
            self._question(str(above["id"])),
        )
        lines = [
            "This branches from an earlier conversation about this repository.",
            f"Asked: {asked}",
        ]
        if at >= 0:
            lines.append(f"Answered:\n\n{_cut(str(said[at]['text']), CONTEXT_CHARS)}")
        if quote:
            lines.append(f"From that answer, this passage:\n\n> {quote}")
        lines.append(f"Now: {question}")
        return "\n\n".join(lines)

    def _so_far(self, conversation: Row, question: str) -> str:
        lines = [f"From the passage: “{conversation['quote']}”"] if conversation["quote"] else []
        for message in self.store.messages(str(conversation["id"]))[:-1]:
            if message["kind"] == "person":
                lines.append(f"Asked: {message['text']}")
            elif message["kind"] == "agent":
                lines.append(f"Answered: {message['text']}")
        history = "\n\n".join(lines)[-CONTEXT_CHARS:]
        return f"Earlier in this conversation:\n\n{history}\n\nNow: {question}"

    def _question(self, conversation_id: str) -> str:
        root = self.store.message(conversation_id)
        return str(root["text"]) if root is not None else ""

    # -- runs ----------------------------------------------------------------------------------

    def running(self, conversation_id: str) -> bool:
        task = self._runs.get(conversation_id)
        return task is not None and not task.done()

    def stop(self, conversation_id: str) -> bool:
        """End a conversation's run now; its CLI and anything it started go with it."""
        task = self._runs.get(conversation_id)
        if task is None or task.done():
            return False
        task.cancel()
        return True

    async def close(self) -> None:
        runs = list(self._runs.values())
        for task in runs:
            task.cancel()
        await asyncio.gather(*runs, return_exceptions=True)

    def restore(self) -> None:
        """A conversation that was answering when the house stopped is stopped, and says so."""
        for channel in self.store.channels():
            for thread in self.store.threads(channel["id"]):
                if thread["kind"] != CONVERSATION or thread["status"] != "working":
                    continue
                for message in self.store.messages(thread["id"]):
                    if message["kind"] == "turn" and message["data"].get("state") == "working":
                        data = {**message["data"], "state": "stopped", "ended_at": time.time()}
                        self.store.update_message(message["id"], data=data)
                self.store.add_message(
                    channel_id=thread["channel_id"],
                    thread_id=thread["id"],
                    author_id=AGENT_ID,
                    kind="notice",
                    text="Stopped when the house restarted. Ask again to pick it up.",
                )
                self.store.update_thread(thread["id"], status="failed")

    def _start(self, conversation: Row, prompt: str, *, session: str, fork: bool = False) -> None:
        conversation_id = str(conversation["id"])
        self._set_status(conversation_id, "working")
        self._runs[conversation_id] = asyncio.get_running_loop().create_task(
            self._run(conversation, prompt, session, fork), name=f"research {conversation_id}"
        )
        self._changed(str(conversation["frame_id"]))

    async def _run(self, conversation: Row, prompt: str, session: str, fork: bool) -> None:
        conversation_id = str(conversation["id"])
        frame_id = str(conversation["frame_id"])
        harness = HARNESSES[conversation["harness"]]
        repo = Path(conversation["repo"])
        turn = self._say(
            conversation_id,
            "",
            kind="turn",
            data={
                "state": "working",
                "header": f"{harness.title} is reading {repo.name}",
                "steps": [],
                "notes": [],
                "mark": harness.id,
                "started_at": time.time(),
            },
        )
        steps: list[dict[str, Any]] = []
        notes: list[str] = []
        answer = failure = ""
        stopped = False

        def show(**change: Any) -> None:
            turn["data"] = {**turn["data"], "steps": steps[-STEPS_KEPT:], "notes": notes[-3:]}
            turn["data"].update(change)
            self._update(str(turn["id"]), data=turn["data"])

        try:
            self._write_profile()
            events = self.runner(
                harness.id,
                repo=repo,
                prompt=prompt,
                session=session,
                fork=fork,
                profile=self.profile,
            )
            async with contextlib.aclosing(events):
                async for event in events:
                    if event.kind == "session":
                        self.store.update_conversation(conversation_id, session=event.text)
                    elif event.kind == "step":
                        for step in steps:
                            step["status"] = "done"
                        steps.append(
                            {"id": f"s{len(steps)}", "title": event.text, "status": "running"}
                        )
                        show(header=event.text)
                        self._card(frame_id)
                    elif event.kind == "note":
                        notes.append(event.text)
                        show()
                    elif event.kind == "answer":
                        answer = event.text
                    else:
                        failure = event.text
        except asyncio.CancelledError:
            stopped = True
        except ResearchError as error:
            failure = str(error)
        except Exception as error:  # a CLI that misbehaves must not take the house down
            _LOGGER.exception("research run failed on %s", conversation_id)
            failure = f"It stopped: {type(error).__name__}."
        if not answer and notes and not (failure or stopped):
            answer = notes[-1]
        for step in steps:
            step["status"] = "done"
        show(state="stopped" if stopped else "done", ended_at=time.time())
        if answer:
            self._say(conversation_id, answer, kind="agent", data={"mark": harness.id})
        if failure:
            self._say(conversation_id, failure, kind="notice")
        self._runs.pop(conversation_id, None)
        self._set_status(conversation_id, "failed" if failure and not answer else "idle")
        self._changed(frame_id)

    def _write_profile(self) -> None:
        if not self.profile.exists() or self.profile.read_text() != KIMI_PROFILE:
            self.profile.parent.mkdir(parents=True, exist_ok=True)
            self.profile.write_text(KIMI_PROFILE)

    def _say(
        self, conversation_id: str, text: str, *, kind: str, data: dict[str, Any] | None = None
    ) -> Row:
        thread = self.store.thread(conversation_id)
        assert thread is not None  # noqa: S101 - a conversation's thread is never removed
        message = self.store.add_message(
            channel_id=thread["channel_id"],
            thread_id=conversation_id,
            author_id=AGENT_ID,
            kind=kind,
            text=text,
            data=data,
        )
        self.hub.publish("message.created", message=message)
        return message

    def _update(self, message_id: str, **values: Any) -> None:
        updated = self.store.update_message(message_id, **values)
        if updated is not None:
            self.hub.publish("message.updated", message=updated)

    def _set_status(self, conversation_id: str, status: str) -> None:
        thread = self.store.update_thread(conversation_id, status=status)
        if thread is not None:
            self.hub.publish("thread.updated", thread=thread)

    def _changed(self, frame_id: str) -> None:
        frame = self.store.thread(frame_id)
        view = self.view(frame_id)
        if frame is None or view is None:
            return
        self._card_at[frame_id] = time.time()
        self.hub.publish(
            "research.updated", thread_id=frame_id, channel_id=frame["channel_id"], research=view
        )

    def _card(self, frame_id: str) -> None:
        if time.time() - self._card_at.get(frame_id, 0.0) >= CARD_SECONDS:
            self._changed(frame_id)

    # -- notes ---------------------------------------------------------------------------------

    def keep(
        self, frame_id: str, *, by: str, text: str, conversation_id: str = "", message_id: str = ""
    ) -> Row:
        """A note in the frame's notebook: a passage or a whole answer from a conversation, or the
        team's own words."""
        self._frame(frame_id)
        words = text.strip()
        if not words:
            raise ValueError("A note needs words.")
        if conversation_id:
            conversation = self.store.conversation(conversation_id)
            if conversation is None or conversation["frame_id"] != frame_id:
                raise KeyError(conversation_id)
        note = self.store.add_note(
            {
                "frame_id": frame_id,
                "text": words[:8_000],
                "conversation_id": conversation_id,
                "message_id": message_id,
                "author_id": by,
            }
        )
        self._changed(frame_id)
        return note

    def edit_note(self, note_id: str, *, text: str) -> Row:
        note = self.store.note(note_id)
        if note is None:
            raise KeyError(note_id)
        if not text.strip():
            raise ValueError("A note needs words.")
        updated = self.store.update_note(note_id, text=text.strip()[:8_000])
        self._changed(str(note["frame_id"]))
        assert updated is not None  # noqa: S101 - found just above
        return updated

    def drop_note(self, note_id: str) -> None:
        note = self.store.note(note_id)
        if note is None:
            raise KeyError(note_id)
        self.store.delete_note(note_id)
        self._changed(str(note["frame_id"]))

    def notes_markdown(self, frame_id: str) -> str:
        """The frame's notes as one document, grouped by the question each came from: what the
        engine is handed to make the frame's assets from."""
        research, _ = self._frame(frame_id)
        notes = self.store.notes(frame_id)
        if not notes:
            return ""
        repo = Path(research["repo"])
        branch = branch_of(repo)
        conversations = {c["id"]: c for c in self.store.conversations(frame_id)}
        lines = [
            f"# Research notes: {repo.name}",
            "",
            f"What the team kept from research on the `{repo.name}` repository"
            + (f" (`{branch}`)" if branch else "")
            + ", answered by coding agents that read its code. Each note sits under the question "
            "it came from. Build on these; anything else needs checking first.",
        ]
        groups: dict[str, list[Row]] = {}
        for note in notes:
            groups.setdefault(str(note["conversation_id"]), []).append(note)
        repo_view = self._repo_view(research)
        listing = list(conversations.values())
        for conversation_id, kept in groups.items():
            conversation = conversations.get(conversation_id)
            lines.append("")
            if conversation is None:
                lines.append("## Written by the team")
            else:
                lines.append(f"## {self._question(conversation_id)}")
                trail = [
                    s for s in self.lineage(kept[0], repo_view, listing) if s["kind"] != "follow_up"
                ]
                path = " › ".join(
                    f"`{step['label']}`" + (f" ({step['detail']})" if step["detail"] else "")
                    if step["kind"] == "repo"
                    else f"“{_clip(step['label'], 90)}”"
                    for step in trail
                )
                lines.append(
                    f"_Lineage: {path}; answered by {HARNESSES[conversation['harness']].title}._"
                )
            said = self.store.messages(conversation_id) if conversation is not None else []
            for note in kept:
                kind = self._note_kind(note)
                label = {
                    "answer": "The whole answer",
                    "passage": "A passage of the answer",
                    "own": "",
                }[kind]
                asked = _follow_up(said, str(note["message_id"]), conversation_id)
                if label and asked:
                    label += f" to the follow-up “{_clip(asked, 90)}”"
                lines += ["", f"_{label}:_" if label else "", _demote(str(note["text"]))]
        return (
            "\n".join(line for i, line in enumerate(lines) if line or i == 0 or lines[i - 1]) + "\n"
        )

    # -- what the canvas shows -----------------------------------------------------------------

    def view(self, frame_id: str) -> dict[str, Any] | None:
        research = self.store.research(frame_id)
        if research is None:
            return None
        notes = self.store.notes(frame_id)
        kept = Counter(str(n["conversation_id"]) for n in notes)
        conversations = self.store.conversations(frame_id)
        repo = self._repo_view(research)
        return {
            "repo": repo,
            "harness": research["harness"],
            "conversations": [
                self._conversation_view(c, kept[str(c["id"])]) for c in conversations
            ],
            "notes": [
                {
                    "id": n["id"],
                    "text": n["text"],
                    "conversation_id": n["conversation_id"],
                    "message_id": n["message_id"],
                    "author_id": n["author_id"],
                    "created_at": n["created_at"],
                    "kind": self._note_kind(n),
                    "lineage": self.lineage(n, repo, conversations),
                }
                for n in notes
            ],
        }

    def _repo_view(self, research: Row) -> dict[str, str]:
        path = Path(research["repo"])
        root = repo_root(path)
        return {
            "name": path.name,
            "path": str(path),
            "branch": branch_of(path),
            "within": root.name if root is not None and root != path else "",
        }

    def _note_kind(self, note: Row) -> str:
        """A whole answer kept, a passage of one, or the team's own words."""
        if not note["conversation_id"]:
            return "own"
        message = self.store.message(str(note["message_id"])) if note["message_id"] else None
        return (
            "answer"
            if message is not None and message["text"].strip() == note["text"].strip()
            else "passage"
        )

    def lineage(
        self, note: Row, repo: dict[str, str], conversations: list[Row]
    ) -> list[dict[str, str]]:
        """Where a note came from, from the repository down: the repository (and the one it sits
        in), then every conversation from the first question to the one it was kept from, and
        the follow-up it answers when it was kept from a later answer in that conversation."""
        steps = [
            {
                "kind": "repo",
                "label": repo["name"],
                "detail": " · ".join(
                    p
                    for p in (f"in {repo['within']}" if repo["within"] else "", repo["branch"])
                    if p
                ),
            }
        ]
        by_id = {str(c["id"]): c for c in conversations}
        chain: list[Row] = []
        at = by_id.get(str(note["conversation_id"]))
        while at is not None and at not in chain:
            chain.insert(0, at)
            at = by_id.get(str(at["parent_id"])) if at["parent_id"] else None
        for conversation in chain:
            steps.append(
                {
                    "kind": "conversation",
                    "id": str(conversation["id"]),
                    "label": self._question(str(conversation["id"])),
                    "harness": str(conversation["harness"]),
                    "detail": f"from the passage “{_clip(conversation['quote'], 80)}”"
                    if conversation["quote"]
                    else "",
                }
            )
        if chain and note["message_id"]:
            kept_from = str(chain[-1]["id"])
            asked = _follow_up(self.store.messages(kept_from), str(note["message_id"]), kept_from)
            if asked:
                steps.append({"kind": "follow_up", "label": asked, "detail": ""})
        return steps

    def _conversation_view(self, conversation: Row, kept: int) -> dict[str, Any]:
        thread = self.store.thread(str(conversation["id"])) or {}
        messages = self.store.messages(str(conversation["id"]))
        answers = [m for m in messages if m["kind"] == "agent"]
        turns = [m for m in messages if m["kind"] == "turn"]
        said = [m for m in messages if m["kind"] in ("agent", "notice")]
        working = thread.get("status") == "working"
        return {
            "id": conversation["id"],
            "parent_id": conversation["parent_id"],
            "quote": conversation["quote"],
            "harness": conversation["harness"],
            "question": next((m["text"] for m in messages if m["kind"] == "person"), ""),
            "status": thread.get("status", "idle"),
            "answer": answers[-1]["text"] if answers else "",
            "answer_id": answers[-1]["id"] if answers else "",
            # The follow-up that answer answers, when it is not the first question's.
            "follow_up": _follow_up(messages, answers[-1]["id"], str(conversation["id"]))
            if answers
            else "",
            "step": str(turns[-1]["data"].get("header") or "") if working and turns else "",
            "problem": said[-1]["text"] if said and said[-1]["kind"] == "notice" else "",
            "asked": sum(1 for m in messages if m["kind"] == "person"),
            "kept": kept,
            "created_at": conversation["created_at"],
        }


def _follow_up(messages: Sequence[Row], answer_id: str, conversation_id: str) -> str:
    """The follow-up an answer in a conversation answers: empty for an answer to its first
    question (the message that opened it, under the conversation's own id)."""
    asked = ""
    for message in messages:
        if message["id"] == answer_id:
            return asked
        if message["kind"] == "person" and message["id"] != conversation_id:
            asked = str(message["text"])
    return ""


def _title(text: str) -> str:
    line = next((x.strip() for x in text.splitlines() if x.strip()), "A question")
    return line if len(line) <= 80 else line[:79].rstrip() + "…"


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _cut(text: str, limit: int) -> str:
    """`text` up to `limit`, its lines kept."""
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _forked(question: str, quote: str) -> str:
    """A branch in a copy of its parent's session, which holds everything the parent read and
    said: the passage and the question are all it needs."""
    return (
        f"From your answer above, this passage:\n\n> {quote}\n\n{question}" if quote else question
    )


def _demote(text: str) -> str:
    """A kept answer's own headings, two levels down, under its question's."""
    return re.sub(
        r"(?m)^(#{1,4})(\s)", lambda m: "#" * min(6, len(m.group(1)) + 2) + m.group(2), text
    )
