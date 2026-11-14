"""An episode on the canvas: a planned explainer, taken from notes to a rendered film.

An episode is a piece of work in a task, like any asset, with a studio of its own. A person
starts one from material (their words and files, or a research frame's notes), picks who
writes it (a coding agent on this computer or the built-in agent), and then:

- **the plan** is written in stages by that agent, each stage read by a classifier and checked
  by code before the next (`design_agent.episode`); the person approves it once;
- **each chapter** is worked in one place: who has the frame for every line, the layout, and
  whether a picture is made at once (simple) or posed as stills for the person's go (rich).
  The pictures are built meanwhile, by the same agent, and posed on the thread's computer;
- **a take** per chapter is recorded in the browser (or brought as a file) and cut to the
  film's format; where a line was started in the take sets when its picture's cues land;
- **the film** is one HyperFrames project written by code (`episode.film`) and rendered on the
  thread's computer.

A person's picks are never undone by a later stage: they are kept beside the plan and applied
every time it is read. Nothing here is sent anywhere: the film is a file on the canvas.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from design_agent.episode import (
    check,
    classifier,
    classify,
    derive,
    film,
    geometry,
    override,
    picture,
    timeline,
    units,
)
from design_agent.episode import plan as plans
from design_agent.episode import questions as Q
from design_agent.surfaces.web import research
from design_agent.surfaces.web.computer import GSAP, PROJECTS, Computer
from design_agent.surfaces.web.episode_workers import (
    BUILTIN,
    DEMO,
    BuiltinWorker,
    DemoWorker,
    LocalWorker,
    Told,
    Worker,
)
from design_agent.surfaces.web.hub import Hub
from design_agent.surfaces.web.store import Row, Store, new_id
from design_agent.workspace.manifest import ManifestBook

if TYPE_CHECKING:
    from design_agent.surfaces.web.agent import AgentHost

_LOGGER = logging.getLogger(__name__)

#: An episode's own task thread, and its asset on the canvas.
EPISODE = "episode"
#: Fix rounds a stage gets before the plan goes on with what the checks still flag.
ROUNDS = 3
#: Tries a picture gets before it is left for the person to send back.
PICTURE_TRIES = 3
#: Pictures built at once by a local agent. The built-in agent builds one at a time: its
#: thread holds one turn.
PICTURES_AT_ONCE = 2
MATERIAL_CHARS = 200_000
TEXT_FILES = (".md", ".markdown", ".txt", ".rst", ".json", ".csv", ".html", ".htm")
SECONDS = (240, 600, 360)
THEMES = Q.table("themes")
LEVELS = units.LEVELS
VOICES = ("live", "narrator")
#: The stages a plan is written in, as the studio names them while it waits.
STEPS: tuple[tuple[str, str], ...] = (
    ("brief", "Read the material"),
    ("script", "Write the script"),
    ("frames", "Frame every line"),
    ("check", "Check the plan"),
)
PROGRESS = re.compile(r"@hf-progress (\{[^\n]*\})")
#: The renderer's check prints its findings under these heads. A file that breaks the first two
#: does not render as written; the rest are about how it looks.
CHECK_SECTIONS = ("Lint", "Runtime", "Layout", "Motion", "Contrast", "Snapshots")
BREAKING = ("Lint", "Runtime")
GENERIC = ("system-ui", "sans-serif", "serif", "monospace", "ui-monospace", "ui-sans-serif")
LINT_ERROR = re.compile(r"✗\s*(?:\[[^\]]*\]\s*)?(.+)")


def _clean(text: str, limit: int = 300) -> str:
    return " ".join(str(text).split())[:limit]


class EpisodeDesk:
    def __init__(
        self,
        *,
        host: AgentHost,
        store: Store,
        hub: Hub,
        data_dir: Path,
        project_root: Path,
        demo: bool = False,
    ) -> None:
        self.host = host
        self.store = store
        self.hub = hub
        self.data_dir = data_dir
        self.project_root = project_root
        self.demo = demo
        #: Tests and the demo hand in their own writers and reader.
        self.workers: dict[str, Worker] = {}
        self.reader: classifier.Ask | None = None
        self._jobs: dict[str, asyncio.Task[None]] = {}
        self._builds: dict[tuple[str, str], asyncio.Task[None]] = {}
        self._gates: dict[str, asyncio.Semaphore] = {}
        self._said_at: dict[str, float] = {}
        self._closing = False
        #: The brand pack a thread's channel wears (the app's brand shelf), or None for the
        #: configured one.
        self.brand_for: Callable[[str], Path | None] | None = None
        self._book: ManifestBook | None = None

    # -- what an episode can be made with -------------------------------------------------------

    def options(self) -> dict[str, Any]:
        writers: list[dict[str, Any]] = []
        if self.demo:
            writers.append(
                {"id": DEMO, "title": "The demo's writer", "ready": True, "local": False}
            )
        else:
            for harness in research.HARNESSES.values():
                writers.append(
                    {
                        "id": harness.id,
                        "title": harness.title,
                        "ready": self.host.research.ready(harness.id),
                        "local": True,
                    }
                )
            writers.append(
                {
                    "id": BUILTIN,
                    "title": "Built-in agent",
                    "ready": self.host.runtime is not None,
                    "local": False,
                }
            )
        return {
            "writers": writers,
            "themes": [
                {"id": t["id"], "name": t["name"], "presenter": t["presenter"], "stage": t["stage"]}
                for t in Q.TYPES["themes"]
            ],
            "seconds": {"least": SECONDS[0], "most": SECONDS[1], "usual": SECONDS[2]},
            "reader": "demo" if self.demo else "jev" if self._jev_key() else "writer",
            "narrator": self._narrator_ready(),
            "geometry": geometry.view(),
        }

    def _jev_key(self) -> str:
        key = self.host.settings.typesafe_api_key
        return key.get_secret_value() if key is not None else ""

    def _narrator_ready(self) -> bool:
        settings = self.host.settings
        return bool(settings.elevenlabs_api_key and settings.narrator_voice_id)

    def _worker(self, episode: Row) -> Worker:
        writer = str(episode["settings"].get("writer") or "")
        if writer in self.workers:
            return self.workers[writer]
        made: Worker
        if writer == BUILTIN:
            made = BuiltinWorker(self.host, self.project_root)
        elif writer == DEMO:
            from design_agent.surfaces.web.demo_episode import SCRIPT

            made = DemoWorker(data_dir=self.data_dir, script=SCRIPT)
        elif writer in research.HARNESSES:
            made = LocalWorker(
                writer, store=self.store, data_dir=self.data_dir, project_root=self.project_root
            )
        else:
            raise ValueError(f"There is no writer called {writer}.")
        self.workers[writer] = made
        return made

    def _reader(self, worker: Worker) -> classifier.Ask:
        if self.reader is not None:
            return self.reader
        if isinstance(worker, DemoWorker):
            return _first_option
        key = self._jev_key()
        return classifier.jev(key) if key else classifier.model(worker.complete)

    def _brand_root(self, thread_id: str) -> Path | None:
        """The brand pack a thread's work wears: its channel's, else the configured one."""
        folder = self.brand_for(thread_id) if self.brand_for is not None else None
        if folder is None:
            folder = self.host.settings.resolved_brand_path(self.project_root)
        return folder if (folder / "brand.toml").is_file() else None

    def _look(self, episode: Row) -> picture.Look:
        """What the episode's pictures and the film's own cards wear: the brand's colours by
        role and the first family of each of its type stacks."""
        root = self._brand_root(str(episode["thread_id"]))
        if root is None:
            return picture.Look()
        from design_agent.surfaces.web.brands import brand_view

        view = brand_view(root)
        roles = {str(r["role"]): str(r["value"]) for r in view.get("roles") or []}
        palette = dict(picture.PALETTE)
        for ours, theirs in (
            ("ground", "ground"),
            ("ink", "ink"),
            ("accent", "accent"),
            ("muted", "muted"),
            ("line", "rule"),
        ):
            if roles.get(theirs):
                palette[ours] = roles[theirs]
        if roles.get("accent"):
            palette["accent_ink"] = "#FFFFFF" if _dark(roles["accent"]) else palette["ink"]
        stacks = view.get("stacks") or {}

        def family(role: str, otherwise: str) -> str:
            named = [str(n) for n in stacks.get(role) or [] if str(n).lower() not in GENERIC]
            return named[0] if named else otherwise

        return picture.Look(
            palette=palette,
            display=family("display", "Fraunces"),
            text=family("text", "Inter"),
            mono=family("mono", "IBM Plex Mono"),
        )

    def _ready(self, episode: Row) -> Computer:
        """The thread's computer with the brand pack and its fonts staged, as the engine's own
        runs stage them, for a thread no engine run has touched (a local writer's)."""
        computer = self._computer(episode)
        components = getattr(self.host.runtime, "components", None)
        if components is None:
            return computer
        manifest = components.manifest
        if self.brand_for is not None:
            if self._book is None:
                self._book = ManifestBook(self.project_root, manifest, self.brand_for)
            manifest = self._book.for_thread(str(episode["thread_id"]))
        try:
            computer.stage(manifest)
        except Exception:  # the stills still pose; type falls back to what the computer has
            _LOGGER.exception("staging failed on %s", episode["thread_id"])
        return computer

    def _computer(self, episode: Row) -> Computer:
        runtime = self.host.runtime
        if runtime is None:
            raise RuntimeError("the agent runtime is not started")
        return Computer(runtime.binding, str(episode["thread_id"]), self.project_root)

    # -- starting one ---------------------------------------------------------------------------

    def create(
        self,
        channel_id: str,
        *,
        by: str,
        title: str = "",
        text: str = "",
        file_ids: Sequence[str] = (),
        frame_id: str = "",
        settings: Mapping[str, Any] | None = None,
    ) -> Row:
        """An episode from material: the person's words and files in a task of its own, or a
        research frame's notes in that frame."""
        chosen = self._settings(settings or {})
        words = text.strip()
        material = [words] if words else []
        if frame_id:
            frame = self.store.thread(frame_id)
            if frame is None or self.store.research(frame_id) is None:
                raise KeyError(frame_id)
            notes = self.host.research.notes_markdown(frame_id)
            if not notes:
                raise ValueError("Keep a note from the research first: an episode starts there.")
            material.insert(0, notes)
            thread = frame
        else:
            for file_id in file_ids:
                row = self.store.file(file_id)
                if row is not None and str(row["name"]).lower().endswith(TEXT_FILES):
                    body = (self.host.files_dir / row["rel_path"]).read_text("utf8", "replace")
                    material.append(f"# {row['name']}\n\n{body}")
            if not material:
                raise ValueError("An episode starts from material: paste notes or add a text file.")
            name = title.strip() or self._title(material[0])
            thread = self.store.add_thread(
                thread_id=new_id("th"),
                channel_id=channel_id,
                task=True,
                title=name,
                kind=EPISODE,
                by=by,
            )
            self.hub.publish("thread.created", thread=self.host.thread_view(thread))
            files = [f for f in (self.store.file(i) for i in file_ids) if f is not None]
            root = self.store.add_message(
                message_id=thread["id"],
                channel_id=channel_id,
                thread_id=thread["id"],
                author_id=by,
                kind="person",
                text=words or f"An episode from {len(files)} file(s)",
                data={"kind": EPISODE, "files": [self.host.file_view(f) for f in files]},
            )
            self.store.attach_files(file_ids, thread["id"])
            self.hub.publish("message.created", message=root)
        body = "\n\n".join(material)[:MATERIAL_CHARS]
        name = title.strip() or self._title(body)
        asset = self.host.new_asset(
            str(thread["id"]), kind=EPISODE, title=name, by=by, status="making"
        )
        episode = self.store.add_episode(
            {
                "thread_id": thread["id"],
                "asset_id": asset["id"],
                "title": name,
                "status": "planning",
                "material": body,
                "settings": chosen,
                "started_by": by,
            }
        )
        self._start_plan(str(episode["id"]))
        return self.view(str(episode["id"]))

    def _title(self, text: str) -> str:
        for line in text.splitlines():
            words = line.strip().lstrip("#").strip()
            if words:
                return words[:72]
        return "An episode"

    def _settings(self, given: Mapping[str, Any], base: Mapping[str, Any] | None = None) -> Row:
        out: Row = dict(
            base or {"seconds": SECONDS[2], "presenter": "on", "voice": "live", "level": "simple"}
        )
        if "seconds" in given:
            out["seconds"] = int(min(max(int(given["seconds"]), SECONDS[0]), SECONDS[1]))
        if given.get("presenter") in ("on", "off"):
            out["presenter"] = given["presenter"]
        if "theme" in given:
            if given["theme"] not in THEMES:
                raise ValueError(f"There is no look called {given['theme']}.")
            out["theme"] = given["theme"]
        if (
            out.get("presenter") == "off"
            or THEMES.get(str(out.get("theme")), {}).get("presenter") == "off"
        ):
            out["presenter"], out["theme"] = "off", "voice-only"
        out.setdefault("theme", "corner-window")
        if given.get("voice") in VOICES:
            out["voice"] = given["voice"]
        if given.get("level") in LEVELS:
            out["level"] = given["level"]
        if "writer" in given:
            writer = str(given["writer"])
            ready = {w["id"] for w in self.options()["writers"] if w["ready"]}
            if writer not in ready and writer not in self.workers:
                raise ValueError("That writer isn't ready on this computer.")
            out["writer"] = writer
        if "writer" not in out:
            first = next((w["id"] for w in self.options()["writers"] if w["ready"]), "")
            if not first:
                raise ValueError("No writer is ready: install a coding agent or set a model.")
            out["writer"] = first
        return out

    # -- reading the plan -----------------------------------------------------------------------

    def _episode(self, episode_id: str) -> Row:
        episode = self.store.episode(episode_id)
        if episode is None:
            raise KeyError(episode_id)
        return episode

    def _merged(self, episode: Row) -> Row:
        """The writer's plan under the classifier's labels, with what the person chose for the
        film laid over the brief: their facts win, and the writer's file is never rewritten."""
        merged = plans.merged(episode["plan"] or {}, episode["labels"] or {})
        brief = merged.setdefault("brief", {})
        chosen = episode["settings"]
        brief["seconds"] = chosen.get("seconds", SECONDS[2])
        if chosen.get("presenter") == "off":
            brief["presenter"], brief["theme"] = "off", "voice-only"
        else:
            brief["presenter"], brief["theme"] = "on", chosen.get("theme", "corner-window")
        return merged

    def _full(self, episode: Row) -> Row | None:
        """Everything code derives from the plan, or None before it has frames."""
        merged = self._merged(episode)
        if not any(f.get("presence") for _, _, f in plans.frames_of(merged)):
            return None
        full = derive.full(merged)
        full["title"] = episode["title"]
        return full

    def _units(self, episode: Row, full: Row) -> list[Row]:
        return units.units(
            full, episode["picks"] or {}, level=str(episode["settings"].get("level", "simple"))
        )

    # -- planning: the writer's turns, each read and checked ---------------------------------

    def _start_plan(self, episode_id: str, *, stage: str = "brief", redo: str = "") -> None:
        running = self._jobs.get(episode_id)
        if running is not None and not running.done():
            raise ValueError("It's still being written. Wait for it, or stop it first.")
        self._jobs[episode_id] = asyncio.get_running_loop().create_task(
            self._planned(episode_id, stage, redo), name=f"episode plan {episode_id}"
        )

    def planning(self, episode_id: str) -> bool:
        job = self._jobs.get(episode_id)
        return job is not None and not job.done()

    async def _planned(self, episode_id: str, stage: str, redo: str) -> None:
        try:
            await self._plan(episode_id, stage, redo)
        except asyncio.CancelledError:
            self._stage(episode_id, state="stopped", said="Stopped.")
            self._set(episode_id, status="failed")
        except Exception as error:  # a writer that misbehaves must not take the house down
            _LOGGER.exception("episode plan failed on %s", episode_id)
            self._stage(episode_id, state="failed", said=f"It stopped: {_clean(str(error), 200)}")
            self._set(episode_id, status="failed")
        finally:
            self._jobs.pop(episode_id, None)
            self._settle(episode_id)

    def _stage(self, episode_id: str, **change: Any) -> None:
        episode = self._episode(episode_id)
        stage = {**(episode["stage"] or {}), **change}
        self.store.update_episode(episode_id, stage=stage)
        self._changed(episode_id)

    def _heard(self, episode_id: str) -> Any:
        def heard(kind: str, text: str) -> None:
            if kind != "step":
                return
            now = time.time()
            episode = self._episode(episode_id)
            self.store.update_episode(
                episode_id, stage={**(episode["stage"] or {}), "said": _clean(text, 120)}
            )
            if now - self._said_at.get(episode_id, 0.0) >= 1.0:
                self._said_at[episode_id] = now
                self._changed(episode_id)

        return heard

    async def _plan(self, episode_id: str, start: str, redo: str) -> None:
        episode = self._episode(episode_id)
        worker = self._worker(episode)
        self._set(episode_id, status="planning" if not episode["approved"] else episode["status"])
        self._stage(
            episode_id, name=start, round=0, state="working", said="Getting ready", at=time.time()
        )
        files = {"material/notes.md": str(episode["material"])}
        if not episode["plan"]:
            files["plan.json"] = "{}\n"
        await worker.prepare(episode, files)
        order = ["brief", "script", "frames"]
        todo = ["redo"] if redo else order[order.index(start) :]
        report: list[str] = []
        for name in todo:
            episode = self._episode(episode_id)
            if name == "frames":
                # who has the frame is read from the script before anything is designed
                report = await self._read(episode_id, worker, ["frames"], checks="")
            prompt = self._prompt(episode, worker, name, report, redo)
            for round_number in range(ROUNDS + 1):
                self._stage(episode_id, name=name, round=round_number, state="working")
                told = await worker.turn(
                    self._episode(episode_id),
                    lane="plan",
                    prompt=prompt,
                    heard=self._heard(episode_id),
                )
                if told.stopped:
                    raise asyncio.CancelledError
                if not told.answer:
                    raise RuntimeError(told.failure or "the writer gave no reply")
                problems = await self._take_plan(episode_id, worker, name)
                if problems:
                    report = problems
                else:
                    self._stage(episode_id, state="reading", said="Reading what was written")
                    stages, checks = {
                        "brief": (["material"], ""),
                        "script": (["script"], "script"),
                        "frames": (["frames", "design"], "all"),
                        "redo": (["frames", "design"], "all"),
                    }[name]
                    report = await self._read(episode_id, worker, stages, checks=checks)
                    problems = self._blocking(episode_id, name)
                if not problems or round_number == ROUNDS:
                    break
                prompt = self._fix_prompt(self._episode(episode_id), worker, name, report)
        episode = self._episode(episode_id)
        full = self._full(episode)
        if full is None:
            raise RuntimeError("the plan has no frames yet")
        self._stage(episode_id, name="done", state="done", said="")
        status = "studio" if episode["approved"] else "plan"
        self._set(episode_id, status=status)
        if episode["approved"]:
            self._queue_pictures(episode_id)

    async def _take_plan(self, episode_id: str, worker: Worker, stage: str) -> list[str]:
        """Read the writer's plan.json into the episode. Returns what is wrong with its shape."""
        text = await worker.read(self._episode(episode_id), "plan.json")
        if text is None:
            return ["plan.json is not in your folder: write it there."]
        try:
            plan = json.loads(text)
        except ValueError as error:
            return [f"plan.json is not valid JSON ({error}): fix the file."]
        problems = _shape(plan, stage)
        if not problems:
            self.store.update_episode(episode_id, plan=plan)
            if isinstance(worker, DemoWorker):
                # the demo's plan comes with the labels it was read with
                self.store.update_episode(episode_id, labels=worker.script.get("labels") or {})
        return problems

    async def _read(
        self, episode_id: str, worker: Worker, stages: Sequence[str], *, checks: str
    ) -> list[str]:
        """Have the plan's words read (classified) for these stages and, with `checks`, held to
        the rules. Keeps the labels and the findings; returns the report the writer is shown."""
        episode = self._episode(episode_id)
        merged = self._merged(episode)
        ask = self._reader(worker)
        lines: list[str] = []
        for stage in stages:
            if stage == "design" and not any(f.get("shows") for _, _, f in plans.frames_of(merged)):
                continue
            said = await asyncio.to_thread(classify.classify, merged, stage, ask)
            lines.append(f"classified: {stage}")
            lines.extend(f" - {line}" for line in said)
        rows: list[Row] = []
        if checks:
            rows = check.check(merged, checks)
            lines.extend(check.lines(rows, checks, merged if checks == "all" else None))
        self.store.update_episode(
            episode_id,
            labels=plans.labels_of(merged),
            report={"rows": rows, "lines": lines, "at": time.time()},
        )
        return lines

    def _blocking(self, episode_id: str, stage: str) -> list[str]:
        """What still stops this stage from being done: the checks' musts, a line that needs a
        picture and has none, a brief with nothing in it."""
        episode = self._episode(episode_id)
        merged = self._merged(episode)
        out = [f"{r['where']}: {r['text']}" for r in check.musts(episode["report"].get("rows", []))]
        if stage == "brief":
            brief = merged.get("brief", {})
            out += [f"the brief has no `{k}`" for k in ("idea", "gap", "for") if not brief.get(k)]
            if len(merged.get("material", [])) < 3:
                out.append("cut the material into at least three items")
        if stage in ("frames", "redo"):
            for _ch, _b, f in plans.frames_of(merged):
                bare = f.get("presence") in ("both", "content") and not f.get("shows")
                if bare and not f.get("hold"):
                    out.append(f"{f['id']} needs a picture: write `shows`, objects and cues")
        return out

    def _prompt(
        self, episode: Row, worker: Worker, stage: str, report: Sequence[str], redo: str
    ) -> str:
        root, skill = worker.place(episode)
        chosen = episode["settings"]
        said = "\n".join(report)
        if stage == "brief":
            presenter = "off (a voice only)" if chosen.get("presenter") == "off" else "on"
            return (
                f"Stage: brief.\n\nYour folder is {root}. The skill is {skill}/SKILL.md: read it "
                f'first, then {skill}/references/script.md ("The brief"). The material is '
                f"{root}/material/notes.md.\n\nThe person chose: {chosen.get('seconds')} seconds, "
                f"presenter {presenter}, theme `{chosen.get('theme')}`, working title "
                f"“{episode['title']}”. Put these in the brief as given.\n\nWrite "
                f"{root}/plan.json with `material` and `brief` only. Reply with the idea in one "
                "sentence and what the material lacks."
            )
        if stage == "script":
            return (
                f"Stage: script.\n\nYour brief was read:\n\n{said}\n\nRead "
                f"{skill}/references/script.md and {skill}/references/types.md. Write the "
                f"spine and every chapter's beats into {root}/plan.json, keeping `brief` and "
                "`material` as they are. Give no beat a `frames` list yet. Reply with the "
                "chapters, one line each."
            )
        if stage == "frames":
            return (
                f"Stage: frames.\n\nEvery line was read for who has the frame:\n\n{said}\n\n"
                f"Read {skill}/references/frames.md and {skill}/references/motion.md. For every "
                "frame marked NEEDS A PICTURE, write its `shows`, `focal`, `objects` and `cues` "
                f"in {root}/plan.json; let a picture grow across beats with `hold`. Change no "
                "`says`. Reply with the pictures you designed, one line each."
            )
        return (
            "Stage: redo.\n\nA person changed who has the frame. What that leaves for you:\n\n"
            f"{redo}\n\nDo only that, in {root}/plan.json, following {skill}/references/plan.md "
            '("When a person changes who has the frame"). Never undo a pick. Reply with what '
            "you changed."
        )

    def _fix_prompt(self, episode: Row, worker: Worker, stage: str, report: Sequence[str]) -> str:
        root, _ = worker.place(episode)
        said = "\n".join(report)
        return (
            f"Stage: fix (the {stage} stage).\n\nYour plan was read and checked:\n\n{said}\n\n"
            f"Fix every MUST, and each look you do not waive, in {root}/plan.json. Change "
            "nothing else. Reply with what you changed."
        )

    def stop(self, episode_id: str) -> None:
        job = self._jobs.get(episode_id)
        if job is not None and not job.done():
            job.cancel()

    def again(self, episode_id: str, *, writer: str = "") -> Row:
        """Pick the planning up where it stopped, with another writer if one is named: the
        files and the house's record of the turns carry over."""
        episode = self._episode(episode_id)
        if writer:
            chosen = self._settings({"writer": writer}, episode["settings"])
            self.store.update_episode(episode_id, settings=chosen)
        stage = str((episode["stage"] or {}).get("name") or "brief")
        self._start_plan(
            episode_id, stage=stage if stage in ("brief", "script", "frames") else "brief"
        )
        return self.view(episode_id)

    # -- the person's side: approving, picking -------------------------------------------------

    def approve(self, episode_id: str, *, by: str) -> Row:
        episode = self._episode(episode_id)
        if self._full(episode) is None or self.planning(episode_id):
            raise ValueError("The plan isn't written yet.")
        self.store.update_episode(episode_id, approved=True, status="studio")
        self._say(episode, f"Approved the plan of “{episode['title']}”.", by=by)
        self._queue_pictures(episode_id)
        self._settle(episode_id)
        return self.view(episode_id)

    def choose(self, episode_id: str, *, by: str, change: Mapping[str, Any]) -> Row:
        """A person's picks: the film's look, voice and default level, who has the frame (for a
        line, a chapter or the whole film), and a picture's level."""
        episode = self._episode(episode_id)
        if self.planning(episode_id):
            raise ValueError("The plan is being written. Pick again when it has landed.")
        before = dict(episode["settings"])
        chosen = self._settings(change.get("settings") or {}, before)
        picks: Row = {"units": dict((episode["picks"] or {}).get("units", {}))}
        for unit_id, pick in (change.get("units") or {}).items():
            if pick.get("level") in LEVELS:
                picks["units"][str(unit_id)] = {"level": pick["level"]}
        self.store.update_episode(episode_id, settings=chosen, picks=picks)
        episode = self._episode(episode_id)
        merged = self._merged(episode)
        new: Row = {k: change[k] for k in ("frames", "chapters", "all", "clear") if change.get(k)}
        if chosen.get("presenter") == "off" and before.get("presenter") != "off":
            new["presenter"] = "off"
        feedback: list[Row] = []
        if any(f.get("presence") for _, _, f in plans.frames_of(merged)):
            feedback = override.apply(merged, new)
            self.store.update_episode(episode_id, labels=plans.labels_of(merged))
        left = override.redo(feedback)
        if left and not self.demo:
            told = "\n".join(
                f"- {x['where']}: {x['was']} is now {x['now']}. {x['do']}" for x in left
            )
            self._start_plan(episode_id, redo=told)
        elif self._episode(episode_id)["approved"]:
            self._queue_pictures(episode_id)
        self._say(episode, "Changed the episode's choices.", by=by, quiet=True)
        self._settle(episode_id)
        return self.view(episode_id)

    # -- pictures: built by the writer, posed on the thread's computer -------------------------

    def _queue_pictures(self, episode_id: str) -> None:
        """Start every picture that is not built from the plan as it stands. One that failed is
        not tried again by itself: the person sends it back, or changes what it is built from."""
        episode = self._episode(episode_id)
        full = self._full(episode)
        if full is None or not episode["approved"] or self._closing:
            return
        for unit in self._units(episode, full):
            if unit["kind"] != "picture":
                continue
            have = self.store.picture(episode_id, unit["id"])
            fresh = have is not None and have["sig"] == unit["sig"]
            running = self._builds.get((episode_id, unit["id"]))
            if have is not None and fresh:
                # Its level is the person's: a picture made rich waits for their go on its
                # stills, and one made simple again no longer does.
                rich = unit["level"] == units.RICH
                if rich and have["status"] == "made" and have["go_sig"] != unit["sig"]:
                    self.store.set_picture(episode_id, unit["id"], status="go")
                elif not rich and have["status"] == "go":
                    self.store.set_picture(episode_id, unit["id"], status="made")
            if fresh or (running is not None and not running.done()):
                continue
            self.store.set_picture(
                episode_id, unit["id"], status="queued", failure="", sig=unit["sig"]
            )
            self._builds[(episode_id, unit["id"])] = asyncio.get_running_loop().create_task(
                self._built(episode_id, unit["id"]), name=f"picture {episode_id} {unit['id']}"
            )
        self._changed(episode_id)

    async def _built(self, episode_id: str, unit_id: str) -> None:
        episode = self._episode(episode_id)
        at_once = 1 if episode["settings"].get("writer") == BUILTIN else PICTURES_AT_ONCE
        gate = self._gates.setdefault(episode_id, asyncio.Semaphore(at_once))
        try:
            async with gate:
                await self._build(episode_id, unit_id)
        except asyncio.CancelledError:
            self.store.set_picture(episode_id, unit_id, status="failed", failure="Stopped.")
        except Exception as error:  # one picture failing must not stop the others
            _LOGGER.exception("picture failed on %s %s", episode_id, unit_id)
            self.store.set_picture(
                episode_id, unit_id, status="failed", failure=_clean(str(error), 240)
            )
        finally:
            self._builds.pop((episode_id, unit_id), None)
            self._settle(episode_id)
            # a pick made while it was building asks for it again
            with contextlib.suppress(KeyError, RuntimeError):
                self._queue_pictures(episode_id)

    async def _build(self, episode_id: str, unit_id: str, note: str = "") -> None:
        episode = self._episode(episode_id)
        full = self._full(episode)
        unit = next((u for u in self._units(episode, full or {}) if u["id"] == unit_id), None)
        if full is None or unit is None:
            return
        worker = self._worker(episode)
        comp = picture.composition_id(unit_id)
        look = self._look(episode)
        brief = picture.brief(unit, full, look=look, note=note)
        root, skill = worker.place(episode)
        self.store.set_picture(episode_id, unit_id, status="making", sig=unit["sig"], failure="")
        self._changed(episode_id)
        await worker.prepare(
            episode,
            {f"pictures/{comp}.brief.json": json.dumps(brief, indent=1, ensure_ascii=False)},
        )
        prompt = (
            f"Stage: picture.\n\nBuild one picture of the episode. Your folder is {root}. Read "
            f"{skill}/briefs/picture.md, then the brief at {root}/pictures/{comp}.brief.json, "
            f"and write {root}/{brief['file']}."
            + (f"\n\nThe person's note on it: {note}" if note else "")
        )
        html = ""
        faults: list[str] = []
        stills: dict[str, str] = {}
        for attempt in range(PICTURE_TRIES):
            told: Told = await worker.turn(
                self._episode(episode_id),
                lane=f"picture:{unit_id}",
                prompt=prompt,
                heard=lambda _kind, _text: None,
            )
            if told.stopped:
                raise asyncio.CancelledError
            html = await worker.read(self._episode(episode_id), str(brief["file"])) or ""
            faults = (
                picture.faults(html, unit, full, look)
                if html
                else [f"{brief['file']} was not written"]
            )
            if not faults:
                self.store.set_picture(episode_id, unit_id, status="posing", html=html)
                self._changed(episode_id)
                # What the layout and contrast checks flag is sent back, but never keeps a
                # picture that renders from being used: the last try holds it to less.
                faults, stills = await asyncio.to_thread(
                    self._pose, episode, unit, full, html, attempt < PICTURE_TRIES - 1
                )
            if not faults:
                break
            listed = "\n".join(f"- {f}" for f in faults[:12])
            prompt = (
                f"Stage: picture.\n\n{root}/{brief['file']} can't be used yet:\n\n{listed}\n\n"
                "Change only what these name, and reply with what you changed."
            )
        if faults:
            self.store.set_picture(
                episode_id, unit_id, status="failed", html=html, failure="; ".join(faults[:3])
            )
            return
        level = unit["level"]
        if level == units.RICH:
            html, stills = await self._looked(episode_id, unit, full, brief, html, stills)
        self.store.set_picture(
            episode_id,
            unit_id,
            status="go" if level == units.RICH else "made",
            html=html,
            stills=stills,
            note="",
            failure="",
        )
        self._changed(episode_id)
        clip = await asyncio.to_thread(self._clip, episode, unit)
        if clip:
            self.store.set_picture(episode_id, unit_id, clip=clip)

    async def _looked(
        self, episode_id: str, unit: Row, full: Row, brief: Row, html: str, stills: dict[str, str]
    ) -> tuple[str, dict[str, str]]:
        """A rich picture's builder looks at its own stills once and fixes what it sees: what
        only a render shows (an overlap, a label cut off, something under the person's window).
        A fix that breaks the file is dropped; the picture it had stands."""
        episode = self._episode(episode_id)
        worker = self._worker(episode)
        root, _ = worker.place(episode)
        comp = brief["composition_id"]
        images: dict[str, bytes] = {}
        for n, frame_id in enumerate(unit["frames"], start=1):
            row = self.store.file(stills.get(frame_id, ""))
            if row is not None:
                images[f"pictures/{comp}.stills/{n}.png"] = (
                    self.host.files_dir / row["rel_path"]
                ).read_bytes()
        if not images:
            return html, stills
        await worker.show(episode, images)
        told = await worker.turn(
            episode,
            lane=f"picture:{unit['id']}",
            prompt=(
                f"Stage: picture.\n\nLook at how {root}/{brief['file']} came out. Its stills, "
                f"one taken at the end of each line, in line order, are in "
                f"{root}/pictures/{comp}.stills/. Open each one. If anything overlaps, is cut "
                "off, is too small to read, sits where the brief says to keep clear, or a "
                "still does not show what its line added, fix the file. If they are right, "
                "change nothing and reply “Nothing to change.”"
            ),
            heard=lambda _kind, _text: None,
        )
        if told.stopped:
            raise asyncio.CancelledError
        again = await worker.read(episode, str(brief["file"])) or ""
        if not again or again == html or picture.faults(again, unit, full, self._look(episode)):
            return html, stills
        self.store.set_picture(episode_id, unit["id"], status="posing")
        self._changed(episode_id)
        faults, posed = await asyncio.to_thread(self._pose, episode, unit, full, again)
        return (html, stills) if faults else (again, posed)

    def _pose_dir(self, episode: Row, unit: Row) -> str:
        return f"{PROJECTS}/{episode['id']}/pose/{picture.composition_id(unit['id'])}"

    def _pose(
        self, episode: Row, unit: Row, full: Row, html: str, strict: bool = True
    ) -> tuple[list[str], dict[str, str]]:
        """Check one picture and take a still at the end of each of its lines, on the plan's
        clock. Returns the faults (empty when it stands) and the stills' file ids by line.
        `strict` also counts what the layout, motion and contrast checks flag."""
        computer = self._ready(episode)
        comp = picture.composition_id(unit["id"])
        own = picture.clock(unit, timeline.schedule(full))
        look = self._look(episode)
        folder = self._pose_dir(episode, unit)
        computer.put(
            [
                (
                    f"{folder}/index.html",
                    picture.stage(unit, own, ground=look.palette["ground"]).encode(),
                ),
                (
                    f"{folder}/{picture.FOLDER}/{comp}.html",
                    picture.dressed(html, own, look).encode(),
                ),
            ]
        )
        times = picture.still_times(own)
        wanted = ",".join(f"{t:.3f}".rstrip("0").rstrip(".") for t in times.values())
        ran = computer.run(
            f"cd {folder} && cp -n {GSAP} gsap.min.js; rm -rf stills; "
            f"hyperframes check . 2>&1 | tail -80; echo ---; "
            f"hyperframes snapshot . --at {wanted} --no-end --keep -o stills --describe false "
            "2>&1 | tail -5; ls stills 2>/dev/null",
            timeout=600,
        )
        broken, flagged = _findings(ran.output.split("---", 1)[0])
        if broken or (strict and flagged):
            return [*broken, *flagged], {}
        stills: dict[str, str] = {}
        for frame_id, at in times.items():
            name = f"at-{f'{at:.3f}'.rstrip('0').rstrip('.')}s.png"
            content = computer.get(f"{folder}/stills/{name}")
            if content is None:
                return [f"no still could be taken at {at:.2f} s: {_clean(ran.output[-300:])}"], {}
            row = self.host.save_file(
                str(episode["thread_id"]),
                f"{comp}-{frame_id.replace('.', '-')}.png",
                content,
                origin="episode",
            )
            stills[frame_id] = str(row["id"])
        return [], stills

    def _clip(self, episode: Row, unit: Row) -> str:
        """A draft clip of one picture on the plan's clock, for playing it in the studio."""
        computer = self._computer(episode)
        folder = self._pose_dir(episode, unit)
        ran = computer.run(
            f"cd {folder} && hyperframes render . --quality draft --fps 30 --output clip.mp4 "
            "--quiet 2>&1 | tail -3",
            timeout=1800,
        )
        content = computer.get(f"{folder}/clip.mp4") if ran.ok else None
        if not content:
            return ""
        name = f"{picture.composition_id(unit['id'])}.mp4"
        return str(
            self.host.save_file(str(episode["thread_id"]), name, content, origin="episode")["id"]
        )

    def go(self, episode_id: str, unit_id: str, *, by: str) -> Row:
        """The person's go on a rich picture's stills: it counts as made."""
        have = self.store.picture(episode_id, unit_id)
        if have is None or have["status"] not in ("go", "made"):
            raise ValueError("Its stills aren't posed yet.")
        self.store.set_picture(episode_id, unit_id, status="made", go_sig=have["sig"])
        self._say(
            self._episode(episode_id), "Gave the go on a picture's stills.", by=by, quiet=True
        )
        self._settle(episode_id)
        return self.view(episode_id)

    def send_back(self, episode_id: str, unit_id: str, *, by: str, note: str) -> Row:
        """A person's note on a picture: it is built again with the note."""
        if not note.strip():
            raise ValueError("Say what to change.")
        running = self._builds.get((episode_id, unit_id))
        if running is not None and not running.done():
            raise ValueError("It's being built. Send the note when it has landed.")
        self.store.set_picture(episode_id, unit_id, status="queued", note=note.strip()[:600])
        self._builds[(episode_id, unit_id)] = asyncio.get_running_loop().create_task(
            self._rebuilt(episode_id, unit_id, note.strip()[:600]),
            name=f"picture {episode_id} {unit_id}",
        )
        self._say(
            self._episode(episode_id),
            f"Sent a picture back: {note.strip()[:200]}",
            by=by,
            quiet=True,
        )
        self._settle(episode_id)
        return self.view(episode_id)

    async def _rebuilt(self, episode_id: str, unit_id: str, note: str) -> None:
        try:
            await self._build(episode_id, unit_id, note)
        except asyncio.CancelledError:
            self.store.set_picture(episode_id, unit_id, status="failed", failure="Stopped.")
        except Exception as error:  # one picture failing must not stop the others
            _LOGGER.exception("picture failed on %s %s", episode_id, unit_id)
            self.store.set_picture(
                episode_id, unit_id, status="failed", failure=_clean(str(error), 240)
            )
        finally:
            self._builds.pop((episode_id, unit_id), None)
            self._settle(episode_id)

    # -- takes -----------------------------------------------------------------------------------

    async def add_take(
        self,
        episode_id: str,
        *,
        by: str,
        chapter: str,
        frame: str = "",
        marks: Sequence[Mapping[str, Any]] = (),
        name: str,
        content: bytes,
    ) -> Row:
        """A recording of a chapter (or of one line of it): cut to the film's format on the
        thread's computer and kept as this chapter's take."""
        episode = self._episode(episode_id)
        full = self._full(episode)
        if full is None:
            raise ValueError("The plan isn't written yet.")
        found = next((c for c in full["chapters"] if c["id"] == chapter), None)
        if found is None:
            raise KeyError(chapter)
        lines = [f for b in found["beats"] for f in b["frames"]]
        if frame and frame not in {f["id"] for f in lines}:
            raise KeyError(frame)
        if not content:
            raise ValueError("The recording is empty.")
        made = await asyncio.to_thread(self._cut, episode, name, content)
        seconds = float(made["seconds"])
        given = [
            {"frame": str(m["frame"]), "t": round(max(0.0, float(m["t"])), 3)}
            for m in marks
            if str(m.get("frame")) in {f["id"] for f in lines}
        ]
        if not frame and not given:
            # A recording brought as a file: each line is taken to start where the plan's
            # pace puts it, stretched over the take.
            total = sum(float(f["seconds"]) for f in lines) or 1.0
            at = 0.0
            for f in lines:
                given.append({"frame": f["id"], "t": round(at / total * seconds, 3)})
                at += float(f["seconds"])
        for other in self.store.takes(episode_id):
            if other["chapter"] == chapter and other["frame"] == frame and other["kept"]:
                self.store.update_take(str(other["id"]), kept=False)
        self.store.add_take(
            {
                "episode_id": episode_id,
                "chapter": chapter,
                "frame": frame,
                "seconds": seconds,
                "marks": given,
                "video": made["video"],
                "audio": made["audio"],
                "kept": True,
                "added_by": by,
            }
        )
        self._say(
            episode,
            f"Recorded a take of chapter {full['chapters'].index(found) + 1}.",
            by=by,
            quiet=True,
        )
        self._settle(episode_id)
        return self.view(episode_id)

    def _cut(self, episode: Row, name: str, content: bytes) -> Row:
        """A recording as the film uses it: constant 30 frames a second with a key frame every
        half second (so any line can be played from where it starts), and its sound beside it."""
        computer = self._computer(episode)
        folder = f"{PROJECTS}/{episode['id']}/takes"
        stem = f"take-{int(time.time() * 1000)}"
        source = f"{folder}/{stem}.src{Path(name).suffix.lower()[:6] or '.webm'}"
        computer.put([(source, content)])
        ran = computer.run(
            f"cd {folder} && kinds=$(ffprobe -v error -show_entries stream=codec_type -of csv=p=0 "
            f"{source} | tr '\\n' ' '); echo \"kinds: $kinds\"; "
            f'case "$kinds" in *video*) ffmpeg -v error -y -i {source} '
            "-vf \"scale=-2:'min(1080,ih)',fps=30\" -c:v libx264 -preset veryfast -crf 20 -g 15 "
            f"-pix_fmt yuv420p -c:a aac -b:a 160k -ar 48000 -movflags +faststart {stem}.mp4 && "
            f"(ffmpeg -v error -y -i {stem}.mp4 -vn -c:a copy {stem}.m4a || true);; "
            f"*) ffmpeg -v error -y -i {source} -vn -c:a aac -b:a 160k -ar 48000 {stem}.m4a;; esac; "
            f'for f in {stem}.mp4 {stem}.m4a; do [ -s $f ] && echo "$f $(ffprobe -v error '
            '-show_entries format=duration -of csv=p=0 $f)"; done; '
            f"rm -f {source}",
            timeout=1800,
        )
        lengths = dict(re.findall(rf"({stem}\.(?:mp4|m4a)) ([0-9.]+)", ran.output))
        if not lengths:
            raise ValueError(f"The recording couldn't be read: {_clean(ran.output[-200:])}")
        out: Row = {"video": "", "audio": "", "seconds": max(float(v) for v in lengths.values())}
        thread_id = str(episode["thread_id"])
        for kind, suffix in (("video", "mp4"), ("audio", "m4a")):
            data = (
                computer.get(f"{folder}/{stem}.{suffix}") if f"{stem}.{suffix}" in lengths else None
            )
            if data:
                out[kind] = str(
                    self.host.save_file(thread_id, f"{stem}.{suffix}", data, origin="episode")["id"]
                )
        return out

    def keep_take(self, episode_id: str, take_id: str, *, keep: bool) -> Row:
        take = self.store.take(take_id)
        if take is None or take["episode_id"] != episode_id:
            raise KeyError(take_id)
        if keep:
            for other in self.store.takes(episode_id):
                if other["chapter"] == take["chapter"] and other["frame"] == take["frame"]:
                    self.store.update_take(str(other["id"]), kept=other["id"] == take_id)
        else:
            self.store.delete_take(take_id)
        self._settle(episode_id)
        return self.view(episode_id)

    # -- the film --------------------------------------------------------------------------------

    def _film_sig(self, episode: Row, full: Row) -> str:
        takes = [(t["id"], t["marks"]) for t in self.store.takes(str(episode["id"])) if t["kept"]]
        made = sorted(
            (p["unit"], p["sig"], plans.digest(p["html"]))
            for p in self.store.pictures(str(episode["id"]))
            if p["status"] in ("made", "go") and p["html"]
        )
        spoken = sorted((k, v.get("h")) for k, v in self._voice(episode).items())
        return plans.digest(
            json.dumps(
                [full.get("chapters"), full.get("brief"), takes, made, spoken], sort_keys=True
            )
        )

    def render(self, episode_id: str, *, by: str) -> Row:
        episode = self._episode(episode_id)
        if self._full(episode) is None or not episode["approved"]:
            raise ValueError("Approve the plan first.")
        if (episode["film"] or {}).get("status") == "rendering":
            raise ValueError("The film is already rendering.")
        self.store.update_episode(
            episode_id,
            film={**(episode["film"] or {}), "status": "rendering", "fraction": 0.0, "failure": ""},
        )
        self._jobs[f"film:{episode_id}"] = asyncio.get_running_loop().create_task(
            self._rendered(episode_id), name=f"episode film {episode_id}"
        )
        self._say(episode, f"Asked for the film of “{episode['title']}”.", by=by)
        self._settle(episode_id)
        return self.view(episode_id)

    async def _narrate(self, episode_id: str) -> None:
        """Speak every line no take covers, when the film is narrated. A line is spoken once:
        it is spoken again only when its words change."""
        episode = self._episode(episode_id)
        full = self._full(episode)
        if full is None or episode["settings"].get("voice") != "narrator":
            return
        if not self._narrator_ready():
            raise ValueError("Narration needs ELEVENLABS_API_KEY and a narrator voice.")
        from design_agent.tools.media import MediaKeys, speak

        keys = MediaKeys.from_settings(self.host.settings)
        voice_id = str(self.host.settings.narrator_voice_id)
        clock = timeline.schedule(full, self._kept(episode_id))
        lines = [f for _, _, f in plans.frames_of(full)]
        spoken: Row = dict((episode["film"] or {}).get("voice") or {})
        for i, f in enumerate(lines):
            line = timeline.line_of(clock, f["id"])
            words = str(f.get("vo") or "")
            mark = plans.digest(words, voice_id)
            if line is None or line["source"]["kind"] == "take" or not words.strip():
                continue
            if (spoken.get(f["id"]) or {}).get("h") == mark:
                continue
            said = await speak(
                keys,
                words,
                voice_id,
                previous_text=str(lines[i - 1].get("vo") or "") if i else None,
                next_text=str(lines[i + 1].get("vo") or "") if i + 1 < len(lines) else None,
            )
            if isinstance(said, str):
                raise ValueError(f"Narration stopped at line {f['id']}: {said}")
            row = self.host.save_file(
                str(episode["thread_id"]),
                f"voice-{f['id'].replace('.', '-')}.mp3",
                said.audio,
                origin="episode",
            )
            spoken[f["id"]] = {
                "file": row["id"],
                "seconds": said.seconds,
                "words": said.words,
                "h": mark,
            }
            episode = self._episode(episode_id)
            self.store.update_episode(episode_id, film={**(episode["film"] or {}), "voice": spoken})

    def _kept(self, episode_id: str) -> list[Row]:
        return [
            {
                "id": t["id"],
                "chapter": t["chapter"],
                "frame": t["frame"],
                "seconds": t["seconds"],
                "marks": t["marks"],
            }
            for t in self.store.takes(episode_id)
            if t["kept"]
        ]

    def _voice(self, episode: Row) -> Row:
        """The narration there is, by line, when the film is narrated."""
        if episode["settings"].get("voice") != "narrator":
            return {}
        return dict((episode["film"] or {}).get("voice") or {})

    async def _rendered(self, episode_id: str) -> None:
        try:
            await self._narrate(episode_id)
            await asyncio.to_thread(self._render, episode_id)
        except Exception as error:  # a render that fails must leave the episode usable
            _LOGGER.exception("episode film failed on %s", episode_id)
            episode = self._episode(episode_id)
            self.store.update_episode(
                episode_id,
                film={
                    **(episode["film"] or {}),
                    "status": "failed",
                    "failure": _clean(str(error), 300),
                },
            )
        finally:
            self._jobs.pop(f"film:{episode_id}", None)
            self._settle(episode_id)

    def _render(self, episode_id: str) -> None:
        episode = self._episode(episode_id)
        full = self._full(episode)
        if full is None:
            raise ValueError("The plan isn't written yet.")
        computer = self._ready(episode)
        folder = f"{PROJECTS}/{episode_id}/film"
        kept = [t for t in self.store.takes(episode_id) if t["kept"]]
        spoken = self._voice(episode)
        clock = timeline.schedule(full, self._kept(episode_id), spoken)
        media: list[tuple[str, bytes]] = []
        voice: dict[str, str] = {}
        for frame_id, said in spoken.items():
            row = self.store.file(str(said.get("file")))
            if row is not None:
                voice[frame_id] = f"voice/{frame_id.replace('.', '-')}.mp3"
                media.append(
                    (
                        f"{folder}/{voice[frame_id]}",
                        (self.host.files_dir / row["rel_path"]).read_bytes(),
                    )
                )
        takes: dict[str, Row] = {}
        for take in kept:
            entry: Row = {"video": "", "audio": ""}
            for kind, suffix in (("video", "mp4"), ("audio", "m4a")):
                row = self.store.file(str(take[kind])) if take[kind] else None
                if row is None:
                    continue
                path = f"takes/{take['id']}.{suffix}"
                media.append(
                    (f"{folder}/{path}", (self.host.files_dir / row["rel_path"]).read_bytes())
                )
                entry[kind] = path
            takes[str(take["id"])] = entry
        found = self._units(episode, full)
        pictures = {
            p["unit"]: p["html"]
            for p in self.store.pictures(episode_id)
            if p["html"] and p["status"] in ("made", "go")
        }
        files = film.project(
            full, clock, found, pictures, takes=takes, voice=voice, look=self._look(episode)
        )
        computer.run(f"rm -rf {folder} && mkdir -p {folder}/out", timeout=120)
        computer.put([(f"{folder}/{path}", text.encode()) for path, text in files.items()] + media)
        # Each picture was held to the checks when it was posed; the page around them is code's.
        computer.run(
            f"cd {folder} && cp -n {GSAP} gsap.min.js; rm -f render.log render.exit && "
            "(nohup sh -c 'hyperframes render . "
            "--quality looks --fps 30 --output out/episode.mp4 > render.log 2>&1; echo $? > "
            "render.exit' >/dev/null 2>&1 &)",
            timeout=60,
        )
        started = time.time()
        while True:
            time.sleep(3.0)
            seen = computer.run(
                f"cd {folder} && (cat render.exit 2>/dev/null || echo running); "
                "tr '\\r' '\\n' < render.log | grep '@hf-progress' | tail -1",
                timeout=60,
            ).output
            state = seen.split("\n", 1)[0].strip()
            progress = PROGRESS.search(seen)
            if progress is not None:
                with contextlib.suppress(ValueError):
                    fraction = float(json.loads(progress.group(1)).get("pct", 0)) / 100
                    episode = self._episode(episode_id)
                    self.store.update_episode(
                        episode_id, film={**(episode["film"] or {}), "fraction": round(fraction, 2)}
                    )
                    self._changed(episode_id)
            if state != "running":
                break
            if time.time() - started > 3 * 3600:
                raise ValueError("The render took longer than three hours.")
        content = computer.get(f"{folder}/out/episode.mp4") if state == "0" else None
        if not content:
            tail = computer.run(f"tail -5 {folder}/render.log").output
            raise ValueError(f"The render stopped: {_clean(tail[-300:])}")
        slug = (
            re.sub(r"[^a-z0-9]+", "-", str(episode["title"]).lower()).strip("-")[:48] or "episode"
        )
        row = self.host.save_file(
            str(episode["thread_id"]), f"{slug}.mp4", content, origin="delivered"
        )
        episode = self._episode(episode_id)
        self.store.update_episode(
            episode_id,
            film={
                "status": "done",
                "fraction": 1.0,
                "file": row["id"],
                "sig": self._film_sig(episode, full),
                "seconds": clock["total"],
                "failure": "",
                "at": time.time(),
            },
        )
        self.host.file_asset(str(episode["asset_id"]), row)

    # -- what the house shows --------------------------------------------------------------------

    def _say(self, episode: Row, text: str, *, by: str, quiet: bool = False) -> None:
        """What a person did in the studio, in the task's thread, so the thread tells the whole
        story. `quiet` ones are activity, not messages."""
        thread = self.store.thread(str(episode["thread_id"]))
        if thread is None:
            return
        if quiet:
            self.store.add_activity(
                {
                    "thread_id": thread["id"],
                    "kind": "episode",
                    "source": by,
                    "text": text,
                    "at": time.time(),
                }
            )
            return
        message = self.store.add_message(
            channel_id=thread["channel_id"],
            thread_id=thread["id"],
            author_id=by,
            kind="person",
            text=text,
            data={"kind": EPISODE, "episode": episode["id"]},
        )
        self.hub.publish("message.created", message=message)

    def _set(self, episode_id: str, **values: Any) -> None:
        self.store.update_episode(episode_id, **values)
        self._changed(episode_id)

    def _busy(self, episode_id: str) -> bool:
        return (
            self.planning(episode_id)
            or f"film:{episode_id}" in self._jobs
            or any(key[0] == episode_id and not task.done() for key, task in self._builds.items())
        )

    def busy(self, thread_id: str) -> bool:
        """Whether any episode of a thread has its plan, a picture or its film under way."""
        return any(self._busy(str(e["id"])) for e in self.store.episodes(thread_id))

    def _settle(self, episode_id: str) -> None:
        """The asset's status from where the episode stands; the thread's follows from it (a
        plan to approve, stills waiting on a go and a plan that stopped all wait on a person)."""
        episode = self.store.episode(episode_id)
        if episode is None:
            return
        waiting = episode["status"] == "plan" or any(
            p["status"] == "go" for p in self.store.pictures(episode_id)
        )
        if (episode["film"] or {}).get("status") == "done":
            status = "done"
        elif episode["status"] == "failed":
            status = "blocked"
        elif waiting and not self._busy(episode_id):
            status = "review"
        else:
            status = "making"
        if episode["asset_id"]:
            self.host.set_asset(str(episode["asset_id"]), status=status)
        self.host.settle_status(str(episode["thread_id"]))
        self._changed(episode_id)

    def _changed(self, episode_id: str) -> None:
        episode = self.store.episode(episode_id)
        thread = self.store.thread(str(episode["thread_id"])) if episode else None
        if episode is None or thread is None:
            return
        self.hub.publish(
            "episode.updated",
            id=episode_id,
            thread_id=thread["id"],
            channel_id=thread["channel_id"],
            card=self.card(episode),
        )

    def restore(self) -> None:
        """What a restart left half done is stopped, and says so."""
        for record in self.store.working_runs():
            if record["lane"]:
                self.store.update_run(str(record["id"]), state="stopped", ended_at=time.time())
        for episode in self.store.all_episodes():
            episode_id = str(episode["id"])
            if episode["status"] == "planning" or (episode["stage"] or {}).get("state") in (
                "working",
                "reading",
            ):
                self.store.update_episode(
                    episode_id,
                    status="failed" if not episode["approved"] else episode["status"],
                    stage={
                        **(episode["stage"] or {}),
                        "state": "stopped",
                        "said": "Stopped when the house restarted.",
                    },
                )
            for have in self.store.pictures(episode_id):
                if have["status"] in ("queued", "making", "posing"):
                    self.store.set_picture(
                        episode_id,
                        have["unit"],
                        status="failed",
                        failure="Stopped when the house restarted.",
                    )
            if (episode["film"] or {}).get("status") == "rendering":
                self.store.update_episode(
                    episode_id,
                    film={
                        **episode["film"],
                        "status": "failed",
                        "failure": "Stopped when the house restarted.",
                    },
                )

    async def close(self) -> None:
        self._closing = True
        tasks = [*self._jobs.values(), *self._builds.values()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def card(self, episode: Row) -> dict[str, Any]:
        """An episode as its card on the canvas shows it: a line, not the plan."""
        stage = episode["stage"] or {}
        film_state = episode["film"] or {}
        pictures = self.store.pictures(str(episode["id"]))
        takes = {
            t["chapter"]
            for t in self.store.takes(str(episode["id"]))
            if t["kept"] and not t["frame"]
        }
        chapters = len((episode["plan"] or {}).get("chapters", []))
        return {
            "id": episode["id"],
            "thread_id": episode["thread_id"],
            "asset_id": episode["asset_id"],
            "title": episode["title"],
            "status": episode["status"],
            "approved": episode["approved"],
            "stage": {k: stage.get(k) for k in ("name", "state", "said", "round")},
            "writer": episode["settings"].get("writer"),
            "chapters": chapters,
            "recorded": len(takes),
            "pictures": {
                "made": sum(1 for p in pictures if p["status"] == "made"),
                "go": sum(1 for p in pictures if p["status"] == "go"),
                "making": sum(1 for p in pictures if p["status"] in ("queued", "making", "posing")),
                "failed": sum(1 for p in pictures if p["status"] == "failed"),
            },
            "film": {k: film_state.get(k) for k in ("status", "fraction", "failure")},
        }

    def cards(self, thread_id: str) -> list[dict[str, Any]]:
        return [self.card(e) for e in self.store.episodes(thread_id)]

    def view(self, episode_id: str) -> dict[str, Any]:
        """Everything the studio draws."""
        episode = self._episode(episode_id)
        thread = self.store.thread(str(episode["thread_id"]))
        full = self._full(episode)
        found = self._units(episode, full) if full is not None else []
        pictures = {p["unit"]: p for p in self.store.pictures(episode_id)}
        clock = (
            timeline.schedule(full, self._kept(episode_id), self._voice(episode))
            if full is not None
            else None
        )
        film_state = {k: v for k, v in (episode["film"] or {}).items() if k != "voice"}
        if full is not None and film_state.get("status") == "done":
            film_state["stale"] = film_state.get("sig") != self._film_sig(episode, full)
        film_state["file"] = self._file(film_state.get("file"))
        report = episode["report"] or {}
        runs = [
            {
                "id": r["id"],
                "lane": r["lane"],
                "harness": r["harness"],
                "state": r["state"],
                "asked": _clean(str(r["prompt"]), 160),
                "said": _clean(str(r["answer"] or r["failure"]), 400),
                "steps": len(r["steps"]),
                "started_at": r["started_at"],
                "ended_at": r["ended_at"],
            }
            for r in self.store.runs(str(episode["thread_id"]))
            if r["lane"]
        ]
        return {
            **self.card(episode),
            "channel_id": thread["channel_id"] if thread else "",
            "settings": episode["settings"],
            "steps": [{"id": key, "label": label} for key, label in STEPS],
            "plan": full,
            "written": {
                "material": len((episode["plan"] or {}).get("material", [])),
                "idea": (episode["plan"] or {}).get("brief", {}).get("idea", ""),
                "chapters": [
                    {
                        "id": c.get("id"),
                        "question": c.get("question", ""),
                        "beats": len(c.get("beats", [])),
                    }
                    for c in (episode["plan"] or {}).get("chapters", [])
                ],
            },
            "clock": clock,
            "units": [
                {
                    **unit,
                    "picture": self._picture_view(pictures.get(unit["id"]), unit),
                    "kind_of_picture": unit["picture"],
                }
                for unit in found
            ],
            "takes": [self._take_view(t) for t in self.store.takes(episode_id)],
            "film_state": film_state,
            "checks": [r for r in report.get("rows", []) if r.get("level") in ("must", "look")],
            "runs": runs[-40:],
            "options": self.options(),
        }

    def _file(self, file_id: Any) -> dict[str, Any] | None:
        row = self.store.file(str(file_id)) if file_id else None
        return self.host.file_view(row) if row is not None else None

    def _picture_view(self, have: Row | None, unit: Row) -> dict[str, Any]:
        if have is None:
            return {
                "status": "none",
                "stills": {},
                "clip": None,
                "stale": False,
                "failure": "",
                "note": "",
            }
        return {
            "status": have["status"],
            "stills": {
                frame: view
                for frame, file_id in (have["stills"] or {}).items()
                if (view := self._file(file_id)) is not None
            },
            "clip": self._file(have["clip"]),
            "stale": have["sig"] != unit["sig"],
            "failure": have["failure"],
            "note": have["note"],
        }

    def _take_view(self, take: Row) -> dict[str, Any]:
        return {
            "id": take["id"],
            "chapter": take["chapter"],
            "frame": take["frame"],
            "n": take["n"],
            "seconds": take["seconds"],
            "marks": take["marks"],
            "kept": take["kept"],
            "video": self._file(take["video"]),
            "audio": self._file(take["audio"]),
            "created_at": take["created_at"],
        }


def _findings(report: str) -> tuple[list[str], list[str]]:
    """What the renderer's check found in a picture: what breaks it, and what it flags about
    how it looks, each as one line the builder can act on."""
    section = BREAKING[0]
    broken: list[str] = []
    flagged: list[str] = []
    for raw in report.splitlines():
        line = raw.strip()
        if line in CHECK_SECTIONS:
            section = line
            continue
        found = LINT_ERROR.match(line)
        into = broken if section in BREAKING else flagged
        if found is not None:
            into.append(f"{section.lower()}: {found.group(1).strip()[:300]}")
        elif line.startswith(("Try ", "Fix: ")) and into:
            into[-1] += f" ({line[:160]})"
    return broken[:12], flagged[:12]


def _dark(colour: str) -> bool:
    """Whether white reads on a colour better than ink does."""
    value = colour.lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    try:
        red, green, blue = (int(value[i : i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return True
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue < 0.55


def _first_option(state: Any, questions: Row) -> Row:  # noqa: ARG001 - a reader's signature
    """The demo's reader: its plan arrives labelled, so the little that is still asked (the
    hook, the landing) takes the first option."""
    out: Row = {}
    for key, question in questions.items():
        if question.get("type") == "noul":
            out[key] = {"noul": 1.0}
        else:
            first = next(iter(question.get("criteria") or {"none": ""}))
            out[key] = {"choice": first, "confidence": 1.0, "probabilities": {first: 1.0}}
    return out


def _shape(plan: Any, stage: str) -> list[str]:
    """What is wrong with a plan's shape, before any of it is read."""
    if not isinstance(plan, dict):
        return ["plan.json must hold one JSON object."]
    out: list[str] = []
    if not isinstance(plan.get("brief"), dict):
        out.append("`brief` must be an object.")
    material = plan.get("material")
    if not isinstance(material, list) or not all(
        isinstance(m, dict) and m.get("id") and m.get("text") for m in material
    ):
        out.append("`material` must be a list of {id, text}.")
    if stage == "brief":
        return out
    chapters = plan.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        return [*out, "`chapters` must be a list with at least one chapter."]
    seen: set[str] = set()
    for ch in chapters:
        if not isinstance(ch, dict) or not ch.get("id") or not isinstance(ch.get("beats"), list):
            out.append("every chapter needs an `id`, a `question` and a list of `beats`.")
            continue
        for b in ch["beats"]:
            if not isinstance(b, dict) or not b.get("id") or not str(b.get("says") or "").strip():
                out.append(f"every beat of {ch['id']} needs an `id` and `says`.")
                continue
            ids = [str(b["id"])]
            frames = b.get("frames") or []
            if not isinstance(frames, list) or not all(isinstance(f, dict) for f in frames):
                out.append(f"{b['id']}: `frames` must be a list of objects.")
                continue
            ids += [str(f.get("id") or f"{b['id']}.f{i + 1}") for i, f in enumerate(frames)]
            for one in ids:
                if one in seen:
                    out.append(f"the id {one} is used twice.")
                seen.add(one)
            if len(frames) > 1 and not all(str(f.get("vo") or "").strip() for f in frames):
                out.append(f"{b['id']} has more than one frame: each needs its `vo`.")
    return list(dict.fromkeys(out))[:20]
