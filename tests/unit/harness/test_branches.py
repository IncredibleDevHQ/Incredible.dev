"""Looks: copies of a project made in parallel, read back, and one merged after a backup."""

import asyncio
import json
import os
import shutil
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from design_agent.harness import events as ev
from design_agent.harness.branches import (
    DEFAULT_CONTEXT,
    Looks,
    LooksError,
    LookSpec,
    LookWatch,
    SnapshotBranches,
    next_ids,
)
from design_agent.harness.policy import Delivery, decide
from design_agent.harness.protocols import ExecResult

PROJECT = "/workspace/projects/film"


class RecordingExec:
    """Records each command and answers with the next scripted output."""

    def __init__(self, *outputs: ExecResult | str) -> None:
        self.commands: list[str] = []
        self._outputs = list(outputs)

    async def execute(self, command: str, *, timeout: int | None = None) -> ExecResult:
        self.commands.append(command)
        answer = self._outputs.pop(0) if self._outputs else ExecResult("")
        return answer if isinstance(answer, ExecResult) else ExecResult(answer)


class LocalExec:
    """Runs each command in a real local shell, so the scripts themselves are what is tested."""

    async def execute(self, command: str, *, timeout: int | None = None) -> ExecResult:
        process = await asyncio.create_subprocess_exec(
            "/bin/sh",
            "-c",
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        output, _ = await asyncio.wait_for(process.communicate(), timeout or 60)
        return ExecResult(output.decode(), process.returncode)


class FakeRunner:
    def __init__(self, fail_on: int | None = None) -> None:
        self.started: list[dict] = []
        self._fail_on = fail_on

    async def start(self, brief, *, effort, label="", wave=None) -> str:
        if self._fail_on is not None and len(self.started) + 1 == self._fail_on:
            raise RuntimeError("Delegation is unavailable in this run")
        self.started.append({"brief": brief, "effort": effort, "label": label, "wave": wave})
        return f"t-{len(self.started)}"

    async def run(self, brief, *, effort, label="", wave=None):  # pragma: no cover - unused
        raise NotImplementedError


# -- commands and briefs ------------------------------------------------------------------------


async def test_prepare_copies_each_look_without_other_looks_renders_or_dependencies():
    sandbox = RecordingExec()
    folders = await Looks(sandbox).prepare(PROJECT, ["a", "b"])

    assert folders == [f"{PROJECT}/looks/a", f"{PROJECT}/looks/b"]
    (script,) = sandbox.commands  # one sandbox call for every look
    assert "command -v rsync" in script
    assert (
        "rsync -a --delete --delete-excluded --exclude=/looks --exclude=/out "
        "--exclude=/node_modules" in script
    )
    # Without rsync: `cp -a` of every other top-level entry, into a folder emptied first.
    assert 'rm -rf "$2"' in script and 'cp -a "$entry" "$2"/' in script
    assert "looks|out|node_modules) continue" in script
    assert 'copy_tree "$project" "$project/looks/a"' in script
    assert 'copy_tree "$project" "$project/looks/b"' in script
    # Dependencies are linked, not copied, so the renderer runs from the look's folder.
    assert 'ln -sfn ../../node_modules "$project/looks/a"/node_modules' in script


async def test_the_copy_method_can_be_forced():
    for use_rsync, expected in ((True, "HAVE_RSYNC=1"), (False, "HAVE_RSYNC=0")):
        sandbox = RecordingExec()
        await Looks(sandbox, use_rsync=use_rsync).prepare(PROJECT, ["a"])
        assert expected in sandbox.commands[0]
        assert "command -v rsync" not in sandbox.commands[0]


@pytest.mark.parametrize("look_id", ["../x", "_backup-1", ".meta", "a b", "", "a/b"])
async def test_a_look_id_is_one_safe_folder_name(look_id):
    sandbox = RecordingExec()
    with pytest.raises(LooksError):
        await Looks(sandbox).prepare(PROJECT, [look_id])
    assert sandbox.commands == []


@pytest.mark.parametrize("project", ["/", "/workspace", "workspace/projects/x", "/a/../b", "/a/b/"])
async def test_a_project_is_an_absolute_folder_two_levels_deep(project):
    sandbox = RecordingExec()
    with pytest.raises(LooksError):
        await Looks(sandbox).prepare(project, ["a"])
    assert sandbox.commands == []


async def test_each_look_needs_its_own_id():
    sandbox = RecordingExec()
    for ids in (["a", "a"], []):
        with pytest.raises(LooksError):
            await Looks(sandbox).prepare(PROJECT, ids)
    assert sandbox.commands == []


async def test_a_failed_command_raises_with_the_tail_of_its_output():
    sandbox = RecordingExec(ExecResult("rsync: write failed: No space left on device", 23))
    with pytest.raises(LooksError, match="No space left") as raised:
        await Looks(sandbox).prepare(PROJECT, ["a"])
    assert "exit 23" in str(raised.value)


async def test_an_unknown_exit_code_counts_only_with_the_scripts_last_marker():
    missing = RecordingExec(ExecResult("partial", None))
    with pytest.raises(LooksError):
        await Looks(missing).prepare(PROJECT, ["a", "b"])
    finished = RecordingExec(ExecResult("@@prepared@@ a\n@@prepared@@ b\n", None))
    assert len(await Looks(finished).prepare(PROJECT, ["a", "b"])) == 2


def test_the_brief_names_the_folder_the_direction_and_what_to_leave_there():
    looks = Looks(RecordingExec())
    brief = looks.brief_for(LookSpec("b", "Kinetic type on black, one accent"), PROJECT)

    assert "Kinetic type on black, one accent" in brief
    assert f"{PROJECT}/looks/b/ is a full copy of the project" in brief
    assert f"{PROJECT}/looks/b/out/" in brief
    assert f"{PROJECT}/looks/b/look.json" in brief
    assert '{"id": "b", "direction":' in brief
    assert "everything you" in brief and "change goes in" in brief
    assert DEFAULT_CONTEXT in brief
    shared = looks.brief_for(LookSpec("b", "x"), PROJECT, context="A 20 s teaser for devs.")
    assert "A 20 s teaser for devs." in shared and DEFAULT_CONTEXT not in shared


def test_a_custom_template_keeps_placeholders_it_does_not_know():
    looks = Looks(RecordingExec())
    brief = looks.brief_for(LookSpec("c", "glass UI"), PROJECT, "{id}: {direction} {unknown}")
    assert brief == "c: glass UI {unknown}"


async def test_start_prepares_once_then_starts_one_helper_per_look_in_one_wave():
    sandbox, runner = RecordingExec(), FakeRunner()
    specs = [LookSpec("a", "kinetic type"), LookSpec("b", "glass UI")]

    started = await Looks(sandbox).start(PROJECT, specs, runner, "max")

    assert started == {"a": "t-1", "b": "t-2"}
    (script,) = sandbox.commands
    assert '.meta/a.json"' in script and '"direction": "kinetic type"' in script
    assert [s["effort"] for s in runner.started] == ["max", "max"]
    assert {s["wave"] for s in runner.started} == {"looks film"}
    assert [s["label"] for s in runner.started] == ["look a: kinetic type", "look b: glass UI"]
    assert "kinetic type" in runner.started[0]["brief"]
    assert f"{PROJECT}/looks/b/" in runner.started[1]["brief"]


async def test_a_helper_that_cannot_start_names_the_ones_already_running():
    runner = FakeRunner(fail_on=2)
    with pytest.raises(LooksError) as raised:
        await Looks(RecordingExec()).start(
            PROJECT, [LookSpec("a", "x"), LookSpec("b", "y")], runner
        )
    assert raised.value.started == {"a": "t-1"}
    assert "look b did not start" in str(raised.value)


def test_next_ids_continue_after_the_looks_on_disk():
    assert next_ids(["a", "b"], 2) == ["c", "d"]
    assert next_ids([], 27)[-2:] == ["z", "a2"]
    assert next_ids("abcdefghijklmnopqrstuvwxyz", 2) == ["a2", "b2"]
    assert next_ids(["a"], 0) == []


# -- reading and merging --------------------------------------------------------------------------


async def test_collect_reads_each_looks_json_and_falls_back_to_its_direction():
    written = {
        "id": "a",
        "direction": "Kinetic type",
        "summary": "Bold type cut to the beat.",
        "stills": ["out/still-1.png", "/abs/still-2.png", 3],
    }
    output = (
        "\n@@look@@ a\n@@meta@@\n"
        + json.dumps({"id": "a", "direction": "kinetic"})
        + "\n@@json@@\n"
        + json.dumps(written, indent=2)
        + "\n\n@@look@@ b\n@@meta@@\n"
        + json.dumps({"id": "b", "direction": "glass UI"})
        + "\n\n@@look@@ c\n@@json@@\nnot json\n"
        + "\n@@look@@ a2\n"
    )
    sandbox = RecordingExec(output)

    results = await Looks(sandbox).collect(PROJECT)

    assert [r.id for r in results] == ["a", "b", "c", "a2"]
    a, b, c, a2 = results
    assert a.ready and a.direction == "Kinetic type" and a.summary == "Bold type cut to the beat."
    assert a.stills == [f"{PROJECT}/looks/a/out/still-1.png", "/abs/still-2.png"]
    assert a.dir == f"{PROJECT}/looks/a"
    assert not b.ready and b.direction == "glass UI" and b.stills == []
    assert not c.ready and not a2.ready
    assert "_backup-*) continue" in sandbox.commands[0]


async def test_pick_backs_up_then_merges_and_returns_the_changed_files():
    output = (
        "@@changed@@ ./\n@@changed@@ src/\n@@changed@@ src/Root.tsx\n@@changed@@ src/theme.ts\n"
        f"@@backup@@ {PROJECT}/looks/_backup-20260927-120000\n"
    )
    sandbox = RecordingExec(output)
    at = 1_790_510_400.0  # 2026-09-27 12:00:00 UTC

    picked = await Looks(sandbox, clock=lambda: at).pick(PROJECT, "b")

    assert picked.changed == ["src/Root.tsx", "src/theme.ts"]
    assert picked.backup == f"{PROJECT}/looks/_backup-20260927-120000"
    (script,) = sandbox.commands
    assert script.index('copy_tree "$project" "$backup"') < script.index("rsync -a -u")
    assert "--exclude=/look.json --exclude=/looks --exclude=/out --exclude=/node_modules" in script
    assert "cmp -s" in script  # the fallback when the sandbox has no rsync


async def test_pick_of_a_missing_look_raises():
    sandbox = RecordingExec(ExecResult(f"no look folder at {PROJECT}/looks/z", 3))
    with pytest.raises(LooksError, match="no look folder"):
        await Looks(sandbox).pick(PROJECT, "z")


# -- the scripts in a real shell ------------------------------------------------------------------


def _write(path: Path, text: str, mtime: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    os.utime(path, (mtime, mtime))


COPY_METHODS = [
    pytest.param(
        True,
        id="rsync",
        marks=pytest.mark.skipif(shutil.which("rsync") is None, reason="no rsync here"),
    ),
    pytest.param(False, id="cp"),
]


@pytest.mark.parametrize("use_rsync", COPY_METHODS)
async def test_prepare_collect_and_pick_in_a_real_shell(tmp_path, use_rsync):
    project = tmp_path / "projects" / "film"
    then = time.time() - 10_000
    _write(project / "src" / "Root.tsx", "root v1", then)
    _write(project / "src" / "looks" / "keep.ts", "a folder named looks, deeper down", then)
    _write(project / "package.json", "{}", then)
    _write(project / ".env.local", "hidden", then)
    _write(project / "out" / "final.mp4", "render", then)
    _write(project / "node_modules" / "renderer" / "index.js", "dependency", then)
    looks = Looks(LocalExec(), use_rsync=use_rsync, clock=lambda: then)

    await looks.start(
        str(project), [LookSpec("a", "kinetic"), LookSpec("b", "glass")], FakeRunner()
    )

    a = project / "looks" / "a"
    assert (a / "src" / "Root.tsx").read_text() == "root v1"
    assert (a / "src" / "looks" / "keep.ts").exists() and (a / ".env.local").exists()
    assert (a / "out").is_dir() and not any((a / "out").iterdir())
    assert not (a / "looks").exists()
    assert (a / "node_modules").is_symlink()
    assert (a / "node_modules" / "renderer" / "index.js").read_text() == "dependency"

    # The helper makes look a; meanwhile the lead edits the project's package.json.
    _write(a / "src" / "Root.tsx", "root, kinetic", then + 100)
    _write(a / "src" / "Intro.tsx", "intro", then + 100)
    _write(a / "package.json", "{}", then)
    _write(a / "out" / "still-1.png", "still", then + 100)
    look_json = {
        "id": "a",
        "direction": "kinetic",
        "summary": "Type.",
        "stills": ["out/still-1.png"],
    }
    _write(a / "look.json", json.dumps(look_json), then + 100)
    _write(project / "package.json", '{"lead": "edit"}', then + 200)

    results = await looks.collect(str(project))
    assert [(r.id, r.ready, r.direction) for r in results] == [
        ("a", True, "kinetic"),
        ("b", False, "glass"),
    ]
    assert results[0].stills == [str(a / "out" / "still-1.png")]

    picked = await looks.pick(str(project), "a")

    assert sorted(picked.changed) == ["src/Intro.tsx", "src/Root.tsx"]
    assert (project / "src" / "Root.tsx").read_text() == "root, kinetic"
    assert (project / "src" / "Intro.tsx").read_text() == "intro"
    assert (project / "package.json").read_text() == '{"lead": "edit"}'  # newer in the project
    assert not (project / "look.json").exists()
    assert sorted(p.name for p in (project / "out").iterdir()) == ["final.mp4"]
    assert (project / "node_modules").is_dir() and not (project / "node_modules").is_symlink()
    backup = Path(picked.backup)
    assert backup.parent == project / "looks" and backup.name.startswith("_backup-")
    assert (backup / "src" / "Root.tsx").read_text() == "root v1"
    assert not (backup / "out").exists() and not (backup / "node_modules").exists()
    assert [r.id for r in await looks.collect(str(project))] == ["a", "b"]

    # Preparing a look again starts it over from the project as it now is.
    _write(project / "looks" / "b" / "stray.txt", "left over", then)
    await looks.prepare(str(project), ["b"])
    assert not (project / "looks" / "b" / "stray.txt").exists()
    assert (project / "looks" / "b" / "src" / "Intro.tsx").read_text() == "intro"


# -- hearing the looks end ----------------------------------------------------------------------


def _ended(kind: str, task_id: str, thread: str = "th-1") -> ev.Event:
    return ev.Event(kind, thread, task_id, label="look", text="report")


def _attention(seen: list[ev.Event]) -> list[ev.Event]:
    return [e for e in seen if e.kind == ev.JOB_ATTENTION]


def _watch(bus: ev.EventBus) -> tuple[LookWatch, list[ev.Event]]:
    seen: list[ev.Event] = []
    bus.subscribe(seen.append)
    return LookWatch("th-1", "film", bus=bus), seen


def test_the_person_is_pinged_once_after_the_last_look_ends():
    bus = ev.EventBus()
    watch, seen = _watch(bus)
    specs = [LookSpec("a", "kinetic type"), LookSpec("b", "glass UI")]
    watch.expect({"a": "t-1", "b": "t-2"}, specs)

    bus.publish(_ended(ev.TASK_DONE, "t-1"))
    bus.publish(ev.Event(ev.TASK_PROGRESS, "th-1", "t-2", text="halfway"))
    bus.publish(_ended(ev.TASK_DONE, "t-2", thread="th-other"))
    bus.publish(_ended(ev.TASK_DONE, "t-9"))
    assert _attention(seen) == [] and watch.pending() == {"b": "t-2"}

    bus.publish(_ended(ev.TASK_FAILED, "t-2"))
    bus.publish(_ended(ev.TASK_DONE, "t-2"))

    (attention,) = _attention(seen)
    assert attention.thread_id == "th-1" and attention.source == watch.id
    assert attention.label == "looks for film"
    assert attention.text == (
        "The looks for film are ready to compare: a (kinetic type). Not finished: b (failed). "
        "Pick the one to build on."
    )
    assert attention.data["ping"] is True
    assert [row["status"] for row in attention.data["looks"]] == ["done", "failed"]
    decision = decide(attention)
    assert decision.delivery is Delivery.NOW and decision.ping
    assert watch.fired and not bus.is_subscribed(watch._on_event)


def test_a_look_that_ends_before_its_id_is_known_is_not_missed():
    bus = ev.EventBus()
    watch, seen = _watch(bus)
    bus.publish(_ended(ev.TASK_DONE, "t-1"))  # a quick helper, before start() returned

    watch.expect({"a": "t-1"}, [LookSpec("a", "kinetic type")])

    assert len(_attention(seen)) == 1


def test_nothing_to_pick_means_no_ping():
    bus = ev.EventBus()
    watch, seen = _watch(bus)
    watch.expect({"a": "t-1", "b": "t-2"}, [LookSpec("a", "x"), LookSpec("b", "y")])
    bus.publish(_ended(ev.TASK_FAILED, "t-1"))
    bus.publish(_ended(ev.TASK_INTERRUPTED, "t-2"))

    assert _attention(seen) == [] and watch.fired
    assert not bus.is_subscribed(watch._on_event)


def test_a_silenced_round_is_tracked_but_pings_nobody():
    bus = ev.EventBus()
    watch, seen = _watch(bus)
    watch.expect({"a": "t-1", "b": "t-2"}, [LookSpec("a", "x"), LookSpec("b", "y")])
    bus.publish(_ended(ev.TASK_DONE, "t-1"))

    watch.silence()  # the person picked a already

    assert watch.look_ids == ["a", "b"] and watch.pending() == {"b": "t-2"}
    bus.publish(_ended(ev.TASK_DONE, "t-2"))
    assert _attention(seen) == [] and watch.fired
    assert not bus.is_subscribed(watch._on_event)


def test_a_watch_with_nothing_started_stops_listening():
    bus = ev.EventBus()
    watch, _ = _watch(bus)
    watch.expect({}, [])
    assert not bus.is_subscribed(watch._on_event)


# -- snapshot branches --------------------------------------------------------------------------


class FakeSnapshotClient:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def capture_snapshot(self, sandbox_name, name, *, tag=None):
        self.calls.append(("capture", sandbox_name, name, tag))
        return SimpleNamespace(id="snap-1", name=name, tags=[tag] if tag else [])

    async def create_sandbox(self, snapshot_id=None, *, snapshot=None, name=None, **resources):
        self.calls.append(("create", snapshot, name, resources))
        return SimpleNamespace(id="box-1", name=name, status="ready")

    async def delete_sandbox(self, name):
        self.calls.append(("delete", name))


async def test_snapshot_branches_capture_spawn_and_discard():
    client = FakeSnapshotClient()
    branches = SnapshotBranches(client)

    snapshot = await branches.capture("thread-box", "film-looks", tag="round-1")
    branch = await branches.spawn(
        "film-looks:round-1", "film-look-a", vcpus=4, mem_bytes=8 << 30, idle_ttl_seconds=600
    )
    await branches.discard("film-look-a")

    assert (snapshot.id, snapshot.name, snapshot.tags) == ("snap-1", "film-looks", ["round-1"])
    assert (branch.name, branch.snapshot, branch.status) == (
        "film-look-a",
        "film-looks:round-1",
        "ready",
    )
    assert client.calls == [
        ("capture", "thread-box", "film-looks", "round-1"),
        (
            "create",
            "film-looks:round-1",
            "film-look-a",
            {"vcpus": 4, "mem_bytes": 8 << 30, "idle_ttl_seconds": 600},
        ),
        ("delete", "film-look-a"),
    ]


async def test_spawn_refuses_resources_the_client_does_not_take():
    client = FakeSnapshotClient()
    with pytest.raises(TypeError, match="gpus"):
        await SnapshotBranches(client).spawn("snap", "box", gpus=1)
    assert client.calls == []
