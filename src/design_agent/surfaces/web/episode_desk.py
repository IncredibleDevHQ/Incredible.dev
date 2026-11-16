"""An episode on the canvas: a planned explainer, taken from notes to a rendered film.

An episode is a piece of work in a task, like any asset, with a studio of its own. A person
starts one from material (their words and files, or a research frame's notes), picks who
writes it (a coding agent on this computer or the built-in agent), and then:

- **the plan** is written in stages by that agent, each stage read by a classifier and checked
  by code before the next (`design_agent.episode`); the person approves it once;
- **each chapter** is worked in one place: who has the frame for every line, the layout, and
  whether a picture is made at once (simple) or posed as stills for the person's go (rich).
  The pictures are built meanwhile, by the same agent, and posed on the thread's computer;
- **a take** per chapter is recorded in the browser (or brought as a file, a camera's own
  included) and cut to the film's format; where a line was started in the take sets when its
  picture's cues land;
- **the narrator** says the lines no take covers, when the person chooses one: in a voice of
  the ElevenLabs account, or in a clone of the person's own made from their takes;
- **the film** is one HyperFrames project written by code (`episode.film`) and rendered on the
  thread's computer.

A person's picks are never undone by a later stage: they are kept beside the plan and applied
every time it is read. The film is a file on the canvas and is sent nowhere. Two things leave
this computer, both for ElevenLabs and both only on a person's say: a narrated line's words
when the film is rendered, and recordings of their voice when they ask for a clone of it.
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import json
import logging
import re
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any

from design_agent.episode import (
    check,
    classifier,
    classify,
    derive,
    film,
    geometry,
    layouts,
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
    from design_agent.tools.media import Voice

_LOGGER = logging.getLogger(__name__)

#: An episode's own task thread, and its asset on the canvas.
EPISODE = "episode"
#: Fix rounds a stage gets before the plan goes on with what the checks still flag.
ROUNDS = 3
#: Turns on a plan that already stands: a pick that leaves the writer something to redo, a
#: change a person asks for in words, a line whose words a person changed. One that fails or
#: is stopped leaves the plan as it was.
STANDING = ("redo", "change", "edit")
#: How many of the lines a change cut are kept, with their words, to be shown.
CUT_SHOWN = 24
#: What a note on a picture asks to change, as the reader is asked. The first is the builder's
#: to make; the second is the writer's, because the plan says what a picture shows.
NOTE_ASK = (
    "A person looks at one picture of an explainer video and asks for a change to it. NOTE is "
    "what they wrote. Is the change about how the picture is drawn, or about what it shows?"
)
NOTE_KINDS = {
    "drawn": "How it is drawn: size, position, spacing, colour, type, something that overlaps, "
    "is cut off or is hard to read, how it moves or how fast. The same things stay in it.",
    "shows": "What it shows: other things in the picture, other words on it, another example, "
    "more or fewer items, another order, another kind of picture.",
}
#: Tries a picture gets before it is left for the person to send back.
PICTURE_TRIES = 3
#: Pictures built at once by a local agent. The built-in agent builds one at a time: its
#: thread holds one turn.
PICTURES_AT_ONCE = 2
MATERIAL_CHARS = 200_000
TEXT_FILES = (".md", ".markdown", ".txt", ".rst", ".json", ".csv", ".html", ".htm")
#: The lengths a person can ask for, in seconds: the limits (the lengths this kind of film
#: runs), the range the sheet opens on, and how far apart the least and the most stay, so a
#: script has room to land between them.
SECONDS = (int(Q.TYPES["numbers"]["seconds"][0]), int(Q.TYPES["numbers"]["seconds"][1]))
USUAL = (300, 420)
GAP = 30
#: Said for the length when a person leaves it to the material.
AUTO = "auto"
THEMES = Q.table("themes")
LEVELS = units.LEVELS
VOICES = ("live", "narrator")
#: A clone of a person's voice is made from their takes: this much speech at least, and no
#: more than a clone uses. A take over the size ElevenLabs takes for one recording is left out.
CLONE_LEAST = 30.0
CLONE_ENOUGH = 180.0
CLONE_TAKE_BYTES = 10 * 1024 * 1024
#: How long the account's list of voices is believed before it is read again.
VOICES_KEPT = 60.0
#: Every take's sound is set to one loudness (EBU R 128, in LUFS), so chapters recorded on
#: different days, a camera's own file and a narrator's lines sit at one level, and its peaks
#: are held short of full scale (dBFS). Below `SILENT` there is no voice to bring up.
LOUDNESS = -16.0
PEAK = -1.5
SILENT = -50.0
MOST_GAIN = 24.0
#: A picture coded for a brighter screen than the film's (an iPhone's, by default), as ffprobe
#: names its transfer, and the filters that bring it down to the film's range.
HDR = ("arib-std-b67", "smpte2084")
TONEMAP = (
    "zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,"
    "zscale=t=bt709:m=bt709:r=tv,format=yuv420p"
)
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


def _length(asked: Any) -> list[int] | str:
    """The length a person asked for: the least and the most seconds, inside the limits and at
    least `GAP` apart, or `AUTO` when they leave it to the material."""
    if asked == AUTO:
        return AUTO
    least, most = sorted(int(s) for s in asked)
    least = min(max(least, SECONDS[0]), SECONDS[1] - GAP)
    return [least, min(max(most, least + GAP), SECONDS[1])]


def _clean(text: str, limit: int = 300) -> str:
    return " ".join(str(text).split())[:limit]


def _ending(name: str) -> str:
    """A recording's kind, from its file's name. The name is the person's file's, so only its
    letters and digits are kept: it becomes part of a command and of an address in a bucket."""
    return re.sub(r"[^a-z0-9]", "", Path(name).suffix.lower())[:5] or "webm"


def _levelled(measured: str) -> str:
    """The ffmpeg filters that set a take's sound to the film's loudness, from ffmpeg's own
    loudness summary of it: one gain for the whole take, and its peaks held only where that
    gain would push them past the ceiling. Empty when the sound is already there, when it is
    silence, or when the summary can't be read: then the take keeps the sound it has."""
    loud = re.search(r"\bI:\s+(-?\d+(?:\.\d+)?) LUFS", measured)
    if loud is None or float(loud[1]) <= SILENT:
        return ""
    gain = max(-MOST_GAIN, min(MOST_GAIN, LOUDNESS - float(loud[1])))
    gain = 0.0 if abs(gain) < 0.5 else round(gain, 1)
    peak = re.search(r"\bPeak:\s+(-?\d+(?:\.\d+)?) dBFS", measured)
    held = peak is None or float(peak[1]) + gain > PEAK
    filters = [f"volume={gain}dB"] if gain else []
    if held:
        filters.append(f"alimiter=limit={10 ** (PEAK / 20):.3f}:level=false:latency=true")
    return ",".join(filters)


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
        #: The ElevenLabs account's voices as last listed, and when (a monotonic time).
        self._listed: tuple[float, list[Voice]] | None = None

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
                {
                    "id": t["id"],
                    "name": t["name"],
                    "presenter": t["presenter"],
                    "stage": t["stage"],
                    # its layouts, and who has the frame in each: one picker for both
                    "kit": [
                        {"layout": lay, "presence": layouts.LAY[lay]["presence"]}
                        for lay in t["kit"]
                    ],
                }
                for t in Q.TYPES["themes"]
            ],
            "seconds": {"least": SECONDS[0], "most": SECONDS[1], "usual": list(USUAL), "gap": GAP},
            "reader": "demo" if self.demo else "jev" if self._jev_key() else "writer",
            # a narrator can speak (ElevenLabs has a key), and the house has a voice of its
            # own for one; without that, an episode picks a voice or clones the person's
            "narrator": {
                "ready": self._speaks(),
                "usual": bool(self.host.settings.narrator_voice_id),
            },
            "geometry": geometry.view(),
            # what a person may pick for the line that brings a picture in
            "pictures": list(override.PICTURES),
            "transitions": list(override.TRANSITIONS),
        }

    def _jev_key(self) -> str:
        key = self.host.settings.typesafe_api_key
        return key.get_secret_value() if key is not None else ""

    def _speaks(self) -> bool:
        """Whether a narrator can speak at all: ElevenLabs has a key here."""
        return bool(self.host.settings.elevenlabs_api_key)

    def _voice_id(self, episode: Row) -> str:
        """The voice that narrates an episode: the one picked for it, else the house's own."""
        picked = episode["settings"].get("narrator") or {}
        return str(picked.get("id") or self.host.settings.narrator_voice_id or "")

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
            base or {"seconds": list(USUAL), "presenter": "on", "voice": "live", "level": "simple"}
        )
        if "seconds" in given:
            out["seconds"] = _length(given["seconds"])
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
        if given.get("narrator"):
            from design_agent.tools.media import VOICE_ID

            picked = given["narrator"]
            if not VOICE_ID.fullmatch(str(picked.get("id") or "")):
                raise ValueError("That isn't an ElevenLabs voice.")
            out["narrator"] = {
                "id": str(picked["id"]),
                "name": _clean(str(picked.get("name") or ""), 80) or "A voice",
            }
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
        if isinstance(chosen.get("seconds"), list):
            brief["seconds"] = chosen["seconds"]
        else:
            # left to the material: the brief states no length, so none is checked
            brief.pop("seconds", None)
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

    def _start_plan(
        self,
        episode_id: str,
        *,
        stage: str = "brief",
        redo: str = "",
        picture: str = "",
        asked: Row | None = None,
    ) -> None:
        running = self._jobs.get(episode_id)
        if running is not None and not running.done():
            raise ValueError("It's still being written. Wait for it, or stop it first.")
        # said at once, so what a person is shown next already knows a turn is under way
        self.store.update_episode(
            episode_id,
            stage={
                **(self._episode(episode_id)["stage"] or {}),
                "name": stage,
                "round": 0,
                "state": "working",
                "said": "Getting ready",
                "at": time.time(),
                # a person's own words for the change, so they can be read back and sent again
                "asked": asked,
            },
        )
        self._jobs[episode_id] = asyncio.get_running_loop().create_task(
            self._planned(episode_id, stage, redo, picture), name=f"episode plan {episode_id}"
        )

    def planning(self, episode_id: str) -> bool:
        job = self._jobs.get(episode_id)
        return job is not None and not job.done()

    async def _planned(self, episode_id: str, stage: str, redo: str, picture: str = "") -> None:
        try:
            await self._plan(episode_id, stage, redo, picture)
        except asyncio.CancelledError:
            if stage in STANDING:
                self._as_it_was(episode_id, stage, "Stopped.")
            else:
                self._stage(episode_id, state="stopped", said="Stopped.")
                self._set(episode_id, status="failed")
        except Exception as error:  # a writer that misbehaves must not take the house down
            _LOGGER.exception("episode plan failed on %s", episode_id)
            why = _clean(str(error), 200).rstrip(".")
            if stage in STANDING:
                self._as_it_was(episode_id, stage, f"It stopped: {why}.")
            else:
                self._stage(episode_id, state="failed", said=f"It stopped: {why}")
                self._set(episode_id, status="failed")
        finally:
            self._jobs.pop(episode_id, None)
            self._settle(episode_id)

    def _as_it_was(self, episode_id: str, stage: str, said: str) -> None:
        """A turn on a standing plan did not finish: the plan goes back to how it stood, and
        the studio stays open. A person's own words stay; only their picture's steps wait."""
        episode = self._episode(episode_id)
        if stage == "edit":
            said += " Your words are in; the steps of their picture were not fitted to them."
        else:
            kept = self.store.snapshot(episode_id)
            if kept is not None and kept["data"].get("plan") and not kept["summary"]:
                self.store.update_episode(
                    episode_id, plan=kept["data"]["plan"], labels=kept["data"]["labels"]
                )
                self.store.drop_snapshot(kept["n"])
            said += " The plan is as it was."
        self._stage(episode_id, name=stage, state="stopped", said=said)
        self._set(episode_id, status="studio" if episode["approved"] else "plan")

    def _as_it_stands(self, episode: Row) -> Row:
        """The plan, its labels and its pictures as they stand: what a change can go back to."""
        keep = ("unit", "sig", "status", "html", "stills", "clip", "go_sig", "note", "failure")
        return {
            "plan": episode["plan"],
            "labels": episode["labels"],
            "pictures": [{k: p[k] for k in keep} for p in self.store.pictures(str(episode["id"]))],
        }

    def _snapshot(
        self, episode_id: str, why: str, episode: Row | None = None, picked: Row | None = None
    ) -> None:
        """A change begins: the episode as it stands is kept, so the change can be taken back.
        `picked` is the pick that began it, when it was one: it goes back with the change."""
        data = self._as_it_stands(episode or self._episode(episode_id))
        if picked:
            data["picked"] = picked
        self.store.put_snapshot(episode_id, why=why, data=data)

    def _note_change(self, episode_id: str) -> bool:
        """What the change did, beside the snapshot it can be taken back to. A turn that left
        the plan and the person's picks exactly as they were is no change: nothing is kept."""
        kept = self.store.snapshot(episode_id)
        if kept is None:
            return False
        episode = self._episode(episode_id)
        picks = ((kept["data"].get("labels") or {}).get("overrides") or {}) == (
            (episode["labels"] or {}).get("overrides") or {}
        )
        same = picks and kept["data"].get("plan") == episode["plan"]
        if same and not kept["summary"]:
            self.store.drop_snapshot(kept["n"])
            return False
        self.store.note_snapshot(
            kept["n"], _changed(kept["data"].get("plan") or {}, episode["plan"] or {})
        )
        return True

    def _go_to(self, episode_id: str, kept: Row) -> None:
        """The episode goes to how `kept` has it. The picks a person made since stay (see
        `picks_kept`), and so does a picture made since that still fits its lines."""
        episode = self._episode(episode_id)
        then, labels = kept["data"]["plan"], dict(kept["data"]["labels"] or {})
        picks = plans.picks_kept(
            labels.get("overrides") or {},
            (episode["labels"] or {}).get("overrides") or {},
            plans.merged(then, {}),
            plans.merged(episode["plan"] or {}, {}),
            kept["data"].get("picked"),
        )
        if picks != (labels.get("overrides") or {}):
            labels = self._with_picks(episode, then, labels, picks)
        self.store.update_episode(episode_id, plan=then, labels=labels)
        episode = self._episode(episode_id)
        full = self._full(episode)
        fits = {u["id"]: u for u in self._units(episode, full)} if full is not None else {}
        for row in kept["data"].get("pictures", []):
            unit = fits.get(str(row["unit"]))
            have = self.store.picture(episode_id, str(row["unit"]))
            if (
                unit is not None
                and have is not None
                and units.same(str(have["sig"]), unit)
                and not units.same(str(row["sig"]), unit)
            ):
                continue  # the one made since is the one these lines now ask for
            values = {k: v for k, v in row.items() if k != "unit"}
            if values.get("status") in ("queued", "making", "posing"):
                values["sig"] = ""  # it was on its way then: it is asked for again
            self.store.set_picture(episode_id, str(row["unit"]), **values)

    def _with_picks(self, episode: Row, plan: Row, labels: Row, picks: Row) -> Row:
        """A plan's labels, as they were kept, with a person's picks as they stand now laid
        over them. A pick the plan cannot carry without the writer (its line would need a
        picture planned) stays as it was kept; if that is not enough, they all do."""
        kept = labels.get("overrides") or {}
        for last in (False, True):
            merged = self._merged(
                {**episode, "plan": plan, "labels": {**labels, "overrides": picks}}
            )
            left = override.redo(override.apply(merged, {}))
            if not left:
                return plans.labels_of(merged)
            if last:
                break
            picks = copy.deepcopy(picks)
            frames = picks.setdefault("frames", {})
            for item in left:
                was = kept.get("frames", {}).get(item["where"])
                if was:
                    frames[item["where"]] = was
                else:
                    frames.pop(item["where"], None)
        return labels

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

    async def _plan(self, episode_id: str, start: str, redo: str, picture: str = "") -> None:
        episode = self._episode(episode_id)
        worker = self._worker(episode)
        standing = start in STANDING
        if not standing:
            # a plan being written takes the studio's place; a change to one that stands does not
            status = "planning" if not episode["approved"] else episode["status"]
            self._set(episode_id, status=status)
        self._stage(
            episode_id, name=start, round=0, state="working", said="Getting ready", at=time.time()
        )
        if picture:
            # a note on a picture: how it is drawn is its builder's, what it shows the writer's
            unit = next(
                (u for u in self._units(episode, self._full(episode) or {}) if u["id"] == picture),
                None,
            )
            if unit is None:
                raise RuntimeError("that picture is no longer in the plan")
            self._stage(episode_id, said="Reading your note")
            if await asyncio.to_thread(self._note_kind, worker, unit, redo) == "drawn":
                self._stage(episode_id, name="done", state="done", said="")
                self._rebuild(episode_id, picture, redo)
                return
            redo = (
                f"About the picture line {picture} brings in (it shows: "
                f"“{_clean(str(unit.get('shows') or ''), 240)}”), the person asks: “{redo}”"
            )
        newest = self.store.snapshot_note(episode_id)
        if start in ("redo", "change") and (newest is None or newest["summary"]):
            # a pick that needed this turn kept the episode as it stood before the pick
            asked = (self._episode(episode_id)["stage"] or {}).get("asked") or {}
            self._snapshot(episode_id, why=str(asked.get("text") or redo))
        # the house's plan is the plan: what a person changed in it reaches the writer's folder
        plan_text = (
            json.dumps(episode["plan"], ensure_ascii=False, indent=1) if episode["plan"] else "{}"
        )
        files = {"material/notes.md": str(episode["material"]), "plan.json": plan_text + "\n"}
        await worker.prepare(episode, files)
        order = ["brief", "script", "frames"]
        todo = [start] if standing else order[order.index(start) :]
        report: list[str] = []
        for name in todo:
            episode = self._episode(episode_id)
            if name == "frames":
                # who has the frame is read from the script before anything is designed
                report = await self._read(episode_id, worker, ["frames"], checks="")
            # a person's own words need no turn of the writer's, unless their picture's steps
            # no longer land on them
            prompt = "" if name == "edit" else self._prompt(episode, worker, name, report, redo)
            for round_number in range(ROUNDS + 1):
                self._stage(episode_id, name=name, round=round_number, state="working")
                problems: list[str] = []
                if prompt:
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
                        "change": (["script", "frames", "design"], "all"),
                        "edit": (["frames", "design"], "all"),
                    }[name]
                    report = await self._read(episode_id, worker, stages, checks=checks)
                    problems = self._blocking(episode_id, name, redo if name == "edit" else "")
                if not problems or round_number == ROUNDS:
                    break
                prompt = self._fix_prompt(
                    self._episode(episode_id), worker, name, report, redo if name == "edit" else ""
                )
        episode = self._episode(episode_id)
        full = self._full(episode)
        if full is None:
            raise RuntimeError("the plan has no frames yet")
        self._stage(episode_id, name="done", state="done", said="")
        if standing and not self._note_change(episode_id) and start == "change":
            # said plainly, or a person who asked is left looking for what is different
            self._stage(episode_id, said="The writer changed nothing.")
        status = "studio" if episode["approved"] else "plan"
        self._set(episode_id, status=status)
        if episode["approved"]:
            self._queue_pictures(episode_id)

    def _note_kind(self, worker: Worker, unit: Row, note: str) -> str:
        """Whether a note on a picture is about how it is drawn or about what it shows. A
        reader that cannot say leaves it with the builder, which is where notes went before."""
        try:
            answers = self._reader(worker)(
                {"picture_shows": unit.get("shows") or "", "NOTE": note},
                {"note": Q.choice(NOTE_ASK, NOTE_KINDS)},
            )
        except Exception:  # a reader that fails must not lose the person's note
            _LOGGER.exception("a picture note could not be read")
            return "drawn"
        picked = str((answers.get("note") or {}).get("choice") or "drawn")
        return picked if picked in NOTE_KINDS else "drawn"

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
            before = self._episode(episode_id)
            self.store.update_episode(episode_id, plan=plan)
            if stage in STANDING and plan == before["plan"]:
                return problems  # written as it was: its labels stand, and nothing is read again
            if stage == "change" and not isinstance(worker, DemoWorker):
                # a change keeps who has the frame for every line it did not redesign: said
                # another way, a line is still the person's or the picture's, and no picture
                # is drawn again because a reading moved
                self.store.update_episode(
                    episode_id,
                    labels=plans.carried(
                        before["labels"] or {}, before["plan"] or {}, plan, frames_only=True
                    ),
                )
            if isinstance(worker, DemoWorker):
                # the demo's plan comes with the labels it was read with; a change to it keeps
                # them, as the demo has no reader to read the new words
                labels = (
                    plans.carried(before["labels"] or {}, before["plan"] or {}, plan)
                    if stage in STANDING
                    else worker.script.get("labels") or {}
                )
                self.store.update_episode(episode_id, labels=labels)
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

    def _blocking(self, episode_id: str, stage: str, about: str = "") -> list[str]:
        """What still stops this stage from being done: the checks' musts, a line that needs a
        picture and has none, a brief with nothing in it. With `about` (a line a person
        reworded), only what that line breaks: the rest of the plan stood before."""
        episode = self._episode(episode_id)
        merged = self._merged(episode)
        musts = check.musts(episode["report"].get("rows", []))
        if about:
            return [f"{r['where']}: {r['text']}" for r in musts if r["where"] == about]
        out = [f"{r['where']}: {r['text']}" for r in musts]
        if stage == "brief":
            brief = merged.get("brief", {})
            out += [f"the brief has no `{k}`" for k in ("idea", "gap", "for") if not brief.get(k)]
            if len(merged.get("material", [])) < 3:
                out.append("cut the material into at least three items")
        if stage in ("frames", "redo", "change"):
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
            asked = chosen.get("seconds")
            length = (
                f"a length between {asked[0]} and {asked[1]} seconds (`seconds`: {asked})"
                if isinstance(asked, list)
                else "no length (leave `seconds` out of the brief: the material decides it)"
            )
            return (
                f"Stage: brief.\n\nYour folder is {root}. The skill is {skill}/SKILL.md: read it "
                f'first, then {skill}/references/script.md ("The brief"). The material is '
                f"{root}/material/notes.md.\n\nThe person chose: {length}, "
                f"presenter {presenter}, theme `{chosen.get('theme')}`, working title "
                f"“{episode['title']}”. Put these in the brief as given.\n\nWrite "
                f"{root}/plan.json with `material` and `brief` only. Deliver nothing: the house "
                "reads plan.json from your folder. Reply with the idea in one sentence and what "
                "the material lacks."
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
        if stage == "change":
            return (
                "Stage: change.\n\nA person asks for a change to the plan:\n\n"
                f"{redo}\n\nMake that change in {root}/plan.json and nothing else, following "
                f'{skill}/references/plan.md ("When a person asks for a change"). Keep the id '
                "of every line that stays, and give a new line a new id. A line marked "
                "`by_person` keeps its words unless the change is about that line. Never undo "
                "a pick. Reply with what you changed, one line each."
            )
        return (
            "Stage: redo.\n\nA person changed who has the frame. What that leaves for you:\n\n"
            f"{redo}\n\nDo only that, in {root}/plan.json, following {skill}/references/plan.md "
            '("When a person changes who has the frame"). Never undo a pick. Reply with what '
            "you changed."
        )

    def _fix_prompt(
        self, episode: Row, worker: Worker, stage: str, report: Sequence[str], about: str = ""
    ) -> str:
        root, _ = worker.place(episode)
        said = "\n".join(report)
        if about:
            return (
                f"Stage: fix.\n\nA person changed the words of {about} (it is marked "
                f"`by_person`). Their words stay exactly as they are. The plan was checked with "
                f"them:\n\n{said}\n\nFix what {about} breaks in {root}/plan.json by fitting "
                "its cues to the new words (the word each lands on, or the cue itself), and "
                "change nothing else. Reply with what you changed."
            )
        return (
            f"Stage: fix (the {stage} stage).\n\nYour plan was read and checked:\n\n{said}\n\n"
            f"Fix every MUST, and each look you do not waive, in {root}/plan.json. Change "
            "nothing else. Reply with what you changed."
        )

    def stop(self, episode_id: str) -> None:
        """Stop what is under way for an episode: its plan, and every picture being made or
        waiting its turn. A stopped picture stays stopped until a person asks for it again."""
        job = self._jobs.get(episode_id)
        if job is not None and not job.done():
            job.cancel()
        for (owner, _), build in list(self._builds.items()):
            if owner == episode_id and not build.done():
                build.cancel()

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
        override.refuse(new)
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
            # as it stood before the pick, so a turn that stops takes the pick back with it
            self._snapshot(episode_id, why="Changed who has the frame", episode=episode, picked=new)
            self._start_plan(episode_id, stage="redo", redo=told)
        elif self._episode(episode_id)["approved"]:
            self._queue_pictures(episode_id)
        self._say(episode, "Changed the episode's choices.", by=by, quiet=True)
        self._settle(episode_id)
        return self.view(episode_id)

    def ask(self, episode_id: str, *, by: str, scope: str, target: str = "", text: str) -> Row:
        """A person asks for a change in words: to the film, a chapter, a line or a picture.
        The writer makes it (a note on how a picture is drawn goes to its builder instead),
        and the plan as it stood is kept so the change can be taken back."""
        note = _clean(text, 600)
        if not note:
            raise ValueError("Say what should change.")
        episode = self._episode(episode_id)
        full = self._full(episode)
        if full is None or self.planning(episode_id):
            raise ValueError("The writer is still working. Ask when that has landed.")
        picture = ""
        if scope == "film":
            told = f"About the whole film, the person asks: “{note}”"
        elif scope == "chapter":
            chapter = next((c for c in full["chapters"] if c["id"] == target), None)
            if chapter is None:
                raise ValueError("That chapter is not in the plan.")
            asks = _clean(str(chapter.get("question") or ""), 160)
            told = f"About chapter {target} (“{asks}”), the person asks: “{note}”"
        elif scope == "line":
            line = next((f for _, _, f in plans.frames_of(full) if f["id"] == target), None)
            if line is None:
                raise ValueError("That line is not in the plan.")
            said = _clean(str(line.get("vo") or ""), 200)
            told = f"About line {target} (“{said}”), the person asks: “{note}”"
        elif scope == "picture":
            unit = next(
                (
                    u
                    for u in self._units(episode, full)
                    if target in u["frames"] and u["kind"] == "picture"
                ),
                None,
            )
            if unit is None:
                raise ValueError("That line has no picture yet.")
            running = self._builds.get((episode_id, unit["id"]))
            if running is not None and not running.done():
                raise ValueError("It's being built. Send the note when it has landed.")
            picture, told = str(unit["id"]), note
        else:
            raise ValueError("A change is asked of the film, a chapter, a line or a picture.")
        self._start_plan(
            episode_id,
            stage="change",
            redo=told,
            picture=picture,
            asked={"scope": scope, "target": target, "text": note},
        )
        self._say(episode, f"Asked for a change: {note}", by=by, quiet=True)
        self._settle(episode_id)
        return self.view(episode_id)

    def edit(self, episode_id: str, *, by: str, frame: str, text: str) -> Row:
        """A person's own words for one line. They are in at once: nothing is read again and
        nothing is drawn again. Only when a step of the line's picture landed on a word that
        is gone does the writer fit that step to the new words."""
        words = " ".join(str(text).split())
        if not words:
            raise ValueError("A line needs words. To drop it, ask for it to be cut.")
        if len(words) > 700:
            raise ValueError("That is long for one line. Ask for the chapter to be changed.")
        episode = self._episode(episode_id)
        if self._full(episode) is None or self.planning(episode_id):
            raise ValueError("The writer is still working. Change the words when that has landed.")
        before = episode["plan"] or {}
        after = copy.deepcopy(before)
        try:
            old = plans.reword(after, frame, words, at=time.time())
        except KeyError:
            raise ValueError("That line is not in the plan.") from None
        if old == words:
            return self.view(episode_id)
        self._snapshot(episode_id, why="You changed a line", episode=episode)
        self.store.update_episode(
            episode_id, plan=after, labels=plans.carried(episode["labels"] or {}, before, after)
        )
        self._note_change(episode_id)
        merged = self._merged(self._episode(episode_id))
        rows = check.check(merged, "all")
        self.store.update_episode(
            episode_id,
            report={"rows": rows, "lines": check.lines(rows, "all", merged), "at": time.time()},
        )
        self._say(episode, "Changed a line's words.", by=by, quiet=True)
        if any(r["where"] == frame for r in check.musts(rows)) and not self.demo:
            self._start_plan(episode_id, stage="edit", redo=frame)
        elif episode["approved"]:
            self._queue_pictures(episode_id)
        self._settle(episode_id)
        return self.view(episode_id)

    def undo(self, episode_id: str, *, by: str) -> Row:
        """Take the last change back: the plan and its pictures as they stood before it. The
        change before it is then the next to go, and this one can be put back."""
        kept = self.store.snapshot(episode_id)
        if kept is None or not kept["data"].get("plan") or not kept["summary"]:
            raise ValueError("There is nothing to take back.")
        return self._turn(episode_id, kept, by=by, back=True)

    def redo(self, episode_id: str, *, by: str) -> Row:
        """Put back the change that was last taken back. It can be until the next change."""
        kept = self.store.snapshot(episode_id, "undone")
        if kept is None or not kept["data"].get("plan"):
            raise ValueError("There is nothing to put back.")
        return self._turn(episode_id, kept, by=by, back=False)

    def _turn(self, episode_id: str, kept: Row, *, by: str, back: bool) -> Row:
        """A change is taken back, or put back: the episode goes to the other side of it, and
        the side it leaves is kept in its place."""
        episode = self._episode(episode_id)
        if self.planning(episode_id):
            raise ValueError("The writer is still working. Stop it, or wait for it.")
        for (owner, _), build in list(self._builds.items()):
            if owner == episode_id and not build.done():
                build.cancel()
        left = self._as_it_stands(episode)
        if kept["data"].get("picked"):
            left["picked"] = kept["data"]["picked"]
        self._go_to(episode_id, kept)
        self.store.turn_snapshot(kept["n"], kind="undone" if back else "before", data=left)
        self._stage(episode_id, name="done", state="done", said="", asked=None)
        said = "Took the last change back." if back else "Put the change back."
        self._say(episode, said, by=by, quiet=True)
        if episode["approved"]:
            self._queue_pictures(episode_id)
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
        found = self._units(episode, full)
        planned = {unit["id"] for unit in found}
        for row in self.store.pictures(episode_id):
            # a line that lost its picture takes the picture's row with it
            if row["unit"] not in planned and (episode_id, row["unit"]) not in self._builds:
                self.store.delete_picture(episode_id, str(row["unit"]))
        for unit in found:
            if unit["kind"] != "picture":
                continue
            have = self.store.picture(episode_id, unit["id"])
            fresh = have is not None and units.same(str(have["sig"]), unit)
            running = self._builds.get((episode_id, unit["id"]))
            if have is not None and fresh:
                # Its level is the person's: a picture made rich waits for their go on its
                # stills, and one made simple again no longer does.
                rich = unit["level"] == units.RICH
                if rich and have["status"] == "made" and not units.same(str(have["go_sig"]), unit):
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
            f"and write {root}/{brief['file']}. Deliver nothing: the house reads the file from "
            "your folder." + (f"\n\nThe person's note on it: {note}" if note else "")
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

    def make(self, episode_id: str, *, by: str) -> Row:
        """Every picture that stopped or failed is asked for again, as the plan stands."""
        episode = self._episode(episode_id)
        left = [p for p in self.store.pictures(episode_id) if p["status"] == "failed"]
        if not episode["approved"] or not left:
            raise ValueError("Every picture is made or on its way.")
        for have in left:
            self.store.set_picture(episode_id, str(have["unit"]), sig="")
        self._queue_pictures(episode_id)
        self._say(episode, "Asked for the pictures that were not made.", by=by, quiet=True)
        self._settle(episode_id)
        return self.view(episode_id)

    def send_back(self, episode_id: str, unit_id: str, *, by: str, note: str) -> Row:
        """A person's note on a picture: it is built again with the note."""
        if not note.strip():
            raise ValueError("Say what to change.")
        running = self._builds.get((episode_id, unit_id))
        if running is not None and not running.done():
            raise ValueError("It's being built. Send the note when it has landed.")
        self._rebuild(episode_id, unit_id, note)
        self._say(
            self._episode(episode_id),
            f"Sent a picture back: {note.strip()[:200]}",
            by=by,
            quiet=True,
        )
        self._settle(episode_id)
        return self.view(episode_id)

    def _rebuild(self, episode_id: str, unit_id: str, note: str) -> None:
        """Start one picture again with a person's note for its builder."""
        note = note.strip()[:600]
        self.store.set_picture(episode_id, unit_id, status="queued", note=note)
        self._builds[(episode_id, unit_id)] = asyncio.get_running_loop().create_task(
            self._rebuilt(episode_id, unit_id, note), name=f"picture {episode_id} {unit_id}"
        )
        self._changed(episode_id)

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
        source: IO[bytes],
    ) -> Row:
        """A recording of a chapter (or of one line of it): cut to the film's format on the
        thread's computer and kept as this chapter's take. `source` is the recording as an
        open file; it is read from there and never held in memory."""
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
        source.seek(0, 2)
        if source.tell() == 0:
            raise ValueError("The recording is empty.")
        made = await asyncio.to_thread(self._cut, episode, name, source)
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
        take = self.store.add_take(
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
        await self._keep_footage(episode, take, name, source, by=by)
        self._settle(episode_id)
        return self.view(episode_id)

    async def _keep_footage(
        self, episode: Row, take: Row, name: str, source: IO[bytes], *, by: str
    ) -> None:
        """The recording as it arrived, kept in the house's bucket (S3, or MinIO in
        development) under its take's name, when there is a bucket. It is kept once the cut
        has shown it is a recording. The take stands whether or not the bucket took it: a
        take is not lost to a store that is down, and the thread says when it was not kept."""
        from design_agent.tools.footage import Bucket, FootageError

        bucket = Bucket.from_settings(self.host.settings)
        if bucket is None:
            return
        key = f"episodes/{episode['id']}/takes/{take['id']}.{_ending(name)}"
        try:
            kept = await asyncio.to_thread(bucket.put, key, source, name=name)
        except FootageError as error:
            _LOGGER.warning("footage of take %s was not kept: %s", take["id"], error)
            self._say(
                episode,
                f"The recording itself was not kept in the bucket: {_clean(str(error), 240)}",
                by=by,
                quiet=True,
            )
            return
        self.store.update_take(str(take["id"]), raw=kept)

    def _cut(self, episode: Row, name: str, source: IO[bytes]) -> Row:
        """A recording as the film uses it: no taller than the film's frame, a constant 30
        frames a second with a key frame every half second (so any line can be played from
        where it starts), in the film's range of light, its sound at the film's loudness, and
        that sound beside it. The recording is copied across as a file, never held in memory:
        a camera's own runs to gigabytes."""
        computer = self._computer(episode)
        folder = f"{PROJECTS}/{episode['id']}/takes"
        stem = f"take-{int(time.time() * 1000)}"
        src = f"{folder}/{stem}.src.{_ending(name)}"
        computer.put_stream(src, source)
        # What is in it, how loud its sound is, and whether this computer can bring a bright
        # picture down to the film's range.
        looked = computer.run(
            f'cd {folder} && echo "streams: $(ffprobe -v error -show_entries '
            f"stream=codec_type,color_transfer,channels -of json {src} 2>/dev/null "
            "| tr -d ' \\n')\"; "
            f"ffmpeg -hide_banner -nostats -i {src} -vn -af ebur128=peak=true:framelog=verbose "
            "-f null - 2>&1 | tail -n 20; "
            "echo \"zscale: $(ffmpeg -hide_banner -filters 2>/dev/null | grep -c ' zscale ')\"",
            timeout=1800,
        ).output
        listed = re.search(r"^streams: (\{.*\})$", looked, re.M)
        try:
            streams = json.loads(listed[1]).get("streams", []) if listed else []
        except ValueError:
            streams = []
        video = [s for s in streams if s.get("codec_type") == "video"]
        sound = [s for s in streams if s.get("codec_type") == "audio"]
        bright = any(s.get("color_transfer") in HDR for s in video) and bool(
            re.search(r"^zscale: [1-9]", looked, re.M)
        )
        level = _levelled(looked) if sound else ""
        audio = (
            (f'-af "{level}" ' if level else "")
            # more channels than a film's two (a camera with four inputs) are mixed down
            + ("-ac 2 " if any(int(s.get("channels") or 0) > 2 for s in sound) else "")
            + "-c:a aac -b:a 160k -ar 48000"
        )
        if video:
            picture = "fps=30,scale=-2:'min(1080,ih)':flags=lanczos" + (
                f",{TONEMAP}" if bright else ""
            )
            colour = "-colorspace bt709 -color_primaries bt709 -color_trc bt709 " if bright else ""
            cut = (
                f'ffmpeg -v error -y -i {src} -vf "{picture}" -c:v libx264 -preset veryfast '
                f"-crf 18 -g 15 -pix_fmt yuv420p {colour}{audio} -movflags +faststart {stem}.mp4 "
                f"&& (ffmpeg -v error -y -i {stem}.mp4 -vn -c:a copy {stem}.m4a || true)"
            )
        else:
            cut = f"ffmpeg -v error -y -i {src} -vn {audio} {stem}.m4a"
        ran = computer.run(
            f"cd {folder} && {cut}; "
            f'for f in {stem}.mp4 {stem}.m4a; do [ -s $f ] && echo "$f $(ffprobe -v error '
            '-show_entries format=duration -of csv=p=0 $f)"; done; '
            f"rm -f {src}",
            timeout=3600,
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
        parts: list[Any] = [full.get("chapters"), full.get("brief"), takes, made, spoken]
        picked = (episode["settings"].get("narrator") or {}).get("id")
        if picked and episode["settings"].get("voice") == "narrator":
            # a voice picked for this film: another one is another film. A film narrated in
            # the house's voice keeps the signature it was rendered with.
            parts.append(picked)
        return plans.digest(json.dumps(parts, sort_keys=True))

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
        if not self._speaks():
            raise ValueError("Narration needs ELEVENLABS_API_KEY.")
        voice_id = self._voice_id(episode)
        if not voice_id:
            raise ValueError("Narration needs a voice: pick one under Voice, or clone yours.")
        from design_agent.tools.media import MediaKeys, speak

        keys = MediaKeys.from_settings(self.host.settings)
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

    # -- the narrator's voice --------------------------------------------------------------------

    async def voices(self) -> dict[str, Any]:
        """The voices a narrator can speak in: the ElevenLabs account's, the ones made in it
        first, with the house's own marked. The account is asked again after a minute."""
        if not self._speaks():
            raise ValueError("Narration needs ELEVENLABS_API_KEY.")
        from design_agent.tools.media import MediaKeys, voices

        heard = self._listed
        if heard is None or time.monotonic() - heard[0] > VOICES_KEPT:
            found = await voices(MediaKeys.from_settings(self.host.settings))
            if isinstance(found, str):
                raise ValueError(found)
            heard = self._listed = (time.monotonic(), found)
        usual = str(self.host.settings.narrator_voice_id or "")
        rows = [
            {"id": v.id, "name": v.name, "own": v.own, "usual": v.id == usual} for v in heard[1]
        ]
        if usual and not any(row["usual"] for row in rows):
            # a voice from ElevenLabs' library, used by its id without being kept in the account
            rows.insert(0, {"id": usual, "name": "The house's voice", "own": False, "usual": True})
        return {"voices": rows}

    def _samples(self, episode_id: str) -> tuple[list[tuple[str, bytes]], float]:
        """The sound of the takes a person kept, oldest first, until there is as much speech
        as a clone uses, and how many seconds of it that is."""
        from design_agent.tools.media import CLONE_SAMPLES

        samples: list[tuple[str, bytes]] = []
        seconds = 0.0
        for take in self.store.takes(episode_id):
            if seconds >= CLONE_ENOUGH or len(samples) >= CLONE_SAMPLES:
                break
            row = self.store.file(str(take["audio"])) if take["kept"] and take["audio"] else None
            if row is None or int(row["size"]) > CLONE_TAKE_BYTES:
                continue
            samples.append((str(row["name"]), (self.host.files_dir / row["rel_path"]).read_bytes()))
            seconds += float(take["seconds"])
        return samples, seconds

    async def clone(
        self,
        episode_id: str,
        *,
        by: str,
        name: str,
        consent: bool,
        noisy: bool = False,
        sample: tuple[str, bytes] | None = None,
    ) -> Row:
        """A voice made by ElevenLabs from recordings of a person, which then narrates this
        episode: from the takes they kept, or from one recording they bring (`sample`, a file
        name and its bytes). The recordings leave this computer and a voice is a person's own,
        so each time the person says it is theirs to clone, and the thread keeps that they did."""
        episode = self._episode(episode_id)
        if not self._speaks():
            raise ValueError("Cloning a voice needs ELEVENLABS_API_KEY.")
        if not consent:
            raise ValueError("Say that the voice is yours, or that its speaker agreed.")
        title = _clean(name, 60)
        if not title:
            raise ValueError("Give the voice a name.")
        if sample is not None:
            samples, source = [sample], "a recording brought as a file"
        else:
            samples, seconds = self._samples(episode_id)
            if seconds < CLONE_LEAST:
                raise ValueError(
                    f"A clone needs {int(CLONE_LEAST)} seconds of your takes or more. "
                    "Record a chapter first, or bring a recording."
                )
            source = f"{len(samples)} take{'s' if len(samples) != 1 else ''} of this episode"
        from design_agent.tools.media import MediaKeys, clone_voice

        made = await clone_voice(
            MediaKeys.from_settings(self.host.settings), title, samples, noisy=noisy
        )
        if isinstance(made, str):
            raise ValueError(made)
        self._listed = None
        picked: Row = {"id": made.voice_id, "name": title}
        if made.verify:
            # ElevenLabs wants the speaker verified on its own site before the voice speaks
            picked["verify"] = True
        episode = self._episode(episode_id)
        self.store.update_episode(
            episode_id, settings={**episode["settings"], "voice": "narrator", "narrator": picked}
        )
        self._say(
            episode,
            f"Cloned a voice with ElevenLabs, “{title}”, from {source}, having confirmed the "
            "voice is theirs to clone. It narrates the lines nobody recorded.",
            by=by,
        )
        self._settle(episode_id)
        return self.view(episode_id)

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
        # Kept as the episode's own file: its card holds the film, and an earlier render
        # never lingers on the canvas as something delivered loose.
        row = self.host.save_file(
            str(episode["thread_id"]), f"{slug}.mp4", content, origin="episode"
        )
        episode = self._episode(episode_id)
        # The narration stays with the film: it is what the film's clock and signature were
        # made from, and a line already spoken is not paid for again at the next render.
        narration = (episode["film"] or {}).get("voice")
        self.store.update_episode(
            episode_id,
            film={
                **({"voice": narration} if narration else {}),
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
        if episode["status"] == "failed":
            status = "blocked"
        elif self._busy(episode_id):
            status = "making"
        elif waiting:
            status = "review"
        elif (episode["film"] or {}).get("status") == "done":
            status = "done"
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
                kept = self.store.snapshot(episode_id)
                if (
                    (episode["stage"] or {}).get("name") in ("redo", "change")
                    and kept is not None
                    and kept["data"].get("plan")
                    and not kept["summary"]
                ):
                    # a change that was under way is not half made: the plan is as it stood
                    self.store.update_episode(
                        episode_id, plan=kept["data"]["plan"], labels=kept["data"]["labels"]
                    )
                    self.store.drop_snapshot(kept["n"])
                self.store.update_episode(
                    episode_id,
                    # a plan that was still being written stopped; one that stood still stands
                    status="failed" if episode["status"] == "planning" else episode["status"],
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
            # nothing is running now: its card and its thread say where it stands, not where
            # the last process left it
            self._settle(episode_id)

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
            "stage": {k: stage.get(k) for k in ("name", "state", "said", "round", "at", "asked")},
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
        changed = self.store.snapshot_note(episode_id)
        undone = self.store.snapshot_note(episode_id, "undone")
        said: dict[str, float] = {}
        for t in self.store.takes(episode_id):
            if t["kept"]:
                key = str(t["frame"] or t["chapter"])
                said[key] = max(said.get(key, 0.0), float(t["created_at"]))
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
            # the last change that stands: what it did, and how many before it can also go back
            "last_change": (
                {
                    "why": changed["why"],
                    "at": changed["at"],
                    **changed["summary"],
                    "earlier": self.store.snapshots(episode_id) - 1,
                }
                if changed is not None and changed["summary"]
                else None
            ),
            # the change that was last taken back, while it can still be put back
            "undone": ({"why": undone["why"], **undone["summary"]} if undone is not None else None),
            # lines a person reworded after they were recorded: the take says the old words
            "rerecord": [
                f["id"]
                for ch, _b, f in plans.frames_of(full or {})
                if ch["id"] in said
                and float((f.get("by_person") or {}).get("at") or 0.0)
                > max(said[ch["id"]], said.get(f["id"], 0.0))
            ],
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
            "stale": not units.same(str(have["sig"]), unit),
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


def _changed(before: Row, after: Row) -> Row:
    """What a change did to the plan's lines: the ones whose words changed (and what they
    said), the new ones, the ones that are gone (what they said, and the line they came
    after), and the ones that kept their words while their picture was planned again."""
    was, now = _lines(before), _lines(after)
    chapter_of = {
        str(f["id"]): str(ch["id"]) for ch, _, f in plans.frames_of(plans.merged(before, {}))
    }
    order = list(was)
    cut: list[Row] = []
    for i, key in enumerate(order):
        if key in now:
            continue
        stays = next((k for k in reversed(order[:i]) if k in now), "")
        # the line it came after, when that line is in its own chapter and still stands
        after_line = stays if stays and chapter_of[stays] == chapter_of[key] else ""
        cut.append({"says": was[key][0], "chapter": chapter_of[key], "after": after_line})
    reworded = [k for k in now if k in was and now[k][0] != was[k][0]]
    return {
        "lines": reworded,
        "was": {k: was[k][0] for k in reworded},
        "added": [k for k in now if k not in was],
        "removed": len(cut),
        "cut": cut[:CUT_SHOWN],
        "pictures": [
            k for k in now if k in was and now[k][0] == was[k][0] and now[k][1] != was[k][1]
        ],
    }


def _lines(plan: Row) -> dict[str, tuple[str, str]]:
    """Every line by its id, as the writer's plan has it: its words, and what it shows."""
    return {
        str(f["id"]): (
            " ".join(str(f.get("vo") or "").split()),
            json.dumps(
                [f.get("shows"), f.get("hold"), f.get("objects"), f.get("cues")], sort_keys=True
            ),
        )
        for _, _, f in plans.frames_of(plans.merged(plan, {}))
    }


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
