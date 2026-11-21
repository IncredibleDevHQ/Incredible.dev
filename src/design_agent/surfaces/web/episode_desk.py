"""An episode on the canvas: a planned explainer, taken from notes to a rendered film.

An episode is a piece of work in a task, like any asset, with a studio of its own. A person
starts one from material (their words and files, or a research frame's notes), picks who
writes it (a coding agent on this computer or the built-in agent), and then:

- **the plan** is written in stages by that agent, each stage read by a classifier and checked
  by code before the next (`design_agent.episode`); the person approves it once;
- **each chapter** is worked in one place: who has the frame for every line, the layout, and
  whether a picture is made at once (simple) or posed as stills for the person's go (rich).
  The pictures are built meanwhile, by the same agent, and posed on the thread's computer;
- **a take** per chapter is recorded in the browser (or brought as a file, or a clip read
  where it is on a camera's card) and cut to the film's format, with a copy for 4K from a
  recording taller than the film's frame; where a line was started in the take sets when its
  picture's cues land. A camera's clip of a studio take is found under it by sound (`sync`) and
  takes its marks;
- **the narrator** says the lines no take covers, when the person chooses one: in a voice of
  the ElevenLabs account, or in a clone of the person's own made from their takes;
- **the film** is one HyperFrames project written by code (`episode.film`) and rendered on the
  thread's computer, in HD or in 4K.

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
import secrets
import shlex
import shutil
import tempfile
import threading
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any
from urllib.parse import unquote

from design_agent.episode import (
    catalog,
    check,
    classifier,
    classify,
    derive,
    film,
    geometry,
    illustrations,
    layouts,
    override,
    picture,
    sketch,
    sync,
    timeline,
    units,
)
from design_agent.episode import plan as plans
from design_agent.episode import questions as Q
from design_agent.surfaces.web import episode_models, episode_render, research
from design_agent.surfaces.web.computer import GSAP, PROJECTS, Computer
from design_agent.surfaces.web.episode_workers import (
    BUILTIN,
    DEMO,
    BuiltinWorker,
    DemoWorker,
    LocalWorker,
    Told,
    Worker,
    asked_now,
)
from design_agent.surfaces.web.hub import Hub
from design_agent.surfaces.web.store import Row, Store, new_id
from design_agent.tools import local_speech
from design_agent.workspace.manifest import BrandFor, BrandSnapshot, ManifestBook

if TYPE_CHECKING:
    from design_agent.surfaces.web.agent import AgentHost
    from design_agent.tools.media import Voice

_LOGGER = logging.getLogger(__name__)

#: Says what an agent builds on for a pick of model and effort, as a made picture's record
#: keeps it; a ValueError when the agent does not offer them (`EpisodeDesk._generation`).
Generation = Callable[[str, Row], Row]
#: An episode's own task thread, and its asset on the canvas.
EPISODE = "episode"
#: Fix rounds a stage gets before the plan goes on with what the checks still flag.
ROUNDS = 3
#: Turns on a plan that already stands: a pick that leaves the writer something to redo, a
#: change a person asks for in words, a line whose words a person changed. One that fails or
#: is stopped leaves the plan as it was.
STANDING = ("redo", "change")
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
#: Tries a rich picture's motion plan gets at its shape before the picture says it failed.
MOTION_TRIES = 2
#: Pictures built at once by a local agent. The built-in agent builds one at a time: its
#: thread holds one turn.
PICTURES_AT_ONCE = 2
#: Pictures one agent builds at once across every episode, so many episodes handed to it wait
#: their turn. The built-in agent builds one, as it does within an episode.
HOUSE_AT_ONCE = 4
#: Earlier versions of a picture kept to look back at and to put back; past this, the
#: oldest made is dropped.
VERSIONS = 12
#: What a version of a picture is kept as: all it needs to stand again as it was made.
VERSION_KEEPS = (
    "status",
    "sig",
    "html",
    "stills",
    "clip",
    "go_sig",
    "level",
    "builder",
    "generation",
    "motion",
    "words",
    "timing",
)
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
#: What each kind of picture is, and how long each way in takes, as the plan's own table has them.
KINDS = Q.table("picture_types")
WAYS_IN = Q.table("transitions")
WAYS_BY_RELATION = {str(r["id"]): r["transition"] for r in Q.TYPES["relations"]}
LEVELS = units.LEVELS
#: What a person adds to a chapter's script: a line that goes on in its block, a block said to
#: camera, or a block whose line brings in a picture of one of the types they may pick.
LINE_KINDS = ("more", "camera", *override.PICTURES)
VOICES = ("live", "narrator", "local")
#: A clone of a person's voice is made from their takes: this much speech at least, and no
#: more than a clone uses. A take over the size ElevenLabs takes for one recording is left out.
#: Keep previews and narration close to the speaker using Eleven v4’s similarity setting.
CLONE_SIMILARITY = 0.9
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
#: A take's copies on the thread's computer and among the house's files, by kind: one no taller
#: than the film's frame (the studio's, and a film in HD's), one no taller than `UHD` for a film
#: in 4K (made only from a recording taller than the film's frame), and its sound alone.
COPIES = {"video": "mp4", "uhd": "uhd.mp4", "audio": "m4a"}
UHD = 2160
#: Frame rates the film's 30 a second shows without a step: a camera's NTSC rates, and double.
SMOOTH_RATES = (29.97, 30.0, 59.94, 60.0)
#: How often a cut under way is looked at, and how often a recording being brought in says how
#: far it has come (seconds).
CUT_POLL = 1.0
IMPORT_TOLD = 1.5
#: The sizes a film is rendered in. HyperFrames renders the same 1920 by 1080 page at twice the
#: density for 4K, so a film's pictures, type and windows are the same in both.
SIZES = ("hd", "4k")
#: Room a render takes on the thread's computer while it runs, by a second of film (bytes), with
#: a floor for the rest: measured, with some to spare.
SCRATCH = {"hd": 8 * 1024**2, "4k": 44 * 1024**2}
SCRATCH_FLOOR = 2 * 1024**3
#: How much longer a film takes to render in 4K than in HD, measured (2.3 times), with room.
SLOWER_4K = 3
#: The stages a plan is written in, as the studio names them while it waits.
STEPS: tuple[tuple[str, str], ...] = (
    ("brief", "Read the material"),
    ("script", "Write the script"),
    ("frames", "Frame every line"),
    ("check", "Check the plan"),
)
#: The renderer's check prints its findings under these heads. A file that breaks the first two
#: does not render as written; the rest are about how it looks.
CHECK_SECTIONS = ("Lint", "Runtime", "Layout", "Motion", "Contrast", "Craft", "Audio", "Snapshots")
BREAKING = ("Lint", "Runtime")
#: What the renderer's craft pass says of how a picture plays (a stretch with nothing changing,
#: a line too brief to read, type under the floor, an empty first frame). They are questions for
#: the builder's review, never faults; a picture has no sound of its own, so that one is dropped.
CRAFT_NOTE = re.compile(r"[⚠ℹ]\s*([a-z_]+):\s*(.+)")
CRAFT_SKIPPED = frozenset({"film_silent"})
#: How each of a picture builder's turns opens, by the stage it belongs to. Code writes every
#: prompt, so a turn's stage is read back from its first words. A build begins with the turn
#: that plans it (motion graphics; its drawing turn opens like a simple picture's first) or the
#: one that draws it (a simple picture).
TURN_STAGES: tuple[tuple[str, str], ...] = (
    ("Stage: motion plan.", "motion"),
    ("Stage: picture.\n\nLook at how", "review"),
    ("Stage: picture.", "draw"),
)
BUILD_OPENINGS: dict[str, str] = {
    units.RICH: "Stage: motion plan.\n\nPlan how",
    units.SIMPLE: "Stage: picture.\n\nBuild one picture",
}
#: A build's stages in order: the builder's turns, the stills the house takes between the
#: drawing and the review, and a motion-graphics picture's go, which is the person's.
BUILD_STAGES: dict[str, tuple[str, ...]] = {
    units.RICH: ("motion", "draw", "pose", "review", "go"),
    units.SIMPLE: ("draw", "pose"),
}
#: Where a picture stands as a job on the production board, by its record's status ("none" for
#: one never asked for). A made one that is out of date is to make again, whatever this says.
JOB_STATES: dict[str, str] = {
    "none": "todo",
    "queued": "waiting",
    "making": "running",
    "posing": "running",
    "go": "go",
    "made": "done",
    "failed": "failed",
}
#: How many of an agent's newest made pictures say how long one takes it to build.
BUILDS_MEANT = 20
#: The longest note a person can leave a picture's builder while it works.
NOTE_CHARS = 600
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


@dataclass(frozen=True)
class Seen:
    """What ffprobe found in a recording: its picture (the first), its sound, how long it runs,
    and whether it is coded for a brighter screen than the film's (and can be brought down)."""

    video: Row | None = None
    sound: tuple[Row, ...] = ()
    seconds: float = 0.0
    bright: bool = False

    @property
    def height(self) -> int:
        return int((self.video or {}).get("height") or 0)

    @property
    def fps(self) -> float:
        top, _, bottom = str((self.video or {}).get("avg_frame_rate") or "").partition("/")
        try:
            return float(top) / float(bottom or 1)
        except (ValueError, ZeroDivisionError):
            return 0.0

    @property
    def bt709(self) -> bool:
        return (self.video or {}).get("color_space") == "bt709"


@dataclass
class Brought:
    """A recording on the thread's computer, between being looked at and being cut."""

    computer: Computer
    folder: str
    take_id: str
    src: str
    seen: Seen = dataclass_field(default_factory=Seen)
    match: sync.Match | None = None


def _seen(looked: str) -> Seen:
    listed = re.search(r"^streams: (\{.*\})$", looked, re.M)
    try:
        probe = json.loads(listed[1]) if listed else {}
    except ValueError:
        probe = {}
    streams = [s for s in probe.get("streams") or [] if isinstance(s, dict)]
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    try:
        seconds = float((probe.get("format") or {}).get("duration") or 0.0)
    except (TypeError, ValueError):
        seconds = 0.0
    return Seen(
        video=video,
        sound=tuple(s for s in streams if s.get("codec_type") == "audio"),
        seconds=seconds,
        bright=bool(video and video.get("color_transfer") in HDR)
        and bool(re.search(r"^zscale: [1-9]", looked, re.M)),
    )


def _noticed(seen: Seen, clip: Mapping[str, Any]) -> Row:
    """What a person should know of a recording brought in, in a line: a frame rate the film's
    30 can't show smoothly, and a camera's log picture, which looks flat until it is graded."""
    notes: list[str] = []
    rate = seen.fps
    if seen.video and rate and not any(abs(rate - r) < 0.05 for r in SMOOTH_RATES):
        notes.append(
            f"Recorded at {rate:.3g} fps; the film runs at 30, so movement steps a little."
            + (" Set the camera to NTSC for 30p." if round(rate) in (25, 50) else "")
        )
    if str(clip.get("look") or "").startswith("s-log"):
        notes.append(
            "Recorded in S-Log3, so it looks flat in the film: Picture Profile PP11 "
            "(S-Cinetone) gives the finished look."
        )
    return {
        "height": seen.height or None,
        "fps": round(rate, 3) if rate else None,
        "note": " ".join(notes),
    }


def _gb(size: float) -> str:
    return f"{size / 1024**3:.0f} GB" if size >= 10 * 1024**3 else f"{size / 1024**3:.1f} GB"


def _label(label: str) -> str:
    label = label.strip()
    if len(label) > 120:
        raise ValueError("Version names must be 120 characters or fewer.")
    return label


def _given(marks: Sequence[Mapping[str, Any]], lines: Sequence[Row]) -> list[Row]:
    """The marks a recording came with, for the chapter's own lines only."""
    ids = {f["id"] for f in lines}
    return [
        {"frame": str(m["frame"]), "t": round(max(0.0, float(m["t"])), 3)}
        for m in marks
        if str(m.get("frame")) in ids
    ]


def _spread(lines: Sequence[Row], seconds: float) -> list[Row]:
    """A recording brought with no marks: each line is taken to start where the plan's pace puts
    it, stretched over the take."""
    total = sum(float(f["seconds"]) for f in lines) or 1.0
    at, out = 0.0, []
    for f in lines:
        out.append({"frame": f["id"], "t": round(at / total * seconds, 3)})
        at += float(f["seconds"])
    return out


def _stem(name: str) -> str:
    """A recording's own name, as much of it as is safe in a file's name (`C0012`)."""
    return re.sub(r"[^A-Za-z0-9_-]", "", Path(name).stem)[:40] or "recording"


def _keep_file(source: IO[bytes] | Path, target: Path, *, move: bool) -> None:
    """A recording put where it is kept, as a file: moved when it is the house's own copy,
    otherwise copied (and never left half copied under its name)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(source, Path) and move:
        shutil.move(str(source), target)
        return
    partial = target.with_name(f".{target.name}.part")
    try:
        if isinstance(source, Path):
            shutil.copyfile(source, partial)
        else:
            source.seek(0)
            with partial.open("wb") as out:
                shutil.copyfileobj(source, out, 4 * 1024 * 1024)
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)


def _quietly(work: Callable[..., Any], *args: Any) -> None:
    """Tidying up that must not stop what it follows."""
    try:
        work(*args)
    except Exception:
        _LOGGER.warning("tidying up after a take failed", exc_info=True)


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
        #: Recordings being brought in say where they stand from their own threads.
        self._imports_lock = threading.Lock()
        #: When each picture on its way was asked for.
        self._asked: dict[tuple[str, str], float] = {}
        #: Episodes whose applied picks are with the writer: their pictures follow its turn.
        self._then_draw: set[str] = set()
        # pictures a person asked to have planned again: drawn again once the writer has
        self._redraw: dict[str, set[str]] = {}
        #: A builder's turns within an episode (`PICTURES_AT_ONCE`), and across every episode
        #: (`HOUSE_AT_ONCE`).
        self._gates: dict[str, asyncio.Semaphore] = {}
        self._house: dict[str, asyncio.Semaphore] = {}
        self._said_at: dict[str, float] = {}
        #: What the renderer's craft pass said of each picture as it was last posed, kept for
        #: its builder's review.
        self._craft: dict[tuple[str, str], list[str]] = {}
        #: Notes a person left a picture's builder while it worked, waiting for its next turn on
        #: the picture; the ones the build took in, each with the stage it went to; when each
        #: build began; and the builds whose last turn (the review) has begun.
        self._steer: dict[tuple[str, str], list[Row]] = {}
        self._steered: dict[tuple[str, str], list[Row]] = {}
        self._began: dict[tuple[str, str], float] = {}
        self._last_turn: set[tuple[str, str]] = set()
        self._closing = False
        #: The brand pack a thread's channel wears (the app's brand shelf), or None for the
        #: configured one.
        self.brand_for: BrandFor | None = None
        self._book: ManifestBook | None = None
        #: The ElevenLabs account's voices as last listed, and when (a monotonic time).
        self._listed: tuple[float, list[Voice]] | None = None

    # -- what an episode can be made with -------------------------------------------------------

    def options(self, writer: str | None = None) -> dict[str, Any]:
        writers: list[dict[str, Any]] = [
            {
                "id": h.id,
                "title": h.title,
                "ready": self.host.research.ready(h.id),
                "local": True,
            }
            for h in research.HARNESSES.values()
        ]
        if self.demo:
            writers.append(
                {"id": DEMO, "title": "HTTP caching sample", "ready": True, "local": False}
            )
        else:
            writers.append(
                {
                    "id": BUILTIN,
                    "title": "Built-in agent",
                    "ready": self.host.runtime is not None,
                    "local": False,
                }
            )
        for w in writers:
            w["provider"] = episode_models.generation(self.host.settings, w["id"], {})["provider"]
        return {
            "writers": writers,
            "components": {
                k: {"purpose": v.purpose, "layouts": v.layouts}
                for k, v in catalog.COMPONENTS.items()
            },
            "picture_writers": writers,
            "generation_models": {
                w["id"]: episode_models.options(self.host.settings, w["id"]) for w in writers
            },
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
            "local_narrator": local_speech.engine() is not None,
            "reader": "demo"
            if writer == DEMO or writer is None and self.demo
            else "jev"
            if self._jev_key()
            else "writer",
            # a narrator can speak (ElevenLabs has a key), and the house has a voice of its
            # own for one; without that, an episode picks a voice or clones the person's
            "narrator": {
                "ready": self._speaks(),
                "usual": bool(self.host.settings.narrator_voice_id),
            },
            "geometry": geometry.view(),
            # what a person may pick for the line that brings a picture in: each kind with what
            # it is, and each way in with how long it takes, for the studio to show them
            "pictures": [{"id": p, "means": KINDS[p]["reads_as"]} for p in override.PICTURES],
            "transitions": [
                {"id": t, "seconds": float(WAYS_IN[t]["seconds"])} for t in override.TRANSITIONS
            ],
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
        """The film's agent, on the model and effort picked for the film (its own otherwise)."""
        worker = self._worker_called(str(episode["settings"].get("writer") or ""))
        pick = self._film_pick(episode)
        if isinstance(worker, LocalWorker | BuiltinWorker):
            model = pick["model"] or self._default_model(worker)
            if model != worker.model or pick["effort"]:
                scoped = copy.copy(worker)
                scoped.model, scoped.effort = model, pick["effort"]
                return scoped
        return worker

    def _default_model(self, worker: LocalWorker | BuiltinWorker) -> str:
        if worker.id == "codex":
            return episode_models.codex_default_model(self.host.settings)
        return worker.model

    def _generation(self, builder: str, pick: Row) -> Row:
        """What an agent builds on for a pick of model and effort (see `Generation`)."""
        return episode_models.generation(self.host.settings, builder, pick)

    def _film_pick(self, episode: Row, generation: Generation | None = None) -> Row:
        """The model and effort picked for the film's agent, while that agent still offers them
        (an agent's models are its own to change): nothing picked is the agent's default."""
        chosen = episode["settings"]
        pick = {k: str(chosen.get(f"writer_{k}") or "") for k in ("model", "effort")}
        if pick["model"] or pick["effort"]:
            try:
                (generation or self._generation)(str(chosen.get("writer") or ""), pick)
            except ValueError:
                return {"model": "", "effort": ""}
        return pick

    def _builder(self, episode: Row, unit: Row) -> Worker:
        """Who builds one picture: the agent a person picked for it, else its chapter's, else
        the film's writer, on the model and effort that hold for it (`_units` settles both)."""
        worker = self._worker_called(
            str(unit.get("builder") or episode["settings"].get("writer") or "")
        )
        now = unit.get("model_now") or unit.get("model_pick") or {}
        model, effort = now.get("model", ""), now.get("effort", "")
        if (
            isinstance(worker, LocalWorker)
            or isinstance(worker, BuiltinWorker)
            and (model or effort)
        ):
            scoped = copy.copy(worker)
            scoped.model, scoped.effort = model or self._default_model(worker), effort
            return scoped
        return worker

    def _can_write(self, writer: str) -> bool:
        ready = {w["id"] for w in self.options()["writers"] if w["ready"]}
        return writer in ready or writer in self.workers

    def _worker_called(self, writer: str) -> Worker:
        if writer in self.workers:
            return self.workers[writer]
        made: Worker
        if writer == BUILTIN:
            made = BuiltinWorker(self.host, self.project_root)
        elif writer == DEMO:
            from design_agent.surfaces.web.demo_episode import SCRIPT

            made = DemoWorker(data_dir=self.data_dir, script=SCRIPT, store=self.store)
        elif writer in research.HARNESSES:
            made = LocalWorker(
                writer, store=self.store, data_dir=self.data_dir, project_root=self.project_root
            )
            if writer == "codex":
                made.model = self._default_model(made)
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

    def _brand_root(self, thread_id: str) -> Path | BrandSnapshot | None:
        """The brand pack a thread's work wears: its channel's, else the configured one."""
        folder = self.brand_for(thread_id) if self.brand_for is not None else None
        if isinstance(folder, BrandSnapshot):
            return folder
        if folder is None:
            folder = self.host.settings.resolved_brand_path(self.project_root)
        return folder if (folder / "brand.toml").is_file() else None

    def _look(self, episode: Row, brand: picture.Look | None = None) -> picture.Look:
        settings = episode["settings"]
        return (brand or self._brand_look(episode)).with_background(
            settings.get("background_color", ""), settings.get("background_texture", "solid")
        )

    def _brand_look(self, episode: Row) -> picture.Look:
        """What the episode's pictures and the film's own cards wear: the brand's colours by
        role and the first family of each of its type stacks."""
        root = self._brand_root(str(episode["thread_id"]))
        if root is None:
            return picture.Look()
        from design_agent.surfaces.web.brands import brand_view

        if isinstance(root, BrandSnapshot):
            with root.open() as folder:
                view = brand_view(folder)
        else:
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
        swatches = {str(c["name"]).lower(): str(c["value"]) for c in view.get("colors", [])}
        palette["panel"] = (
            swatches.get("panel")
            or swatches.get("surface")
            or (palette["ground"] if _dark(palette["ground"]) else palette["panel"])
        )
        if roles.get("accent"):
            palette["accent_ink"] = (
                "#FFFFFF"
                if _dark(roles["accent"])
                else (palette["ink"] if _dark(palette["ink"]) else palette["ground"])
            )
        stacks = view.get("stacks") or {}

        def family(role: str, otherwise: str) -> str:
            named = [str(n) for n in stacks.get(role) or [] if str(n).lower() not in GENERIC]
            return named[0] if named else otherwise

        return picture.Look(
            palette=palette,
            display=family("display", "Fraunces"),
            text=family("text", "Inter"),
            mono=family("mono", "IBM Plex Mono"),
            series=tuple(view.get("series", [])),
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
        if self.demo and not (settings or {}).get("writer") and (words or frame_id or file_ids):
            raise ValueError(
                "Choose a writer for your notes or explicitly select the HTTP caching sample."
            )
        material = [words] if words else []
        if frame_id:
            frame = self.store.thread(frame_id)
            if frame is None or self.store.research(frame_id) is None:
                raise KeyError(frame_id)
            self._channel_narrator(chosen, str(frame["channel_id"]))
            notes = self.host.research.notes_markdown(frame_id)
            if not notes:
                raise ValueError("Keep a note from the research first: an episode starts there.")
            material.insert(0, notes)
            thread = frame
        else:
            self._channel_narrator(chosen, channel_id)
            for file_id in file_ids:
                row = self.store.file(file_id)
                if row is not None and str(row["name"]).lower().endswith(TEXT_FILES):
                    body = self.host.blobs.read(row).decode("utf8", "replace")
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
        if given.get("voice") == "local" and not local_speech.engine():
            raise ValueError("Local narration needs macOS speech or espeak-ng.")
        if given.get("voice") in VOICES:
            out["voice"] = given["voice"]
        if "narrator" in given and given["narrator"] is None:
            out.pop("narrator", None)
        elif given.get("narrator"):
            from design_agent.tools.media import VOICE_ID

            picked = given["narrator"]
            if not VOICE_ID.fullmatch(str(picked.get("id") or "")):
                raise ValueError("That isn't an ElevenLabs voice.")
            out["narrator"] = {
                "id": str(picked["id"]),
                "name": _clean(str(picked.get("name") or ""), 80) or "A voice",
            }
            clone = out.get("cloned_voice") or {}
            if clone.get("id") == picked["id"] and clone.get("verify"):
                out["narrator"]["verify"] = True
        if "portrait" in given:
            if given["portrait"] not in film.PORTRAITS:
                raise ValueError("Unknown presenter portrait.")
            out["portrait"] = given["portrait"]
        if "background_color" in given:
            color = given["background_color"]
            if not isinstance(color, str) or (
                color and not re.fullmatch(r"#[0-9a-fA-F]{6}", color)
            ):
                raise ValueError("Choose a six-digit hex background color.")
            out["background_color"] = color.lower()
        if "background_texture" in given:
            texture = given["background_texture"]
            if not isinstance(texture, str) or texture not in picture.TEXTURES:
                raise ValueError("Unknown background texture.")
            out["background_texture"] = texture
        if given.get("level") in LEVELS:
            out["level"] = given["level"]
        if "writer" in given:
            writer = str(given["writer"])
            if not self._can_write(writer):
                raise ValueError("That writer isn't ready on this computer.")
            if writer != out.get("writer"):
                # another agent has its own models: the picks made for the last one go
                out.pop("writer_model", None)
                out.pop("writer_effort", None)
            out["writer"] = writer
        if "writer" not in out:
            first = next((w["id"] for w in self.options()["writers"] if w["ready"]), "")
            if not first:
                raise ValueError("No writer is ready: install a coding agent or set a model.")
            out["writer"] = first
        if "writer_model" in given or "writer_effort" in given:
            # the model the film's agent runs on and how hard it thinks; a new model's efforts
            # are its own, so one picked without an effort starts on its default
            model = str(given.get("writer_model", out.get("writer_model")) or "")
            effort = str(
                given.get(
                    "writer_effort", "" if "writer_model" in given else out.get("writer_effort")
                )
                or ""
            )
            episode_models.generation(
                self.host.settings, out["writer"], {"model": model, "effort": effort}
            )
            for key, value in (("writer_model", model), ("writer_effort", effort)):
                out.pop(key, None)
                if value:
                    out[key] = value
        return out

    # -- reading the plan -----------------------------------------------------------------------

    def _episode(self, episode_id: str) -> Row:
        episode = self.store.episode(episode_id)
        if episode is None:
            raise KeyError(episode_id)
        return episode

    def _channel_of(self, episode: Row) -> str:
        thread = self.store.thread(str(episode["thread_id"]))
        if not thread:
            raise KeyError(episode["thread_id"])
        return str(thread["channel_id"])

    def _channel_narrator(self, settings: Row, channel_id: str) -> None:
        narrator = settings.get("narrator")
        if not narrator or not (voice := self.store.voice_clone(narrator["id"])):
            return
        if voice["channel_id"] != channel_id:
            raise ValueError("That cloned voice belongs to another channel.")
        settings["narrator"] = self._clone_pick(voice)

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
        for _, _, frame in plans.frames_of(full):
            pick = frame.get("picked") or {}
            if pick.get("window_size") or pick.get("window_shape"):
                spot = geometry.for_frame(frame)
                if spot.person:
                    frame["window"] = {"box": list(spot.person), "radius": spot.person_radius}
        full["title"] = episode["title"]
        return full

    def _units(
        self,
        episode: Row,
        full: Row,
        look: picture.Look | None = None,
        generation: Generation | None = None,
    ) -> list[Row]:
        """The plan's units, each with who builds it and on what. A read of many episodes hands
        in the look and the `generation` it already has, so neither is read again for each."""
        found = units.units(
            full, episode["picks"] or {}, level=str(episode["settings"].get("level", "simple"))
        )
        chosen = (episode["picks"] or {}).get("units", {})
        by_chapter = self._chapter_builders(episode)
        writer = str(episode["settings"].get("writer") or "")
        generation = generation or self._generation
        film_pick = self._film_pick(episode, generation)
        said = {str(f["id"]): f for _, _, f in plans.frames_of(full)}
        if not found:
            return []
        look = look or self._look(episode)
        theme_sig = plans.digest(json.dumps(look.tokens(), sort_keys=True))
        for unit in found:
            unit["theme_sig"] = theme_sig
            unit["custom_background"] = look.custom_color or look.texture != "solid"
            # who builds it: the agent picked for this picture, else its chapter's, else the
            # film's writer
            unit["builder"] = str(
                (chosen.get(unit["id"]) or {}).get("builder")
                or by_chapter.get(str(unit["chapter"]))
                or writer
            )
            pick = chosen.get(unit["id"]) or {}
            unit["builder_pick"] = pick.get("builder")
            unit["model_pick"] = (
                {k: pick.get(k, "") for k in ("model", "effort")}
                if not pick.get("builder") or pick["builder"] == unit["builder"]
                else {"model": "", "effort": ""}
            )
            # what it is built on: its own pick, else the film's while the film's agent builds
            # it, else that agent's default
            own = unit["model_pick"]
            if own["model"] or own["effort"]:
                unit["model_now"] = {**own, "from": "beat"}
            elif unit["builder"] == writer and (film_pick["model"] or film_pick["effort"]):
                unit["model_now"] = {**film_pick, "from": "film"}
            else:
                unit["model_now"] = {"model": "", "effort": "", "from": ""}
            try:
                unit["generation"] = generation(unit["builder"], unit["model_now"])
            except ValueError:
                # the agent no longer offers what was picked: its default builds it
                unit["model_now"] = {"model": "", "effort": "", "from": ""}
                unit["generation"] = generation(unit["builder"], {})
            # what its lines say now, and when a person last made one say something else
            lines = [said.get(str(frame)) or {} for frame in unit["frames"]]
            unit["words_now"] = _said(lines)
            unit["reworded_at"] = max(
                (
                    float(mark.get("at") or 0.0)
                    for f in lines
                    if (mark := f.get("by_person") or {}) and f.get("vo") != mark.get("was")
                ),
                default=0.0,
            )
        return found

    def _chapter_builders(self, episode: Row) -> dict[str, str]:
        """The agent a person picked to build each chapter's pictures, by chapter."""
        picked = (episode["picks"] or {}).get("chapters", {})
        return {
            str(chapter): str(pick["builder"])
            for chapter, pick in picked.items()
            if (pick or {}).get("builder")
        }

    def _status(self, episode_id: str) -> str:
        """Where an episode with a plan stands: in the studio once its pictures were asked for
        (all of them, or the first one by name) or a chapter was recorded; a plan before."""
        episode = self._episode(episode_id)
        started = (
            episode["approved"]
            or bool(self.store.pictures(episode_id))
            or bool(self.store.takes(episode_id))
        )
        return "studio" if started else "plan"

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
        self._then_draw.discard(episode_id)
        self._redraw.pop(episode_id, None)
        kept = self.store.snapshot(episode_id)
        if kept is not None and kept["data"].get("plan") and not kept["summary"]:
            self.store.update_episode(
                episode_id, plan=kept["data"]["plan"], labels=kept["data"]["labels"]
            )
            self.store.drop_snapshot(kept["n"])
        said += " The plan is as it was."
        self._stage(episode_id, name=stage, state="stopped", said=said)
        self._set(episode_id, status=self._status(episode_id))

    def _as_it_stands(self, episode: Row) -> Row:
        """The plan, its labels and its pictures as they stand: what a change can go back to."""
        keep = ("unit", "version", "note", "failure", *VERSION_KEEPS)
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
        if "unit_choices" in kept["data"]:
            settings_picks = dict(episode["picks"] or {})
            unit_choices = dict(settings_picks.get("units") or {})
            for uid, choice in kept["data"]["unit_choices"].items():
                if choice is None:
                    unit_choices.pop(uid, None)
                else:
                    unit_choices[uid] = choice
            self.store.update_episode(episode_id, picks={**settings_picks, "units": unit_choices})
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
            # a row kept before pictures kept their words is judged by when its lines changed
            values = {"words": "", **{k: v for k, v in row.items() if k != "unit"}}
            if values.get("status") in ("queued", "making", "posing"):
                values["sig"] = ""  # it was on its way then: it is asked for again
            self._put(episode_id, str(row["unit"]), values)

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
        was = dict(episode["stage"] or {})
        stage = {**was, **change}
        if "name" in change and change["name"] != was.get("name"):
            # when each stage began, so the plan's page times them one by one
            stage["log"] = [*(stage.get("log") or []), {"name": change["name"], "at": time.time()}]
        self.store.update_episode(episode_id, stage=stage)
        self._changed(episode_id)

    def _pulsed(self, episode_id: str, run_id: str) -> None:
        """A turn gave a sign of life between its steps: the studio is told that alone, so a
        model's long thought costs it no reading of the whole episode."""
        pulse = self.store.pulses.get(run_id)
        if pulse is not None:
            self.hub.publish("episode.pulse", id=episode_id, pulse=pulse)

    def _heard(self, episode_id: str) -> Any:
        def heard(kind: str, text: str) -> None:
            if kind == "pulse":
                self._pulsed(episode_id, text)
            if kind not in ("step", "note", "thought"):
                return
            now = time.time()
            if kind == "step":
                episode = self._episode(episode_id)
                self.store.update_episode(
                    episode_id, stage={**(episode["stage"] or {}), "said": _clean(text, 120)}
                )
            if now - self._said_at.get(episode_id, 0.0) >= 1.0:
                self._said_at[episode_id] = now
                self._changed(episode_id)

        return heard

    def _seen(self, episode_id: str) -> Any:
        """A picture's builder is at a new step: the studio hears of it, once a second at most."""

        def heard(kind: str, text: str) -> None:
            if kind == "pulse":
                self._pulsed(episode_id, text)
            now = time.time()
            told = kind in ("step", "note", "thought")
            if told and now - self._said_at.get(episode_id, 0.0) >= 1.0:
                self._said_at[episode_id] = now
                self._changed(episode_id)

        return heard

    async def _plan(self, episode_id: str, start: str, redo: str, picture: str = "") -> None:
        episode = self._episode(episode_id)
        worker = self._worker(episode)
        standing = start in STANDING
        if not standing:
            # a plan being written takes the studio's place; a change to one that stands does not
            status = "planning" if self._status(episode_id) == "plan" else episode["status"]
            self._set(episode_id, status=status)
        began = time.time()
        self._stage(
            episode_id,
            name=start,
            round=0,
            state="working",
            said="Getting ready",
            at=began,
            log=[{"name": start, "at": began}],
        )
        asked = (episode["stage"] or {}).get("asked") or {}
        unit = None
        if start == "change" and asked.get("scope") in ("line", "picture"):
            target = asked.get("target")
            unit = next(
                (
                    u
                    for u in self._units(episode, self._full(episode) or {})
                    if target in u["frames"]
                ),
                None,
            )
            if unit is not None:
                worker = self._builder(episode, unit)
        if picture:
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
            json.dumps(episode["plan"], ensure_ascii=False, indent=1)
            if episode["plan"] and start != "brief"
            else "{}"
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
            prompt = self._prompt(episode, worker, name, report, redo)
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
        if standing and not self._note_change(episode_id) and start == "change":
            # said plainly, or a person who asked is left looking for what is different
            self._stage(episode_id, said="The writer changed nothing.")
        self._set(episode_id, status=self._status(episode_id))
        self._queue_pictures(episode_id)
        if start == "redo" and episode_id in self._then_draw:
            # the picks were applied: what they left the writer is done, and the pictures follow
            self._then_draw.discard(episode_id)
            picks = dict(self._episode(episode_id)["picks"] or {})
            picks.pop("writer", None)
            self.store.update_episode(episode_id, picks=picks)
            self._refresh(episode_id)
        again = self._redraw.pop(episode_id, set())
        if start == "redo" and again:
            # planned again for their words: drawn again, whatever the writer changed
            planned = {u["id"] for u in self._units(episode, full) if u["kind"] == "picture"}
            for unit_id in again & planned:
                self._set_queued(episode_id, unit_id, sig="", failure="")
            self._set(episode_id, status=self._status(episode_id))
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
            if stage in STANDING and not isinstance(worker, DemoWorker):
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
        picks = (episode["picks"] or {}).get("units", {})
        for _, _, f in plans.frames_of(merged):
            if picks.get(f["id"], {}).get("component"):
                f["_component_picked"] = True
        # A framing turn can edit a chapter question or its narration. Refresh any
        # invalidated script labels before the final checks consume them.
        if (
            checks == "all"
            and "script" not in stages
            and (
                any(not ch.get("type") for ch in merged.get("chapters", []))
                or any(not beat.get("subtype") for _, beat in plans.beats_of(merged))
            )
        ):
            stages = ["script", *stages]
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
        musts = check.musts(episode["report"].get("rows", []))
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
            theme = layouts.theme_of({"brief": chosen})
            kit = "\n".join(
                f"- {key} ({layouts.LAY[key]['presence']}): {layouts.LAY[key]['reads_as']}"
                for key in theme["kit"]
            )
            return (
                f"Stage: frames.\n\nEvery line was read for who has the frame:\n\n{said}\n\n"
                f"Available layouts for this look:\n{kit}\n\n"
                "On each new shot, set `layout_intent` to the layout ID that fits who is "
                "on screen and what the viewer needs to see. Compose the picture for that "
                "space. For illustrated objects choose an `asset` from "
                f"{', '.join(illustrations.ASSETS)}. Set a frame's `camera` to overview, "
                "focus or reset and its `focal` to one object ID. Use `visible` for the "
                "IDs needed in this shot, including held objects. Keep a compact label in "
                "`words`. Zoom only when one detail needs inspection, then reset for the "
                "next comparison or relationship. Code fits the assets into measured slots "
                "and limits their scale, keeping labels readable. When the frame is crowded, "
                "show fewer supporting objects or choose a content-only layout. "
                "Keep the same framing on a hold unless the explanation moves to a detail. "
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
            "Stage: redo.\n\nA person changed the plan in the studio. What that leaves for "
            f"you:\n\n{redo}\n\nDo only that, in {root}/plan.json, following "
            f'{skill}/references/plan.md ("When a person changes who has the frame", "When a '
            'person changes a line\'s words" and "When a person adds or cuts a line"). Never '
            "undo a pick, and keep every `by_person` line's words. Reply with what you changed."
        )

    def _fix_prompt(self, episode: Row, worker: Worker, stage: str, report: Sequence[str]) -> str:
        root, _ = worker.place(episode)
        said = "\n".join(report)
        return (
            f"Stage: fix (the {stage} stage).\n\nYour plan was read and checked:\n\n{said}\n\n"
            f"Fix every MUST, and each look you do not waive, in {root}/plan.json. Change "
            "nothing else. Reply with what you changed."
        )

    def stop(self, episode_id: str, unit_id: str = "") -> None:
        """Stop what is under way for an episode: its plan, and every picture being made or
        waiting its turn; or, when one picture is named, that picture alone. A picture stopped
        while it was made again goes back to the version before; one stopped on its first build
        stays stopped until a person asks for it again (see `_unmade`)."""
        job = self._jobs.get(episode_id)
        if not unit_id:
            self._then_draw.discard(episode_id)
        if not unit_id and job is not None and not job.done():
            job.cancel()
        for (owner, unit), build in list(self._builds.items()):
            if owner == episode_id and unit_id in ("", unit) and not build.done():
                build.cancel()

    def again(
        self,
        episode_id: str,
        *,
        writer: str = "",
        model: str | None = None,
        effort: str | None = None,
        from_start: bool = False,
    ) -> Row:
        """Pick up planning with the chosen writer and model, carrying its prior work over."""
        episode = self._episode(episode_id)
        if self.planning(episode_id):
            raise ValueError("The writer is already planning this episode.")
        if from_start and (episode["approved"] or episode["status"] != "failed"):
            raise ValueError("Only a stopped or failed draft can restart from the source.")
        changes = {
            key: value
            for key, value in {
                "writer": writer or None,
                "writer_model": model,
                "writer_effort": effort,
            }.items()
            if value is not None
        }
        if changes:
            chosen = self._settings(changes, episode["settings"])
            self.store.update_episode(episode_id, settings=chosen)
        stage = str((episode["stage"] or {}).get("name") or "brief")
        self._start_plan(
            episode_id,
            stage=stage if not from_start and stage in ("brief", "script", "frames") else "brief",
        )
        return self.view(episode_id)

    # -- the person's side: approving, picking -------------------------------------------------

    def approve(self, episode_id: str, *, by: str) -> Row:
        episode = self._episode(episode_id)
        if self._full(episode) is None or self.planning(episode_id):
            raise ValueError("The plan isn't written yet.")
        self.store.update_episode(episode_id, approved=True, status="studio")
        self._say(episode, f"Approved the plan of “{episode['title']}”.", by=by)
        full = self._full(episode)
        for unit in self._units(episode, full or {}):
            if unit["kind"] == "picture" and self.store.picture(episode_id, unit["id"]) is None:
                self._set_queued(episode_id, unit["id"], sig="", level=unit["level"])
        self._queue_pictures(episode_id)
        self._settle(episode_id)
        return self.view(episode_id)

    def choose(self, episode_id: str, *, by: str, change: Mapping[str, Any]) -> Row:
        """A person's picks: the film's look, voice, default level and writer, who has the frame
        (for a line, a chapter or the whole film), a picture's level, and the agent that builds
        a chapter's pictures or one picture."""
        episode = self._episode(episode_id)
        if self.planning(episode_id):
            raise ValueError("The plan is being written. Pick again when it has landed.")
        before = dict(episode["settings"])
        chosen = self._settings(change.get("settings") or {}, before)
        if (change.get("settings") or {}).get("narrator"):
            self._channel_narrator(chosen, self._channel_of(episode))
        picks: Row = {
            "units": dict((episode["picks"] or {}).get("units", {})),
            "chapters": dict((episode["picks"] or {}).get("chapters", {})),
            "writer": dict((episode["picks"] or {}).get("writer", {})),
        }
        for chapter_id, picked in (change.get("builders") or {}).items():
            # who builds a chapter's pictures; nothing picked gives them back to the film's writer
            builder = str(picked or "")
            if builder and not self._can_write(builder):
                raise ValueError("That agent isn't ready on this computer.")
            picks["chapters"].pop(str(chapter_id), None)
            if builder:
                picks["chapters"][str(chapter_id)] = {"builder": builder}
        actual_units = (
            {u["id"]: u for u in self._units(episode, self._full(episode) or {})}
            if change.get("units")
            else {}
        )
        for unit_id, pick in (change.get("units") or {}).items():
            unit = actual_units.get(unit_id)
            if unit is None:
                raise ValueError("That picture is no longer in this episode.")
            kept = dict(picks["units"].get(str(unit_id)) or {})
            if pick.get("level") in LEVELS:
                kept["level"] = pick["level"]
            if "builder" in pick:
                # who builds this picture; nothing picked gives it back to the film's writer
                builder = str(pick["builder"] or "")
                if builder and not (
                    builder in self.workers
                    or any(
                        w["id"] == builder and w["ready"] for w in self.options()["picture_writers"]
                    )
                ):
                    raise ValueError("That agent isn't ready on this computer.")
                kept.pop("builder", None)
                if builder:
                    kept["builder"] = builder
            if "builder" in pick and kept.get("builder") != picks["units"].get(unit_id, {}).get(
                "builder"
            ):
                kept.pop("model", None)
                kept.pop("effort", None)
            if "component" in pick and pick["component"] != kept.get("component"):
                kept.pop("variant", None)
            for field in ("component", "variant", "direction", "model", "effort"):
                if field in pick:
                    value = (pick[field] or "").strip()
                    if value:
                        kept[field] = value
                    else:
                        kept.pop(field, None)
            options = unit["visual"]["options"]
            component = kept.get("component") or unit["visual"]["suggested"]
            if (
                component not in options
                or kept.get("variant")
                and kept["variant"] not in options[component]
            ):
                raise ValueError("That component or layout needs different scene data.")
            if len(kept.get("direction", "")) > 1600:
                raise ValueError("Keep the visual direction to 1600 characters.")
            builder = (
                kept.get("builder")
                or (picks["chapters"].get(unit["chapter"]) or {}).get("builder")
                or chosen["writer"]
            )
            if kept.get("model") or kept.get("effort"):
                episode_models.generation(self.host.settings, builder, kept)
                kept["builder"] = builder
            picks["units"][str(unit_id)] = kept
        previous_units = (episode["picks"] or {}).get("units", {})
        changed_units = {
            k: previous_units.get(k)
            for k, change_unit in (change.get("units") or {}).items()
            if {"component", "variant", "direction", "model", "effort"} & change_unit.keys()
            and previous_units.get(k) != picks["units"].get(k)
        }
        if changed_units:
            data = self._as_it_stands(episode)
            data["unit_choices"] = changed_units
            self.store.put_snapshot(episode_id, why="Changed picture generation", data=data)
            snap = self.store.snapshot(episode_id)
            if snap:
                self.store.note_snapshot(
                    snap["n"],
                    {"lines": [], "added": [], "removed": 0, "pictures": list(changed_units)},
                )
        self.store.update_episode(episode_id, settings=chosen, picks=picks)
        episode = self._episode(episode_id)
        merged = self._merged(episode)
        new: Row = {k: change[k] for k in ("frames", "chapters", "all", "clear") if change.get(k)}
        override.refuse(new)
        if chosen.get("presenter") == "off" and before.get("presenter") != "off":
            new["presenter"] = "off"
        feedback: list[Row] = []
        background_only = change.keys() == {"settings"} and (
            change.get("settings") or {}
        ).keys() <= {
            "background_color",
            "background_texture",
            "portrait",
        }
        if not background_only and any(f.get("presence") for _, _, f in plans.frames_of(merged)):
            feedback = override.apply(merged, new)
            self.store.update_episode(episode_id, labels=plans.labels_of(merged))
        left = override.redo(feedback)
        if left and not (self.demo and episode["settings"].get("writer") == DEMO):
            # What the pick leaves the writer waits for the person to apply their picks: trying
            # frames out costs nothing, and nothing is planned or drawn until they say so.
            for item in left:
                picks["writer"][str(item["where"])] = item
            self.store.update_episode(episode_id, picks=picks)
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

    def line_history(self, episode_id: str, frame: str) -> Row:
        current = _history_fields(self._episode(episode_id)["plan"] or {}, frame).get(frame)
        if current is None:
            raise KeyError(frame)
        entries = []
        for record in self.store.previous_plans(episode_id):
            previous = _history_fields(record["plan"], frame).get(frame, {})
            changes = [
                {"label": key, "before": previous.get(key, ""), "after": current.get(key, "")}
                for key in dict.fromkeys([*previous, *current])
                if previous.get(key, "") != current.get(key, "")
            ]
            if changes:
                entries.append(
                    {
                        "id": record["n"],
                        "at": record["at"],
                        "reason": record["why"],
                        "changes": changes,
                    }
                )
            current = previous
        return {"entries": entries}

    def edit(self, episode_id: str, *, by: str, frame: str, text: str) -> Row:
        """A person's own words for one line. They are in at once: nothing is read again and
        nothing is drawn again. Only when a step of the line's picture landed on a word that
        is gone does the writer fit that step to the new words."""
        words = _line_words(text)
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
        self._fit_later(episode_id, [frame], self._report(episode_id))
        self._say(episode, "Changed a line's words.", by=by, quiet=True)
        self._queue_pictures(episode_id)
        self._settle(episode_id)
        return self.view(episode_id)

    def add_line(
        self,
        episode_id: str,
        *,
        by: str,
        after: str,
        text: str,
        kind: str,
        keep: str | None = None,
    ) -> Row:
        """A person adds a line to a chapter's script, after the line `after` (or first in the
        chapter it names). `more` goes on in that line's block: to camera after a line said to
        camera, over the same picture after a picture's line. `camera` starts a block said to
        camera, and a picture type a block whose line brings that picture in. `keep` is the
        line's own words up to where it was split, when the new line is the rest of it.

        The words are the person's and so is what the line is: it is labelled as they chose,
        and nothing is read again. A line said to camera is ready at once. A new picture waits
        for the writer to design it, and a picture that gained a line is out of date: both
        wait for the person to apply their changes."""
        words = _line_words(text)
        if kind not in LINE_KINDS:
            raise ValueError(
                "A line goes on in its block, is said to camera, or brings in a picture."
            )
        episode = self._episode(episode_id)
        full = self._full(episode)
        if full is None or self.planning(episode_id):
            raise ValueError("The writer is still working. Add the line when that has landed.")
        order = [f for _, _, f in plans.frames_of(full)]
        opens = next((ch for ch in full["chapters"] if ch["id"] == after), None)
        prev: Row | None
        nxt: Row | None
        if opens is not None:
            first = opens["beats"][0]["frames"][0]["id"]
            at = next(k for k, f in enumerate(order) if f["id"] == first)
            prev, nxt = (order[at - 1] if at else None), order[at]
            if kind == "more" or keep is not None:
                raise ValueError("A line goes on after another line.")
        else:
            at = next((k for k, f in enumerate(order) if f["id"] == after), -1)
            if at < 0:
                raise ValueError("That line is not in the plan.")
            prev, nxt = order[at], (order[at + 1] if at + 1 < len(order) else None)
        hold = False
        if kind == "more":
            assert prev is not None  # noqa: S101 - a line goes on after one, checked above
            if prev.get("presence") == "person":
                kind = "camera"
            else:
                hold = True
        elif nxt is not None and nxt.get("hold") and nxt.get("presence") != "person":
            raise ValueError("A new block goes after a picture's last line, not inside it.")
        if kind == "camera" and full.get("brief", {}).get("presenter") == "off":
            raise ValueError(
                "Nobody is on camera in this film: a new line here brings in a picture."
            )
        now = time.time()
        before = episode["plan"] or {}
        plan = copy.deepcopy(before)
        if keep is not None:
            plans.reword(plan, after, _line_words(keep), at=now)
        fid = plans.add_line(plan, after, words, at=now, hold=hold)
        labels = plans.carried(episode["labels"] or {}, before, plan)
        merged = self._merged({**episode, "plan": plan, "labels": labels})
        new_ch, new_b, line = next(
            (ch, b, f) for ch, b, f in plans.frames_of(merged) if f["id"] == fid
        )
        if not new_b.get("subtype"):
            # what the beat does is what the beat before it does (or the one after, first in
            # its chapter), and it is the person's
            beats = new_ch["beats"]
            here = next(k for k, b in enumerate(beats) if b is new_b)
            like = next(
                (b for b in [*reversed(beats[:here]), *beats[here + 1 :]] if b.get("subtype")),
                None,
            )
            if like is not None:
                new_b.update(
                    subtype=like["subtype"],
                    type=like.get("type"),
                    p=1.0,
                    reads=[{"id": like["subtype"], "p": 1.0}],
                    by="person",
                )
        if hold:
            assert prev is not None  # noqa: S101 - a held line goes on after one
            line["presence_p"] = dict(prev.get("presence_p") or {str(prev["presence"]): 1.0})
        elif kind == "camera":
            line["presence_p"] = {"person": 1.0, "both": 0.0, "content": 0.0}
        else:
            line["presence_p"] = {"person": 0.0, "both": 1.0, "content": 0.0}
            merged["_overrides"] = override.merge(
                merged.get("_overrides") or {}, {"frames": {fid: {"picture": kind}}}
            )
            line["picked"] = {"picture": kind}
        layouts.settle_frames(merged)
        plans.inherit_holds(merged)
        if kind == "camera" or hold:
            line["_designed"] = True  # nothing is drawn for it: what it is, is all it needs
            if kind == "camera":
                line["picture"] = "camera"
        _follow(merged, [fid, str(nxt["id"]) if nxt is not None else ""])
        self._snapshot(episode_id, why="You added a line", episode=episode)
        self.store.update_episode(episode_id, plan=plan, labels=plans.labels_of(merged))
        if kind in override.PICTURES:
            picks = dict(episode["picks"] or {})
            writer = dict(picks.get("writer") or {})
            writer[fid] = {
                "where": fid,
                "kind": "added",
                "was": "a new line",
                "now": f"{line['presence']} / {line['layout']}",
                "why": "added by a person",
                "do": f"A person added this line with a picture: {KINDS[kind]['name']} "
                f"({KINDS[kind]['reads_as'].rstrip('.')}). Write its `shows`, objects and cues "
                "for its words, as at the frames stage, and keep its words as they are.",
            }
            picks["writer"] = writer
            self.store.update_episode(episode_id, picks=picks)
        self._note_change(episode_id)
        self._fit_later(episode_id, [after] if keep is not None else [], self._report(episode_id))
        self._say(episode, "Added a line.", by=by, quiet=True)
        self._queue_pictures(episode_id)
        self._settle(episode_id)
        return self.view(episode_id)

    def cut_lines(
        self,
        episode_id: str,
        *,
        by: str,
        frames: Sequence[str],
        join: bool = False,
        words: str | None = None,
    ) -> Row:
        """A person cuts lines from a chapter's script: one, or the run of a block. With
        `join`, the one line's words go on at the end of the line before it in its block, as
        the start of a paragraph is deleted in a text; `words` are what that line then says,
        when the person changed it too. A picture that loses a line is out of date and one that
        loses all of them goes with them: nothing is drawn until the person applies their
        changes."""
        cut = list(dict.fromkeys(str(x) for x in frames))
        if not cut:
            raise ValueError("Say which line to cut.")
        episode = self._episode(episode_id)
        full = self._full(episode)
        if full is None or self.planning(episode_id):
            raise ValueError("The writer is still working. Cut the line when that has landed.")
        order = [(ch, f) for ch, _b, f in plans.frames_of(full)]
        where = {str(f["id"]): k for k, (_ch, f) in enumerate(order)}
        if any(x not in where for x in cut):
            raise ValueError("That line is not in the plan.")
        for ch in full["chapters"]:
            ids = [f["id"] for b in ch["beats"] for f in b["frames"]]
            if ids and all(x in cut for x in ids):
                raise ValueError(
                    "A chapter needs a line. To drop the chapter, ask for it to be cut."
                )
        found = self._units(episode, full)
        for unit in found:
            if unit["kind"] != "picture":
                continue
            if unit["frames"][0] in cut and not all(x in cut for x in unit["frames"]):
                raise ValueError(
                    "This line brings its picture in for the lines after it: cut them with it, or keep it."
                )
            running = self._builds.get((episode_id, unit["id"]))
            if running is not None and not running.done() and any(x in cut for x in unit["frames"]):
                raise ValueError("Its picture is being made. Stop it first, or wait for it.")
        now = time.time()
        before = episode["plan"] or {}
        plan = copy.deepcopy(before)
        into = ""
        if join:
            k = where[cut[0]]
            ch, gone = order[k]
            had_ch, had = order[k - 1] if k else (None, None)
            block = units.by_frame(found)
            mine, theirs = block.get(str(gone["id"])), block.get(str((had or {}).get("id")))
            if (
                len(cut) != 1
                or had is None
                or had_ch is None
                or had_ch["id"] != ch["id"]
                or (mine or {}).get("id") != (theirs or {}).get("id")
                or (mine is None and not gone.get("presence") == had.get("presence") == "person")
            ):
                raise ValueError("A line joins the line before it in its block.")
            into = str(had["id"])
            joined = words or f"{str(had.get('vo', '')).strip()} {str(gone.get('vo', '')).strip()}"
            plans.reword(plan, into, _line_words(joined), at=now)
        for x in cut:
            plans.cut_line(plan, x)
        labels = plans.carried(episode["labels"] or {}, before, plan)
        merged = self._merged({**episode, "plan": plan, "labels": labels})
        layouts.settle_frames(merged)
        plans.inherit_holds(merged)
        # the line after each cut follows another line now
        after_cut = [
            str(f["id"])
            for k, (_ch, f) in enumerate(order)
            if str(f["id"]) not in cut and k and str(order[k - 1][1]["id"]) in cut
        ]
        _follow(merged, after_cut)
        labels = plans.labels_of(merged)
        # the lines take their picks, and what they waited on, with them
        frames_picked = dict((labels.get("overrides") or {}).get("frames") or {})
        for x in cut:
            frames_picked.pop(x, None)
        labels["overrides"] = {**(labels.get("overrides") or {}), "frames": frames_picked}
        picks = dict(episode["picks"] or {})
        for key in ("writer", "units"):
            picks[key] = {k: v for k, v in (picks.get(key) or {}).items() if k not in cut}
        self._snapshot(
            episode_id, why="You joined two lines" if join else "You cut a line", episode=episode
        )
        self.store.update_episode(episode_id, plan=plan, labels=labels, picks=picks)
        self._note_change(episode_id)
        self._fit_later(episode_id, [into] if into else [], self._report(episode_id))
        self._say(episode, "Joined two lines." if join else "Cut a line.", by=by, quiet=True)
        self._queue_pictures(episode_id)
        self._settle(episode_id)
        return self.view(episode_id)

    def keep_picture(self, episode_id: str, unit_id: str, *, by: str) -> Row:
        """A person says a picture made for other words still fits: it is kept for the words
        its lines say now, and nothing runs."""
        episode = self._episode(episode_id)
        full = self._full(episode)
        unit = next(
            (u for u in self._units(episode, full or {}) if u["id"] == unit_id and full), None
        )
        have = self.store.picture(episode_id, unit_id)
        if unit is None or have is None or have["status"] not in ("made", "go"):
            raise ValueError("There is no made picture there.")
        self.store.set_picture(episode_id, unit_id, words=unit["words_now"])
        self._say(episode, "Kept a picture for the new words.", by=by, quiet=True)
        self._changed(episode_id)
        return self.view(episode_id)

    def use_version(self, episode_id: str, unit_id: str, n: int, *, by: str) -> Row:
        """A person puts a kept version of a picture back: it stands again as it was made, and
        the one that stood is kept in its place. A build under way for it is stopped, which the
        press says. The beat's level follows the version's, so it does not read as out of date
        for being made another way. Nothing is drawn."""
        episode = self._episode(episode_id)
        have = self.store.picture(episode_id, unit_id)
        chosen = next((k for k in (have or {}).get("versions") or [] if k["n"] == n), None)
        if chosen is None:
            raise ValueError("That version isn't kept any more.")
        build = self._builds.get((episode_id, unit_id))
        if build is not None and not build.done():
            build.cancel()  # its stop lands on a settled picture and leaves it (`_unmade`)
        full = self._full(episode)
        unit = (
            next((u for u in self._units(episode, full) if u["id"] == unit_id), None)
            if full
            else None
        )
        if unit is not None and chosen["level"] and chosen["level"] != unit["level"]:
            picks = dict(episode["picks"] or {})
            picked = dict(picks.get("units") or {})
            picked[unit_id] = {**(picked.get(unit_id) or {}), "level": chosen["level"]}
            self.store.update_episode(episode_id, picks={**picks, "units": picked})
        self._put(episode_id, unit_id, {**_standing(chosen), "failure": "", "note": ""})
        self._say(episode, f"Put version {n} of a picture back.", by=by, quiet=True)
        self._settle(episode_id)
        return self.view(episode_id)

    def replan(self, episode_id: str, *, by: str, pictures: Sequence[str]) -> Row:
        """Have the writer fit pictures to what their lines say now: a person changed the
        words after the pictures were made. What each shows, its objects and its cues are
        planned again for the new words (the words stay as they are), and each is then drawn
        again. Asked for by name, so it runs at once."""
        episode = self._episode(episode_id)
        full = self._full(episode)
        if full is None or self.planning(episode_id):
            raise ValueError("The writer is still working. Ask again when that has landed.")
        found = {u["id"]: u for u in self._units(episode, full) if u["kind"] == "picture"}
        named = list(dict.fromkeys(str(p) for p in pictures))
        if not named or any(p not in found for p in named):
            raise ValueError("There is no picture there to plan again.")
        for unit_id in named:
            running = self._builds.get((episode_id, unit_id))
            if running is not None and not running.done():
                raise ValueError("It's being made. Stop it first, or wait for it.")
        told = "\n".join(
            f"- {unit_id} (its lines {', '.join(found[unit_id]['frames'])}): a person changed "
            "the words of this picture's lines, and they are marked `by_person`. Fit what the "
            "picture shows, its objects and its cues to what the lines say now, as at the "
            "frames stage, and keep every word as it is."
            for unit_id in named
        )
        self._snapshot(episode_id, why="Planned pictures for your words")
        self._redraw.setdefault(episode_id, set()).update(named)
        self._start_plan(episode_id, stage="redo", redo=told)
        self._say(episode, "Asked for pictures to be planned again.", by=by, quiet=True)
        self._settle(episode_id)
        return self.view(episode_id)

    def _report(self, episode_id: str) -> list[Row]:
        """The plan checked as it stands after a person's change, kept as its report."""
        merged = self._merged(self._episode(episode_id))
        rows = check.check(merged, "all")
        self.store.update_episode(
            episode_id,
            report={"rows": rows, "lines": check.lines(rows, "all", merged), "at": time.time()},
        )
        return rows

    def _fit_later(self, episode_id: str, frames: Sequence[str], rows: list[Row]) -> None:
        """A line whose words a person changed, where a step of its picture lands on a word
        that is gone: the writer fits that step to the new words, once the person applies
        their changes. The demo's writer fits nothing."""
        musts = {str(r["where"]) for r in check.musts(rows)}
        wrong = [f for f in frames if f and f in musts]
        if not wrong or (self.demo and self._episode(episode_id)["settings"].get("writer") == DEMO):
            return
        picks = dict(self._episode(episode_id)["picks"] or {})
        writer = dict(picks.get("writer") or {})
        for frame in wrong:
            writer[frame] = {
                "where": frame,
                "kind": "words",
                "do": "A person changed its words (it is marked `by_person`), and a step of its "
                "picture lands on a word that is gone: fit its cues to the new words (the word "
                "each lands on, or the cue itself), and keep the words exactly as they are.",
            }
        picks["writer"] = writer
        self.store.update_episode(episode_id, picks=picks)

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
        if "unit_choices" in kept["data"]:
            current = (episode["picks"] or {}).get("units") or {}
            left["unit_choices"] = {k: current.get(k) for k in kept["data"]["unit_choices"]}
        if kept["data"].get("picked"):
            left["picked"] = kept["data"]["picked"]
        self._go_to(episode_id, kept)
        restored = self._merged(self._episode(episode_id))
        self._fit_later(
            episode_id,
            [f["id"] for _, _, f in plans.frames_of(restored) if f.get("by_person")],
            self._report(episode_id),
        )
        self.store.turn_snapshot(kept["n"], kind="undone" if back else "before", data=left)
        self._stage(episode_id, name="done", state="done", said="", asked=None)
        said = "Took the last change back." if back else "Put the change back."
        self._say(episode, said, by=by, quiet=True)
        self._queue_pictures(episode_id)
        self._settle(episode_id)
        return self.view(episode_id)

    # -- pictures: built by the writer, posed on the thread's computer -------------------------

    def _queue_pictures(
        self, episode_id: str, *, generation_for: Mapping[str, Row] | None = None
    ) -> None:
        """Start the pictures that were asked for and wait their turn (a row that says
        "queued"). Nothing starts a picture by itself: one whose plan changed after it was made
        stays as it is, out of date, until a person applies their changes or asks for it again."""
        episode = self._episode(episode_id)
        full = self._full(episode)
        if full is None or self._closing:
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
            running = self._builds.get((episode_id, unit["id"]))
            if have is None or have["status"] != "queued":
                continue
            if running is not None and not running.done():
                continue
            self._set_queued(
                episode_id,
                unit["id"],
                failure="",
                sig=unit["sig"],
                level=unit["level"],
            )
            self._asked[(episode_id, unit["id"])] = time.time()
            self._builds[(episode_id, unit["id"])] = asyncio.get_running_loop().create_task(
                self._built(episode_id, unit["id"], (generation_for or {}).get(unit["id"])),
                name=f"picture {episode_id} {unit['id']}",
            )
        self._changed(episode_id)

    def _waiting(self, episode: Row, full: Row | None) -> list[Row]:
        """What a person's picks leave the writer that it has not done yet: a line that now
        needs a picture, a picture that has to go, a line nobody is left to say. Each waits for
        the person to apply their picks; one whose pick was taken back or done is dropped."""
        items = (episode["picks"] or {}).get("writer") or {}
        if not items or full is None:
            return []
        frames = {f["id"]: f for _, _, f in plans.frames_of(full)}
        off = full.get("brief", {}).get("presenter") == "off"
        musts = {str(r["where"]) for r in check.musts((episode["report"] or {}).get("rows") or [])}
        out: list[Row] = []
        for where, item in items.items():
            frame = frames.get(str(where))
            if item.get("kind") == "words":
                if frame is not None and str(where) in musts:
                    out.append(item)  # a step still lands on a word that is gone
                continue
            if frame is None:
                if off:  # a line written for a face, with no one left on screen
                    out.append(item)
                continue
            presence = frame.get("presence")
            if presence != str(item.get("now", "")).split(" / ")[0]:
                continue  # the pick was taken back, or another replaced it
            if presence != "person" and (frame.get("shows") or frame.get("hold")):
                continue  # the line has its picture
            if presence == "person" and not override.has_picture(frame):
                continue  # its picture has gone
            out.append(item)
        return out

    def apply(self, episode_id: str, *, by: str) -> Row:
        """Run what a person's picks and changes wait on, which nothing starts by itself: the
        writer plans what the picks leave it (a line that now needs a picture), then the
        pictures that are out of date are drawn again, and once the plan is approved the ones
        the changes added are made. A picture that failed waits for its own Try again."""
        episode = self._episode(episode_id)
        full = self._full(episode)
        if full is None or self.planning(episode_id):
            raise ValueError("The writer is still working. Apply when that has landed.")
        left = self._waiting(episode, full)
        if left:
            told = "\n".join(
                f"- {x['where']}: {x['do']}"
                if x.get("kind") == "words"
                else f"- {x['where']}: {x['was']} is now {x['now']}. {x['do']}"
                for x in left
            )
            self._snapshot(episode_id, why="Planned what your changes need")
            self._then_draw.add(episode_id)
            self._start_plan(episode_id, stage="redo", redo=told)
        elif not self._refresh(episode_id):
            raise ValueError("Nothing is waiting: every picture asked for is up to date.")
        self._say(episode, "Applied the changes.", by=by, quiet=True)
        self._settle(episode_id)
        return self.view(episode_id)

    def _refresh(self, episode_id: str) -> int:
        """Ask again for every picture that is out of date, and once the plan is approved for
        every one its changes added. Returns how many were asked for."""
        episode = self._episode(episode_id)
        full = self._full(episode)
        if full is None:
            return 0
        asked = 0
        for unit in self._units(episode, full):
            if unit["kind"] != "picture":
                continue
            running = self._builds.get((episode_id, unit["id"]))
            if running is not None and not running.done():
                continue
            have = self.store.picture(episode_id, unit["id"])
            if (have is None and episode["approved"]) or (
                have is not None and _outdated(have, unit)
            ):
                self._set_queued(episode_id, unit["id"], sig="", failure="", level=unit["level"])
                asked += 1
        if asked:
            self._set(episode_id, status=self._status(episode_id))
            self._queue_pictures(episode_id)
        return asked

    async def _built(
        self, episode_id: str, unit_id: str, generation_pick: Row | None = None
    ) -> None:
        episode = self._episode(episode_id)
        unit = next(
            (u for u in self._units(episode, self._full(episode) or {}) if u["id"] == unit_id),
            None,
        )
        builder = str(
            (generation_pick or unit or {}).get("builder")
            or episode["settings"].get("writer")
            or ""
        )
        at_once = 1 if builder == BUILTIN else PICTURES_AT_ONCE
        gate = self._gates.setdefault(f"{episode_id}:{builder}", asyncio.Semaphore(at_once))
        in_house = 1 if builder == BUILTIN else HOUSE_AT_ONCE
        house = self._house.setdefault(builder, asyncio.Semaphore(in_house))
        try:
            # Its episode's turn first, so a picture waiting for that holds no place in the
            # house's. Each gate lets in whoever asked first, and one stopped while it waits
            # leaves the line.
            async with gate, house:
                await self._build(episode_id, unit_id, generation_pick=generation_pick)
        except asyncio.CancelledError:
            self._unmade(episode_id, unit_id, "Stopped.", stopped=True)
        except Exception as error:  # one picture failing must not stop the others
            _LOGGER.exception("picture failed on %s %s", episode_id, unit_id)
            self._unmade(episode_id, unit_id, _clean(str(error), 240))
        finally:
            self._record_timing(episode_id, unit_id)
            self._builds.pop((episode_id, unit_id), None)
            self._asked.pop((episode_id, unit_id), None)
            self._steer.pop((episode_id, unit_id), None)
            self._last_turn.discard((episode_id, unit_id))
            self._settle(episode_id)
            # a pick made while it was building asks for it again
            with contextlib.suppress(KeyError, RuntimeError):
                self._queue_pictures(episode_id)

    async def _build(
        self, episode_id: str, unit_id: str, note: str = "", *, generation_pick: Row | None = None
    ) -> None:
        episode = self._episode(episode_id)
        full = self._full(episode)
        unit = next((u for u in self._units(episode, full or {}) if u["id"] == unit_id), None)
        if full is None or unit is None:
            return
        key = (episode_id, unit_id)
        self._began[key] = time.time()
        self._steered.pop(key, None)
        self._last_turn.discard(key)
        if generation_pick is not None:
            unit = {**unit, **generation_pick}
        worker = self._builder(episode, unit)
        if isinstance(worker, DemoWorker) and unit["visual"]["direction"]:
            raise ValueError("Select a live provider to generate from a custom description.")
        comp = picture.composition_id(unit_id)
        look = self._look(episode)
        level = unit["level"]
        brief = picture.brief(unit, full, look=look, note=note)
        root, skill = worker.place(episode)
        self.store.set_picture(
            episode_id,
            unit_id,
            status="making",
            sig=unit["sig"],
            failure="",
            level=level,
            builder=worker.id,
            motion={},
            # dated on the beat's record, so its clock holds across a restart
            timing={"started_at": self._began[key]},
        )
        self._changed(episode_id)
        brief_file = f"pictures/{comp}.brief.json"
        await worker.prepare(episode, {brief_file: json.dumps(brief, indent=1, ensure_ascii=False)})
        planned = ""
        if level == units.RICH:
            motion = await self._motion(episode_id, unit, worker, note, brief)
            # the plan rides in the brief, so a builder with no memory of writing it has it too
            brief = picture.brief(unit, full, look=look, note=note, planned=motion)
            await worker.prepare(
                episode, {brief_file: json.dumps(brief, indent=1, ensure_ascii=False)}
            )
            planned = " Its `motion_plan` is the plan this picture is built to, shot by shot."
        starter = f"pictures/{comp}.starter.html"
        seed = sketch.built(brief)
        illustrated = "data-illustration" in seed
        if not isinstance(worker, DemoWorker):
            await worker.prepare(
                episode, {starter: seed, str(brief["file"]): seed if illustrated else ""}
            )
        edit = (
            f" Edit the existing {brief['file']} in place. Keep its template, clock and timeline. "
            f"For an unfamiliar illustrated object, add its 128×128 inline SVG group to "
            f'<defs id="{comp}-local-artwork"> using data-episode-object with the planned object ID. '
            "The starter places and animates that group automatically."
            if illustrated
            else ""
        )
        prompt = (
            f"Stage: picture.\n\nBuild one picture of the episode. Your folder is {root}. Read "
            f"{skill}/briefs/picture.md and the HyperFrames guides it names in "
            f"{_guides(skill)}/, then the brief at {root}/{brief_file}, "
            f"and adapt the themed starting scene at {root}/{starter}. Write {root}/{brief['file']}.{edit}{planned} Deliver nothing: the house reads the "
            "file from your folder." + (f"\n\nThe person's note on it: {note}" if note else "")
        )
        html = ""
        faults: list[str] = []
        stills: dict[str, str] = {}
        for attempt in range(PICTURE_TRIES):
            told: Told = await worker.turn(
                self._episode(episode_id),
                lane=f"picture:{unit_id}",
                prompt=self._with_notes(episode_id, unit_id, "draw", prompt),
                heard=self._seen(episode_id),
            )
            if told.stopped:
                raise asyncio.CancelledError
            if told.failure:
                raise ValueError(told.failure)
            html = await worker.read(self._episode(episode_id), str(brief["file"])) or ""
            faults = (
                picture.faults(html, unit, full, look) + sketch.artwork_faults(html, brief)
                if html
                else [f"{brief['file']} was not written"]
            )
            if not faults:
                # a clip rendered for what was drawn before no longer plays this picture
                self.store.set_picture(episode_id, unit_id, status="posing", html=html, clip="")
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
                f"Use the brief at {root}/{brief_file}. Change only what these name, and reply with what you changed."
            )
        layout_source = "brief" if illustrated and html == seed else "writer"
        if faults and not isinstance(worker, DemoWorker):
            layout_source = "brief"
            # An invalid drawing never gets published. Try the cue-driven layout from this brief.
            html = seed
            faults = picture.faults(html, unit, full, look) + sketch.artwork_faults(html, brief)
            if not faults:
                faults, stills = await asyncio.to_thread(
                    self._pose, episode, unit, full, html, False
                )
            if not faults:
                await worker.prepare(episode, {str(brief["file"]): html})
        if faults:
            self._unmade(episode_id, unit_id, "; ".join(faults[:3]), html=html)
            return
        generation = {
            **unit["generation"],
            "theme_sig": unit["theme_sig"],
            "catalog_version": catalog.CATALOG_VERSION,
            "drawing_version": catalog.DRAWING_VERSION,
            "layout_source": layout_source,
            "clip_lines": picture.clock(unit, timeline.schedule(full))["lines"],
        }
        if isinstance(worker, LocalWorker):
            if worker.reported_model:
                generation["model"] = episode_models.named(worker.id, worker.reported_model)
            if worker.reported_effort:
                generation["effort"] = worker.reported_effort
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
            generation=generation,
            words=unit["words_now"],
        )
        self._changed(episode_id)
        clip = await asyncio.to_thread(self._clip, episode, unit)
        if clip:
            self.store.set_picture(episode_id, unit_id, clip=clip)

    async def _motion(
        self, episode_id: str, unit: Row, worker: Worker, note: str, brief: Row
    ) -> Row:
        """A rich picture's motion plan, written by its builder before anything is drawn: for
        each line, what the picture opens on, the one move the line is about, how the rest
        lands, and what the line's still shows. Code holds it to its shape and keeps it, and
        the studio shows it while the picture is drawn. Invalid output gets one correction
        before the shot sheet derived from the brief is used."""
        unit_id = str(unit["id"])
        episode = self._episode(episode_id)
        root, skill = worker.place(episode)
        comp = picture.composition_id(unit_id)
        file = picture.motion_file(unit_id)
        starter = json.dumps(picture.brief_motion(brief), ensure_ascii=False)
        contract = f"Keep these exact frame IDs and JSON fields. Adapt this shot sheet to the brief:\n{starter}"
        # a plan left from an earlier build is not this one's
        await worker.prepare(episode, {file: ""})
        prompt = (
            f"Stage: motion plan.\n\nPlan how one picture of the episode moves, before anything "
            f"is drawn. Your folder is {root}. Read {skill}/briefs/motion.md and the HyperFrames "
            f"guides it names in {_guides(skill)}/, then the brief at "
            f"{root}/pictures/{comp}.brief.json, and write {root}/{file}. Write no HTML in this "
            f"turn. {contract}" + (f"\n\nThe person's note on the picture: {note}" if note else "")
        )
        faults: list[str] = []
        for _ in range(MOTION_TRIES):
            told = await worker.turn(
                self._episode(episode_id),
                lane=f"picture:{unit_id}",
                prompt=self._with_notes(episode_id, unit_id, "motion", prompt),
                heard=self._seen(episode_id),
            )
            if told.stopped:
                raise asyncio.CancelledError
            if told.failure:
                raise ValueError(told.failure)
            text = (await worker.read(self._episode(episode_id), file) or "").strip()
            plan, faults = (
                picture.motion_plan(text, unit) if text else ({}, [f"{file} was not written"])
            )
            if not faults:
                self.store.set_picture(episode_id, unit_id, motion=plan)
                self._changed(episode_id)
                return plan
            listed = "\n".join(f"- {f}" for f in faults[:12])
            prompt = (
                f"Stage: motion plan.\n\n{root}/{file} can't be used yet:\n\n{listed}\n\n"
                f"Read {root}/pictures/{comp}.brief.json and write {root}/{file}. {contract}"
            )
        # The writer completed its turns but its output did not match the file contract.
        plan, faults = picture.motion_plan(starter, unit)
        if faults:
            raise ValueError("The brief could not supply a shot sheet: " + "; ".join(faults[:3]))
        await worker.prepare(episode, {file: json.dumps(plan, ensure_ascii=False)})
        self.store.set_picture(episode_id, unit_id, motion=plan)
        self._changed(episode_id)
        return plan

    async def _looked(
        self, episode_id: str, unit: Row, full: Row, brief: Row, html: str, stills: dict[str, str]
    ) -> tuple[str, dict[str, str]]:
        """A rich picture's builder reviews it once as a first-time viewer would see it, and
        fixes what it finds: its stills (what only a render shows: an overlap, a label cut off,
        something under the person's window), frames from inside its moves and its quiet
        stretches, and what the renderer's craft pass measured. A fix that breaks the file is
        dropped; the picture it had stands."""
        episode = self._episode(episode_id)
        worker = self._builder(episode, unit)
        root, skill = worker.place(episode)
        comp = brief["composition_id"]
        images: dict[str, bytes] = {}
        for n, frame_id in enumerate(unit["frames"], start=1):
            row = self.store.file(stills.get(frame_id, ""))
            if row is not None:
                images[f"pictures/{comp}.stills/{n}.png"] = self.host.blobs.read(row)
        if not images:
            return html, stills
        moving = await asyncio.to_thread(self._motion_frames, episode, unit, full, html)
        images.update({f"pictures/{comp}.motion/{name}.png": data for name, data in moving.items()})
        measured = self._craft.pop((episode_id, str(unit["id"])), [])
        await worker.show(episode, images)
        frames = (
            f" In {root}/pictures/{comp}.motion/ are frames from inside its moves and from the "
            "middle of its quiet stretches, in the order they play, each named by its line "
            "and what it shows (a cue moving, the same cue landed, a quiet stretch)."
            if moving
            else ""
        )
        notes = (
            "\n\nWhat the renderer measured:\n" + "\n".join(f"- {note}" for note in measured)
            if measured
            else ""
        )
        told = await worker.turn(
            episode,
            lane=f"picture:{unit['id']}",
            prompt=self._with_notes(
                episode_id,
                str(unit["id"]),
                "review",
                f"Stage: picture.\n\nLook at how {root}/{brief['file']} came out, as someone "
                "seeing it once at full speed will. Its stills, one taken at the end of each "
                f"line, in line order, are in {root}/pictures/{comp}.stills/.{frames} Open "
                f"every one and review them the way {_guides(skill)}/review.md says "
                f"({skill}/briefs/picture.md, “Reviewing it”). Fix what breaks the read and "
                "what weakens the picture, in the file, and nothing else. If it holds up, "
                f"change nothing and reply “Nothing to change.”{notes}",
            ),
            heard=self._seen(episode_id),
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

    def _motion_frames(self, episode: Row, unit: Row, full: Row, html: str) -> dict[str, bytes]:
        """Frames from inside a posed picture's moves and its quiet stretches, by name, for its
        builder's review (`picture.motion_times`). The stills are what a person approves; these
        show how it gets there. Nothing here can stop a picture: with no frames, the review
        goes on by the stills alone."""
        try:
            own = picture.clock(unit, timeline.schedule(full))
            wanted = picture.motion_times(own)
            if not wanted:
                return {}
            computer = self._ready(episode)
            folder = self._pose_dir(episode, unit)
            look = self._look(episode)
            files = picture.stage_files(
                unit, own, picture.dressed(html, own, look), ground=look.palette["ground"]
            )
            computer.put(
                [(f"{folder}/{path}", content.encode()) for path, content in files.items()]
            )
            times = ",".join(f"{at:.3f}".rstrip("0").rstrip(".") for _, at in wanted)
            computer.run(
                f"cd {folder} && cp -n {GSAP} gsap.min.js; rm -rf motion; "
                f"hyperframes snapshot . --at {times} --no-end --keep -o motion --describe false "
                "2>&1 | tail -3",
                timeout=600,
            )
            found: dict[str, bytes] = {}
            for name, at in wanted:
                still = computer.get(
                    f"{folder}/motion/at-{f'{at:.3f}'.rstrip('0').rstrip('.')}s.png"
                )
                if still:
                    found[name] = still
            return found
        except Exception:  # the review goes on by the stills alone
            _LOGGER.exception("no motion frames for %s", unit.get("id"))
            return {}

    def _pose_dir(self, episode: Row, unit: Row) -> str:
        return f"{PROJECTS}/{episode['id']}/pose/{picture.composition_id(unit['id'])}"

    def _label_faults(
        self, computer: Computer, folder: str, unit: Row, own: Row, dressed: str
    ) -> list[str]:
        folder = f"{folder}-measure"
        check = Path(picture.__file__).with_name("check_labels.js").read_bytes()
        if "data-illustration" in dressed:
            computer.put([(f"{folder}/{illustrations.FILENAME}", illustrations.library().encode())])
        computer.put(
            [
                (f"{folder}/check-labels.js", check),
                (f"{folder}/check-labels.html", picture.label_probe(dressed, unit, own).encode()),
            ]
        )
        result = computer.run(
            f"cd {folder} && cp -n {GSAP} gsap.min.js && chrome-headless-shell --no-sandbox "
            f"--window-size={int(unit['canvas'][0])},{int(unit['canvas'][1])} "
            "--disable-gpu --disable-dev-shm-usage --virtual-time-budget=1500 "
            '--dump-dom "file://$PWD/check-labels.html" 2>/dev/null | tail -c 10000',
            timeout=45,
        )
        report = re.search(r"<body[^>]*>LABEL_REPORT=([^<]*)</body>", result.output)
        if not report:
            return [
                "The picture could not be measured in Chromium. Check its initialization and timeline."
            ]
        findings = json.loads(unquote(report[1]))
        if not isinstance(findings, list) or not all(isinstance(f, str) for f in findings):
            return ["The label check returned an invalid report."]
        return findings[:12]

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
        dressed = picture.dressed(html, own, look)
        label_faults = self._label_faults(computer, folder, unit, own, dressed)
        if label_faults:
            return label_faults, {}
        files = picture.stage_files(unit, own, dressed, ground=look.palette["ground"])
        computer.put([(f"{folder}/{path}", content.encode()) for path, content in files.items()])
        times = picture.still_times(own)
        wanted = ",".join(f"{t:.3f}".rstrip("0").rstrip(".") for t in times.values())
        ran = computer.run(
            f"cd {folder} && cp -n {GSAP} gsap.min.js; rm -rf stills; "
            f"hyperframes check . 2>&1 | tail -160; echo ---; "
            f"hyperframes snapshot . --at {wanted} --no-end --keep -o stills --describe false "
            "2>&1 | tail -5; ls stills 2>/dev/null",
            timeout=600,
        )
        report = ran.output.split("---", 1)[0]
        self._craft[(str(episode["id"]), str(unit["id"]))] = _craft_notes(report)
        broken, flagged = _findings(report)
        if broken or (strict and flagged) or any(f.startswith("layout:") for f in flagged):
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
        have = self.store.picture(str(episode["id"]), str(unit["id"]))
        full = self._full(episode)
        if not have or not have["html"] or not full:
            return ""
        # A rejected last revision may still occupy the staging folder. Render the accepted HTML.
        comp = picture.composition_id(unit["id"])
        own = picture.clock(unit, timeline.schedule(full))
        computer.put(
            [
                (
                    f"{folder}/{picture.FOLDER}/{comp}.html",
                    picture.dressed(have["html"], own, self._look(episode)).encode(),
                )
            ]
        )
        ran = computer.run(
            f"cd {folder} && rm -f clip.mp4 && hyperframes render . --quality draft --fps 30 "
            "--output clip.mp4 --quiet >clip.log 2>&1",
            timeout=1800,
        )
        content = computer.get(f"{folder}/clip.mp4") if ran.ok else None
        if not content:
            return ""
        name = f"{picture.composition_id(unit['id'])}.mp4"
        return str(
            self.host.save_file(str(episode["thread_id"]), name, content, origin="episode")["id"]
        )

    def steer(self, episode_id: str, unit_id: str, text: str, *, by: str) -> Row:
        """A note for a picture's builder while it works, without stopping it: the note waits
        for the builder's next turn on the picture and goes in with it. Only a motion-graphics
        picture whose review, the builder's last turn on it, has not begun has one to come."""
        episode = self._episode(episode_id)
        said = " ".join(text.split())[:NOTE_CHARS]
        if not said:
            raise ValueError("Write the note first.")
        if not self._steerable(episode_id, unit_id):
            raise ValueError(
                "A note goes in with the builder's next turn on the picture, and this one has "
                "none to come."
            )
        note = {"id": f"sn_{secrets.token_hex(4)}", "text": said, "at": time.time()}
        self._steer.setdefault((episode_id, unit_id), []).append(note)
        self._say(episode, "Left a note for a picture's builder.", by=by, quiet=True)
        self._changed(episode_id)
        return self.view(episode_id)

    def unsteer(self, episode_id: str, unit_id: str, note_id: str, *, by: str) -> Row:
        """Take back a note the builder has not had yet."""
        queued = self._steer.get((episode_id, unit_id), [])
        kept = [n for n in queued if n["id"] != note_id]
        if len(kept) == len(queued):
            raise ValueError("That note has already gone to the builder.")
        if kept:
            self._steer[(episode_id, unit_id)] = kept
        else:
            self._steer.pop((episode_id, unit_id), None)
        self._say(self._episode(episode_id), "Took back a note.", by=by, quiet=True)
        self._changed(episode_id)
        return self.view(episode_id)

    def _steerable(self, episode_id: str, unit_id: str, have: Row | None = None) -> bool:
        """Whether a note to a picture's builder would reach it: a motion-graphics picture on
        its way whose review has not begun."""
        have = have if have is not None else self.store.picture(episode_id, unit_id)
        return (
            have is not None
            and have["status"] in ("queued", "making", "posing")
            and have["level"] == units.RICH
            and (episode_id, unit_id) not in self._last_turn
        )

    def _with_notes(self, episode_id: str, unit_id: str, stage: str, prompt: str) -> str:
        """A builder's next turn on a picture, with the notes the person left it while it
        worked: they leave the queue and are kept as given to this stage."""
        key = (episode_id, unit_id)
        if stage == "review":
            self._last_turn.add(key)
        queued = self._steer.pop(key, [])
        if not queued:
            return prompt
        given = time.time()
        self._steered.setdefault(key, []).extend(
            {**note, "stage": stage, "given_at": given} for note in queued
        )
        self._changed(episode_id)
        listed = "\n".join(f"- {note['text']}" for note in queued)
        return (
            f"{prompt}\n\nWhile you worked on this picture, the person left notes for this "
            f"turn. Take them in:\n{listed}"
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

    def make(
        self,
        episode_id: str,
        *,
        by: str,
        only: list[str] | None = None,
        chapter: str = "",
        level: str = "",
    ) -> Row:
        """Ask for pictures: the ones named (drawn again when they failed or are out of date), a
        chapter's that were never asked for (recording it asks for them), or with neither every
        one that stopped or failed. One that is current, or on its way, is left as it is. With a
        level the ones named are made again that way, current or not: the person said yes to
        making them so (switching how a made picture is made is that yes)."""
        episode = self._episode(episode_id)
        full = self._full(episode)
        if full is None or self.planning(episode_id):
            raise ValueError("The writer is still working. Ask when that has landed.")
        again = level in LEVELS and only is not None
        if again:
            picks = dict(episode["picks"] or {})
            units_picked = dict(picks.get("units", {}))
            for unit_id in only or ():
                units_picked[str(unit_id)] = {
                    **(units_picked.get(str(unit_id)) or {}),
                    "level": level,
                }
            self.store.update_episode(episode_id, picks={**picks, "units": units_picked})
            episode = self._episode(episode_id)
            full = self._full(episode) or full
        found = [u for u in self._units(episode, full) if u["kind"] == "picture"]
        failed = {
            str(p["unit"]) for p in self.store.pictures(episode_id) if p["status"] == "failed"
        }
        if only is None and not chapter:
            wanted = failed
            if not wanted:
                raise ValueError("Every picture is made or on its way.")
        else:
            wanted = {
                str(u["id"])
                for u in found
                if u["id"] in (only or ()) or (chapter and u["chapter"] == chapter)
            }
            if not wanted:
                raise ValueError("There is no picture to make there.")
        for unit in found:
            unit_id = str(unit["id"])
            running = self._builds.get((episode_id, unit_id))
            if unit_id not in wanted or (running is not None and not running.done()):
                continue
            have = self.store.picture(episode_id, unit_id)
            named = only is not None and unit_id in only
            if (
                have is None
                or (have["status"] == "failed" and (named or not chapter))
                or (named and (again or _outdated(have, unit) or _reworded(have, unit)))
            ):
                self._set_queued(episode_id, unit_id, sig="", failure="", level=unit["level"])
        self._set(episode_id, status=self._status(episode_id))
        self._queue_pictures(episode_id)
        self._say(episode, "Asked for pictures to be made.", by=by, quiet=True)
        self._settle(episode_id)
        return self.view(episode_id)

    def regenerate_chapter(
        self, episode_id: str, chapter: str, *, by: str, provider: str = "", model: str = ""
    ) -> Row:
        """Rebuild a chapter's pictures from the standing plan with an optional model for this run."""
        episode = self._episode(episode_id)
        full = self._full(episode)
        if full is None or self.planning(episode_id):
            raise ValueError("Wait for the plan before regenerating a chapter.")
        if f"film:{episode_id}" in self._jobs:
            raise ValueError("Wait for the film to finish rendering.")
        wanted = {
            str(unit["id"]): unit
            for unit in self._units(episode, full)
            if unit["kind"] == "picture" and unit["chapter"] == chapter
        }
        if not wanted:
            raise ValueError("This chapter has no visuals to regenerate.")
        if any(
            key[0] == episode_id and key[1] in wanted and not task.done()
            for key, task in self._builds.items()
        ):
            raise ValueError("This chapter's visuals are already being made.")
        generation_for = None
        if provider:
            if provider == DEMO or not self._can_write(provider):
                raise ValueError("That provider isn't ready for chapter regeneration.")
            pick = {"model": model, "effort": ""}
            generation_for = dict.fromkeys(
                wanted,
                {
                    "builder": provider,
                    "model_now": pick,
                    "generation": episode_models.generation(self.host.settings, provider, pick),
                },
            )
        elif model:
            raise ValueError("Choose a provider for the model.")
        for unit_id, unit in wanted.items():
            self._set_queued(episode_id, unit_id, sig="", failure="", level=unit["level"])
        self._set(episode_id, status=self._status(episode_id))
        self._queue_pictures(episode_id, generation_for=generation_for)
        self._say(episode, "Asked to regenerate a chapter's visuals.", by=by, quiet=True)
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
        self._set_queued(episode_id, unit_id, note=note)
        self._asked[(episode_id, unit_id)] = time.time()
        self._builds[(episode_id, unit_id)] = asyncio.get_running_loop().create_task(
            self._rebuilt(episode_id, unit_id, note), name=f"picture {episode_id} {unit_id}"
        )
        self._changed(episode_id)

    async def _rebuilt(self, episode_id: str, unit_id: str, note: str) -> None:
        try:
            await self._build(episode_id, unit_id, note)
        except asyncio.CancelledError:
            self._unmade(episode_id, unit_id, "Stopped.", stopped=True)
        except Exception as error:  # one picture failing must not stop the others
            _LOGGER.exception("picture failed on %s %s", episode_id, unit_id)
            self._unmade(episode_id, unit_id, _clean(str(error), 240))
        finally:
            self._record_timing(episode_id, unit_id)
            self._builds.pop((episode_id, unit_id), None)
            self._asked.pop((episode_id, unit_id), None)
            self._steer.pop((episode_id, unit_id), None)
            self._last_turn.discard((episode_id, unit_id))
            self._settle(episode_id)

    def _set_queued(self, episode_id: str, unit_id: str, **values: Any) -> None:
        """A picture asked for again: the version made before is kept (see `_put`)."""
        self._put(episode_id, unit_id, {**values, "status": "queued"})

    def _put(self, episode_id: str, unit_id: str, values: Row) -> None:
        """A picture's record moves: asked for again, or put back to a version of it. The
        version that stood joins the kept ones, first, unless it is the one put back, which
        leaves them; one with no number of its own (on its way) is numbered after every one
        kept, so a number is never made twice. Past `VERSIONS` the oldest made is dropped. A
        version put back is followed as its own build, not the one before it."""
        have = self.store.picture(episode_id, unit_id)
        made = values.get("status") in ("made", "go")
        n = values.get("version") if made else None
        kept = [k for k in (have or {}).get("versions") or [] if k["n"] != n]
        standing = _kept_version(have)
        if standing is not None and standing["n"] != n:
            kept.insert(0, standing)
        if n is None:
            values = {**values, "version": max((k["n"] for k in kept), default=0) + 1}
        else:
            self._began.pop((episode_id, unit_id), None)
            self._steered.pop((episode_id, unit_id), None)
        newest = sorted((k["n"] for k in kept), reverse=True)[:VERSIONS]
        self.store.set_picture(
            episode_id, unit_id, **values, versions=[k for k in kept if k["n"] in newest]
        )

    def _unmade(
        self, episode_id: str, unit_id: str, failure: str, *, stopped: bool = False, **values: Any
    ) -> None:
        """A build ended without a picture. A picture made again goes back to the version
        before, which stands as it did and says why the new one wasn't made (a stop needs no
        why); a first build is left not made, saying why. A stop that lands once the picture
        was settled (made, or a change taken back) leaves it as it is."""
        have = self.store.picture(episode_id, unit_id)
        if have is None:
            return
        building = have["status"] in ("queued", "making", "posing")
        if stopped and not building:
            return
        kept = have.get("versions") or []
        if not building or not kept:
            self.store.set_picture(episode_id, unit_id, status="failed", failure=failure, **values)
            return
        self._put(
            episode_id, unit_id, {**_standing(kept[0]), "failure": "" if stopped else failure}
        )

    def _record_timing(self, episode_id: str, unit_id: str) -> None:
        """Keeps with the beat how long its picture's build took, in all and stage by stage,
        once the build ends, however it ends. Only the build this house began is recorded, and
        only once: a build stopped before it began leaves the record of the one before as it
        is."""
        have = self.store.picture(episode_id, unit_id)
        kept = dict((have or {}).get("timing") or {})
        began = kept.get("started_at")
        if (
            have is None
            or not began
            or kept.get("ended_at")
            or self._began.get((episode_id, unit_id)) != began
        ):
            return
        thread_id = str(self._episode(episode_id)["thread_id"])
        turns = self.store.runs(thread_id, f"picture:{unit_id}")
        level = str(have.get("level") or units.SIMPLE)
        stages, _ = _stages(turns, have, level, float(began))
        self.store.set_picture(
            episode_id, unit_id, timing=_timing(float(began), time.time(), stages)
        )

    # -- takes -----------------------------------------------------------------------------------

    def _chapter_of(self, episode: Row, chapter: str) -> tuple[int, list[Row]]:
        """A chapter's number and its lines, in order."""
        full = self._full(episode)
        if full is None:
            raise ValueError("The plan isn't written yet.")
        found = next((c for c in full["chapters"] if c["id"] == chapter), None)
        if found is None:
            raise KeyError(chapter)
        return full["chapters"].index(found) + 1, [f for b in found["beats"] for f in b["frames"]]

    async def add_take(
        self,
        episode_id: str,
        *,
        by: str,
        chapter: str,
        frame: str = "",
        marks: Sequence[Mapping[str, Any]] = (),
        label: str = "",
        name: str,
        source: IO[bytes],
        recorded_at: float | None = None,
    ) -> Row:
        """A recording of a chapter (or of one line of it) made in the studio: cut to the film's
        format on the thread's computer and kept as this chapter's take while the person waits.
        `source` is the recording as an open file; it is read from there and never held in
        memory. A camera's clip, which takes minutes to bring in, comes by `bring_take`."""
        label = _label(label)
        episode = self._episode(episode_id)
        number, lines = self._chapter_of(episode, chapter)
        if frame and frame not in {f["id"] for f in lines}:
            raise KeyError(frame)
        source.seek(0, 2)
        if source.tell() == 0:
            raise ValueError("The recording is empty.")
        take_id = new_id("tk")
        made = await asyncio.to_thread(self._cut, episode, take_id, name, source)
        given = _given(marks, lines)
        if not frame and not given:
            given = _spread(lines, float(made["seconds"]))
        kept_at = await self._keep_footage(episode, take_id, name, source, by=by)
        self._new_take(
            episode,
            take_id,
            chapter=chapter,
            frame=frame,
            label=label,
            made=made,
            marks=given,
            recording={"kind": "studio" if marks else "file", "name": name, "at": recorded_at},
            raw=kept_at,
            by=by,
        )
        self._say(episode, f"Recorded a take of chapter {number}.", by=by, quiet=True)
        self._settle(episode_id)
        return self.view(episode_id)

    def bring_take(
        self,
        episode_id: str,
        *,
        by: str,
        chapter: str,
        name: str,
        source: Path,
        staged: bool,
        guide: str = "",
        label: str = "",
        clip: Mapping[str, Any] | None = None,
    ) -> Row:
        """A recording of a chapter brought in while the studio goes on: a file a person brought
        (`staged`: the house's own copy of their upload, which it moves or drops when done) or a
        clip on a camera's card, read where it is (`clip`, what the card says of it). A camera's
        file runs to gigabytes and its copies take minutes, so this returns at once and the
        chapter shows how far it has come. With `guide`, the take recorded at the same moment is
        found in it by sound and the clip takes that take's marks; with none, its lines are
        spread at the plan's pace."""
        label = _label(label)
        episode = self._episode(episode_id)
        self._chapter_of(episode, chapter)
        guide_take = None
        if guide:
            guide_take = self.store.take(guide)
            if (
                guide_take is None
                or guide_take["episode_id"] != episode_id
                or guide_take["chapter"] != chapter
                or guide_take["frame"]
            ):
                raise KeyError(guide)
            if not guide_take["audio"]:
                raise ValueError("This take has no sound to match the camera's file by.")
        key = f"import:{episode_id}:{chapter}"
        if key in self._jobs:
            raise ValueError("A recording is already coming in for this chapter.")
        try:
            size = source.stat().st_size
        except OSError as error:
            raise ValueError(f"The recording can't be read: {error.strerror or error}") from None
        if size == 0:
            raise ValueError("The recording is empty.")
        take_id = new_id("tk")
        before = str(((episode.get("imports") or {}).get(chapter) or {}).get("take") or "")
        self._import_set(
            episode_id,
            chapter,
            fresh=True,
            take=take_id,
            name=name,
            guide=guide,
            state="copying",
            done=0,
            total=size,
            fraction=0.0,
            failure="",
            started_at=time.time(),
        )
        self._jobs[key] = asyncio.get_running_loop().create_task(
            self._imported(
                episode_id,
                chapter,
                take_id,
                by=by,
                name=name,
                source=source,
                staged=staged,
                guide=guide_take,
                label=label,
                clip=dict(clip or {}),
                before=before,
            ),
            name=f"episode import {episode_id} {chapter}",
        )
        self._settle(episode_id)
        return self.view(episode_id)

    async def _imported(
        self,
        episode_id: str,
        chapter: str,
        take_id: str,
        *,
        by: str,
        name: str,
        source: Path,
        staged: bool,
        guide: Row | None,
        label: str,
        clip: Row,
        before: str,
    ) -> None:
        episode = self._episode(episode_id)
        stage, said_at = ["copying"], [0.0]

        def tell(**values: Any) -> None:
            # how far it has come, said at most every second or so unless it moved on a stage
            now = time.monotonic()
            if values.get("state") == stage[0] and now - said_at[0] < IMPORT_TOLD:
                return
            stage[0], said_at[0] = str(values.get("state") or stage[0]), now
            self._import_set(episode_id, chapter, **values)

        kept_at = ""
        try:
            if before:
                await asyncio.to_thread(self._forget_copies, episode, before)
            brought = await asyncio.to_thread(
                self._cut_in, episode, take_id, name, source, guide, tell
            )
            # the original is kept while its copies are made: a card is read once more for it
            made, kept = await asyncio.gather(
                asyncio.to_thread(self._cut_out, episode, brought, tell),
                self._keep_footage(episode, take_id, name, source, by=by, move=staged),
                return_exceptions=True,
            )
            kept_at = kept if isinstance(kept, str) else ""
            if isinstance(kept, BaseException):
                raise kept
            if isinstance(made, BaseException):
                raise made
            number, lines = self._chapter_of(self._episode(episode_id), chapter)
            found = brought.match
            ids = {f["id"] for f in lines}
            if found is not None and guide is not None:
                marks = [
                    {"frame": str(m["frame"]), "t": round(found.into(float(m["t"])), 3)}
                    for m in guide["marks"]
                    if str(m["frame"]) in ids
                ]
                matched: Row | None = {
                    "take": guide["id"],
                    "n": guide["n"],
                    "score": found.score,
                    "start": found.start,
                }
            else:
                marks, matched = _spread(lines, float(made["seconds"])), None
            self._new_take(
                episode,
                take_id,
                chapter=chapter,
                frame="",
                label=label,
                made=made,
                marks=marks,
                recording={
                    "kind": "camera" if clip else "file",
                    "name": name,
                    "at": clip.get("recorded_at") or None,
                    "matched": matched,
                    **_noticed(brought.seen, clip),
                },
                raw=kept_at,
                by=by,
            )
            with self._imports_lock:
                imports = dict(self._episode(episode_id).get("imports") or {})
                imports.pop(chapter, None)
                self.store.update_episode(episode_id, imports=imports)
            self._say(
                episode,
                f"Brought {name} in as chapter {number}'s take"
                + (f", matched to take {guide['n']} by sound." if matched and guide else "."),
                by=by,
                quiet=True,
            )
        except Exception as error:
            if not isinstance(error, ValueError | KeyError):
                _LOGGER.exception("bringing %s in for %s failed", name, episode_id)
            failure = (
                "The chapter is no longer in the plan."
                if isinstance(error, KeyError)
                else _clean(str(error), 300) or "It couldn't be brought in."
            )
            self._import_set(
                episode_id, chapter, state="failed", failure=failure, ended_at=time.time()
            )
            with contextlib.suppress(Exception):
                await asyncio.to_thread(self._forget_copies, episode, take_id)
            if kept_at and not kept_at.startswith("s3://"):
                # the original of a take that isn't one: the person still has it where it was
                with contextlib.suppress(OSError):
                    Path(kept_at).unlink()
        finally:
            if staged:
                with contextlib.suppress(OSError):
                    source.unlink(missing_ok=True)
            self._jobs.pop(f"import:{episode_id}:{chapter}", None)
            self._settle(episode_id)

    def _import_set(
        self, episode_id: str, chapter: str, *, fresh: bool = False, **values: Any
    ) -> None:
        """Where a recording being brought in for a chapter stands, for its studio to show."""
        with self._imports_lock:
            imports = dict(self._episode(episode_id).get("imports") or {})
            imports[chapter] = {**({} if fresh else imports.get(chapter) or {}), **values}
            self.store.update_episode(episode_id, imports=imports)
        self._changed(episode_id)

    def forget_import(self, episode_id: str, chapter: str) -> Row:
        """A recording that couldn't be brought in, put out of the chapter's way."""
        self._episode(episode_id)
        if f"import:{episode_id}:{chapter}" in self._jobs:
            raise ValueError("It is still coming in.")
        with self._imports_lock:
            imports = dict(self._episode(episode_id).get("imports") or {})
            imports.pop(chapter, None)
            self.store.update_episode(episode_id, imports=imports)
        self._settle(episode_id)
        return self.view(episode_id)

    def _new_take(
        self,
        episode: Row,
        take_id: str,
        *,
        chapter: str,
        frame: str,
        label: str,
        made: Row,
        marks: list[Row],
        recording: Row,
        raw: str,
        by: str,
    ) -> Row:
        """A take, kept: it takes the place of the chapter's (or the line's) take before it."""
        episode_id = str(episode["id"])
        for other in self.store.takes(episode_id):
            if other["chapter"] == chapter and other["frame"] == frame and other["kept"]:
                self.store.update_take(str(other["id"]), kept=False)
        return self.store.add_take(
            {
                "id": take_id,
                "episode_id": episode_id,
                "chapter": chapter,
                "label": label,
                "frame": frame,
                "seconds": float(made["seconds"]),
                "marks": marks,
                "video": made["video"],
                "audio": made["audio"],
                "uhd": made["uhd"],
                "raw": raw,
                "recording": {k: v for k, v in recording.items() if v not in (None, "")},
                "kept": True,
                "added_by": by,
            }
        )

    def _footage_folder(self) -> Path:
        named = self.host.settings.footage_dir
        return named.expanduser() if named else self.data_dir / "footage"

    async def _keep_footage(
        self,
        episode: Row,
        take_id: str,
        name: str,
        source: IO[bytes] | Path,
        *,
        by: str,
        move: bool = False,
    ) -> str:
        """The recording as it arrived, kept under its take's name: in the house's bucket (S3,
        or MinIO in development) when there is one, else in its footage folder (a drive of its
        own, or the house's folder). Where it was kept, or nothing: a take is not lost to a
        store that is down or a drive that isn't there, and the thread says when it wasn't
        kept. With `move`, the recording is the house's own copy and is moved, not copied."""
        from design_agent.tools.footage import Bucket, FootageError

        if self.host.blobs.backend == "s3":

            def save_private() -> str:
                filename = f"{take_id}.{_ending(name)}"
                if isinstance(source, Path):
                    with source.open("rb") as stream:
                        return self.host.blobs.save_recording(filename, stream)
                return self.host.blobs.save_recording(filename, source)

            return await asyncio.to_thread(save_private)

        bucket = Bucket.from_settings(self.host.settings)
        if bucket is not None:
            key = f"episodes/{episode['id']}/takes/{take_id}.{_ending(name)}"

            def put() -> str:
                if isinstance(source, Path):
                    with source.open("rb") as opened:
                        return bucket.put(key, opened, name=name)
                return bucket.put(key, source, name=name)

            try:
                return await asyncio.to_thread(put)
            except (FootageError, OSError) as error:
                _LOGGER.warning("footage of take %s was not kept: %s", take_id, error)
                self._say(
                    episode,
                    f"The recording itself was not kept in the bucket: {_clean(str(error), 240)}",
                    by=by,
                    quiet=True,
                )
                return ""
        folder = self._footage_folder()
        target = folder / str(episode["id"]) / f"{take_id}-{_stem(name)}.{_ending(name)}"
        try:
            await asyncio.to_thread(_keep_file, source, target, move=move)
        except OSError as error:
            _LOGGER.warning("footage of take %s was not kept: %s", take_id, error)
            self._say(
                episode,
                f"The recording itself was not kept in {folder}: "
                f"{_clean(error.strerror or str(error), 200)}",
                by=by,
                quiet=True,
            )
            return ""
        return str(target)

    def _cut(self, episode: Row, take_id: str, name: str, source: IO[bytes] | Path) -> Row:
        """A recording made in the studio, as the film uses it (`_cut_in`, then `_cut_out`)."""
        return self._cut_out(episode, self._cut_in(episode, take_id, name, source))

    def _cut_in(
        self,
        episode: Row,
        take_id: str,
        name: str,
        source: IO[bytes] | Path,
        guide: Row | None = None,
        tell: Callable[..., None] | None = None,
    ) -> Brought:
        """A recording brought onto the thread's computer and looked at: what is in it, and,
        with a `guide` take, where that take begins in it (`sync`). The recording is copied
        across as a file, never held in memory: a camera's own runs to gigabytes."""
        computer = self._computer(episode)
        folder = self._takes_folder(str(episode["id"]))
        src = f"{folder}/{take_id}.src.{_ending(name)}"
        brought = Brought(computer, folder, take_id, src)
        try:
            with contextlib.ExitStack() as stack:
                stream = (
                    stack.enter_context(source.open("rb")) if isinstance(source, Path) else source
                )
                stream.seek(0, 2)
                size = stream.tell()
                counted = (
                    (
                        lambda sent: tell(
                            state="copying", done=sent, total=size, fraction=sent / size
                        )
                    )
                    if tell is not None and size
                    else None
                )
                computer.put_stream(src, stream, progress=counted)
            # What is in it, and whether this computer can bring a bright picture down to the
            # film's range.
            looked = computer.run(
                f'cd {folder} && echo "streams: $(ffprobe -v error -show_entries '
                "stream=codec_type,color_transfer,color_space,color_primaries,channels,height,"
                f"avg_frame_rate:format=duration -of json {src} 2>/dev/null | tr -d ' \\n')\"; "
                "echo \"zscale: $(ffmpeg -hide_banner -filters 2>/dev/null | grep -c ' zscale ')\"",
                timeout=600,
            ).output
            brought.seen = _seen(looked)
            if not brought.seen.video and not brought.seen.sound:
                raise ValueError("The recording couldn't be read: it has no picture or sound.")
            if guide is not None:
                if tell is not None:
                    tell(state="matching", fraction=0.0)
                brought.match = self._match(episode, brought, guide)
            return brought
        except BaseException:
            computer.run(f"rm -f {src}", timeout=120)
            raise

    def _match(self, episode: Row, brought: Brought, guide: Row) -> sync.Match:
        """Where the take recorded at the same moment begins in the brought recording, by the
        sound the two have in common. Refused, with why, when it can't be told (`sync`)."""
        if not brought.seen.sound:
            raise sync.Unmatched("The camera's file has no sound to match this take by.")
        computer, folder, take_id = brought.computer, brought.folder, brought.take_id
        heard = self._in_sandbox(computer, episode, [(guide, "audio")]).get(
            (str(guide["id"]), "audio")
        )
        if heard is None:
            raise ValueError("This take's sound is missing, so there's nothing to match by.")
        curve = shlex.quote(sync.ENVELOPE)
        ran = computer.run(
            f"cd {folder} && ffmpeg -v error -y -i {heard} -vn -af {curve} -f f32le "
            f"{take_id}.take.env && ffmpeg -v error -y -i {brought.src} -vn -map 0:a:0 "
            f"-af {curve} -f f32le {take_id}.camera.env",
            timeout=3600,
        )
        take_curve = computer.get(f"{folder}/{take_id}.take.env") if ran.ok else None
        camera_curve = computer.get(f"{folder}/{take_id}.camera.env") if ran.ok else None
        if not take_curve or not camera_curve:
            raise ValueError(f"The sound couldn't be read: {_clean(ran.output[-200:])}")
        last = max((float(m["t"]) for m in guide["marks"] or []), default=0.0)
        return sync.match(sync.curve(take_curve), sync.curve(camera_curve), last_mark=last)

    def _cut_out(
        self, episode: Row, brought: Brought, tell: Callable[..., None] | None = None
    ) -> Row:
        """The copies the film uses, made in one reading of the recording: no taller than the
        film's frame (for the studio and a film in HD), and no taller than 2160 when it is taller
        than that (for a film in 4K). Each runs at a constant 30 frames a second with a key frame
        every half second (so any line can be played from where it starts), in the film's range
        of light, with its sound at the film's loudness beside it. Only the stretch a guide take
        was found in is kept. The copies stay on the thread's computer for the renders and are
        kept among the house's files, both moved as files, never held in memory."""
        computer, folder, take_id, seen = (
            brought.computer,
            brought.folder,
            brought.take_id,
            brought.seen,
        )
        found = brought.match
        span = (found.begin, found.end - found.begin) if found is not None else None
        seek = f"-ss {span[0]:.3f} -t {span[1]:.3f} " if span else ""
        seconds = span[1] if span else seen.seconds
        try:
            level = ""
            if seen.sound:
                measured = computer.run(
                    f"ffmpeg -hide_banner -nostats {seek}-i {brought.src} -vn -map 0:a:0 "
                    "-af ebur128=peak=true:framelog=verbose -f null - 2>&1 | tail -n 20",
                    timeout=3600,
                ).output
                level = _levelled(measured)
            sound = (
                "-ac 2 " if any(int(s.get("channels") or 0) > 2 for s in seen.sound) else ""
            ) + "-c:a aac -b:a 160k -ar 48000"
            hd, uhd, said = f"{take_id}.mp4", f"{take_id}.uhd.mp4", f"{take_id}.m4a"
            progress = f"-progress {take_id}.progress "
            if seen.video:
                tall = seen.height > geometry.FRAME_H
                light = f",{TONEMAP}" if seen.bright else ""
                tags = (
                    "-colorspace bt709 -color_primaries bt709 -color_trc bt709 "
                    if seen.bright or seen.bt709
                    else ""
                )
                x264 = (
                    "-c:v libx264 -preset veryfast -crf 18 -g 15 -pix_fmt yuv420p "
                    f"{tags}-movflags +faststart"
                )
                graph = "[0:v:0]fps=30" + (",split=2[a][b];[a]" if tall else ",")
                graph += f"scale=-2:'min({geometry.FRAME_H},ih)':flags=lanczos{light}[hd]"
                if tall:
                    graph += f";[b]scale=-2:'min({UHD},ih)':flags=lanczos{light}[uhd]"
                if seen.sound:
                    graph += f";[0:a:0]{level or 'anull'}[said]"
                outputs = '-map "[hd]" ' + ('-map "[said]" ' + sound if seen.sound else "-an")
                outputs += f" {x264} {hd}"
                if tall:
                    outputs += f' -map "[uhd]" -an {x264} {uhd}'
                cut = (
                    f'ffmpeg -v error -y {progress}{seek}-i {brought.src} -filter_complex "{graph}" '
                    f"{outputs}"
                    + (f" && ffmpeg -v error -y -i {hd} -vn -c:a copy {said}" if seen.sound else "")
                )
            else:
                cut = (
                    f"ffmpeg -v error -y {progress}{seek}-i {brought.src} -vn "
                    + (f'-af "{level}" ' if level else "")
                    + f"{sound} {said}"
                )
            self._run_cut(computer, folder, take_id, cut, seconds, tell)
            listed = computer.run(
                f"cd {folder} && "
                f'for f in {hd} {uhd} {said}; do [ -s $f ] && echo "$f $(ffprobe -v error '
                '-show_entries format=duration -of csv=p=0 $f)"; done',
                timeout=120,
            )
            lengths = dict(
                re.findall(rf"({take_id}\.(?:mp4|uhd\.mp4|m4a)) ([0-9.]+)", listed.output)
            )
            if not lengths:
                raise ValueError(f"The recording couldn't be cut: {_clean(listed.output[-200:])}")
            if tell is not None:
                tell(state="saving", fraction=1.0)
            out: Row = {
                "video": "",
                "audio": "",
                "uhd": "",
                "seconds": max(float(v) for f, v in lengths.items() if f != uhd),
            }
            thread_id = str(episode["thread_id"])
            for kind, made in (("video", hd), ("uhd", uhd), ("audio", said)):
                if made not in lengths:
                    continue

                def write(into: IO[bytes], made: str = made) -> None:
                    computer.get_into(f"{folder}/{made}", into)

                shown = f"{take_id}-{UHD}.mp4" if kind == "uhd" else made
                out[kind] = str(
                    self.host.save_file_from(thread_id, shown, write, origin="episode")["id"]
                )
            return out
        except BaseException:
            with contextlib.suppress(Exception):
                self._forget_copies(episode, take_id)
            raise
        finally:
            with contextlib.suppress(Exception):
                computer.run(
                    f"cd {folder} && rm -f {take_id}.src.* {take_id}.*.env {take_id}.progress "
                    f"{take_id}.exit {take_id}.log {take_id}.pid",
                    timeout=120,
                )

    def _run_cut(
        self,
        computer: Computer,
        folder: str,
        take_id: str,
        cut: str,
        seconds: float,
        tell: Callable[..., None] | None,
    ) -> None:
        """The cut, left running on the thread's computer by itself (a camera's clip takes as
        long as it runs, or longer), and watched until it ends: how far it has come is told
        from ffmpeg's own progress."""
        worker = f"{cut}; echo $? > {take_id}.exit.tmp && mv {take_id}.exit.tmp {take_id}.exit"
        started = computer.run(
            f"cd {folder} && rm -f {take_id}.exit && "
            f"(nohup sh -c {shlex.quote(worker)} </dev/null >{take_id}.log 2>&1 & "
            f"echo $! > {take_id}.pid)",
            timeout=60,
        )
        if not started.ok:
            raise ValueError(f"The cut could not start: {_clean(started.output[-200:])}")
        deadline = time.monotonic() + max(1800.0, seconds * 8)
        while True:
            time.sleep(CUT_POLL)
            if self._closing:
                raise ValueError("The house closed before the recording was cut.")
            poll = computer.run(
                f'cd {folder} && echo "exit: $(cat {take_id}.exit 2>/dev/null)"; '
                f"tail -c 2000 {take_id}.progress 2>/dev/null | grep '^out_time_us=' | tail -1",
                timeout=60,
            ).output
            ended = re.search(r"^exit: (\d+)", poll, re.M)
            if ended:
                break
            at = re.search(r"^out_time_us=(\d+)", poll, re.M)
            if tell is not None and at and seconds > 0:
                tell(state="cutting", fraction=min(1.0, int(at[1]) / 1e6 / seconds))
            if time.monotonic() > deadline:
                raise ValueError("Cutting the recording took far longer than it runs.")
        if ended[1] != "0":
            said = computer.run(f"tail -c 600 {folder}/{take_id}.log", timeout=60).output
            raise ValueError(f"The recording couldn't be cut: {_clean(said[-240:])}")

    def _forget_copies(self, episode: Row, take_id: str) -> None:
        """A take's files on the thread's computer gone, and a cut still making them stopped
        (by the process it was left running as: a match on its name would match this too)."""
        computer = self._computer(episode)
        computer.run(
            f"cd {self._takes_folder(str(episode['id']))} 2>/dev/null || exit 0; "
            f'if [ -s {take_id}.pid ]; then p=$(cat {take_id}.pid); pkill -P "$p"; kill "$p"; fi '
            f"2>/dev/null; rm -f {take_id}.*",
            timeout=120,
        )

    def _takes_folder(self, episode_id: str) -> str:
        root = "/tmp/design-agent" if self.host.blobs.backend == "s3" else PROJECTS  # noqa: S108
        return f"{root}/{episode_id}/takes"

    def _take_path(self, episode_id: str, take_id: str, kind: str) -> str:
        """Where a take's copy (`video`, `uhd` or `audio`) stays on the thread's computer."""
        return f"{self._takes_folder(episode_id)}/{take_id}.{COPIES[kind]}"

    def _in_sandbox(
        self, computer: Computer, episode: Row, copies: Sequence[tuple[Row, str]]
    ) -> dict[tuple[str, str], str]:
        """Where these copies of takes (a take, and `video`, `uhd` or `audio`) are on the
        thread's computer, where they stay between renders. A copy not there whole (a new
        computer, a take from before copies were kept there) is sent again from the house's
        files, as a file."""
        wanted: dict[tuple[str, str], tuple[str, Row]] = {}
        for take, kind in copies:
            row = self.store.file(str(take.get(kind) or "")) if take.get(kind) else None
            if row is not None:
                wanted[(str(take["id"]), kind)] = (
                    self._take_path(str(episode["id"]), str(take["id"]), kind),
                    row,
                )
        if not wanted:
            return {}
        paths = " ".join(path for path, _ in wanted.values())
        listed = computer.run(
            f'for f in {paths}; do [ -f "$f" ] && echo "$(wc -c < "$f" | tr -d " ") $f"; done',
            timeout=120,
        ).output
        sizes = {path: int(size) for size, path in re.findall(r"^(\d+) (\S+)$", listed, re.M)}
        for path, row in wanted.values():
            if sizes.get(path) != int(row["size"]):
                with self.host.blobs.open(row) as copy_of:
                    if row.get("storage") == "s3":
                        with tempfile.TemporaryFile() as stream:
                            shutil.copyfileobj(copy_of, stream)
                            computer.put_stream(path, stream)
                    else:
                        computer.put_stream(path, copy_of)
        return {key: path for key, (path, _) in wanted.items()}

    def keep_take(self, episode_id: str, take_id: str, *, keep: bool) -> Row:
        take = self.store.take(take_id)
        if take is None or take["episode_id"] != episode_id:
            raise KeyError(take_id)
        if keep:
            for other in self.store.takes(episode_id):
                if other["chapter"] == take["chapter"] and other["frame"] == take["frame"]:
                    self.store.update_take(str(other["id"]), kept=other["id"] == take_id)
        else:
            # a deleted take's copies go with it (a 4K one runs to gigabytes); the recording
            # as it arrived stays where it was kept
            self.store.delete_take(take_id)
            for kind in COPIES:
                if take.get(kind):
                    self.host.drop_file(str(take[kind]))
            episode = self._episode(episode_id)
            with contextlib.suppress(RuntimeError):
                asyncio.get_running_loop().create_task(
                    asyncio.to_thread(_quietly, self._forget_copies, episode, take_id)
                )
        self._settle(episode_id)
        return self.view(episode_id)

    # -- the film --------------------------------------------------------------------------------

    @staticmethod
    def _render_blocked(pictures: Sequence[Row], kept: Sequence[Row]) -> str:
        if any(p["status"] in ("queued", "making", "posing") for p in pictures):
            return "Wait for pictures to finish before rendering."
        if not kept and not any(p["html"] and p["status"] in ("made", "go") for p in pictures):
            return "Make a picture or record a chapter first."
        return ""

    def _film_sig(
        self,
        episode: Row,
        full: Row,
        pictures: Sequence[Row],
        kept: Sequence[Row],
        look: picture.Look | None = None,
        clock: Row | None = None,
    ) -> str:
        takes = [(t["id"], t["marks"]) for t in kept]
        made = sorted(
            (p["unit"], p["sig"], plans.digest(p["html"]))
            for p in pictures
            if p["status"] in ("made", "go") and p["html"]
        )
        spoken = sorted((k, v.get("h")) for k, v in self._voice(episode, full).items())
        parts: list[Any] = [full.get("chapters"), full.get("brief"), takes, made, spoken]
        camera_frames = {
            f["id"] for _, _, f in plans.frames_of(full) if f.get("presence") in ("person", "both")
        }
        video_takes = {t["id"] for t in kept if t.get("video")}
        if camera_frames and any(
            line["frame"] in camera_frames and line["source"].get("take") not in video_takes
            for line in (clock or timeline.schedule(full, list(kept)))["lines"]
        ):
            parts.append(("portrait", episode["settings"].get("portrait", "mira")))
        previous = None
        for _, _, frame in plans.frames_of(full):
            current = (
                geometry.for_frame(frame) if frame.get("presence") in ("person", "both") else None
            )
            if (
                previous
                and current
                and previous.person
                and current.person
                and (previous.person, previous.person_radius, previous.zoom)
                != (current.person, current.person_radius, current.zoom)
            ):
                parts.append("presenter-motion-v1")
                break
            previous = current
        if (
            any(p.get("generation") for p in pictures)
            or episode["settings"].get("background_color")
            or episode["settings"].get("background_texture", "solid") != "solid"
        ):
            parts.append((look or self._look(episode)).tokens())
        picked = (episode["settings"].get("narrator") or {}).get("id")
        if picked and episode["settings"].get("voice") == "narrator":
            # a voice picked for this film: another one is another film. A film narrated in
            # the house's voice keeps the signature it was rendered with.
            parts.append(picked)
        return plans.digest(json.dumps(parts, sort_keys=True))

    def render(self, episode_id: str, *, by: str, size: str = "") -> Row:
        """The film rendered on the thread's computer, in HD or in 4K (`SIZES`); with no size
        named, in the size it was asked for last."""
        episode = self._episode(episode_id)
        if self._full(episode) is None or self._status(episode_id) != "studio":
            # a film of nothing but stand-ins is no draft: something of it is made first
            raise ValueError("Make a picture or record a chapter first.")
        film_was = episode["film"] or {}
        if film_was.get("status") == "rendering":
            raise ValueError("The film is already rendering.")
        size = size or str(film_was.get("making") or film_was.get("size") or "hd")
        if size not in SIZES:
            raise ValueError("A film is rendered in HD or in 4K.")
        blocked = self._render_blocked(self.store.pictures(episode_id), self._kept(episode_id))
        if blocked:
            raise ValueError(blocked)
        self.store.update_episode(
            episode_id,
            film={
                **{
                    k: v
                    for k, v in film_was.items()
                    if k in ("voice", "file", "poster", "sig", "at", "seconds", "size")
                },
                "status": "rendering",
                "making": size,
                "started_at": time.time(),
                "phase": "prepare",
                "fraction": 0.0,
                "failure": "",
            },
        )
        self._jobs[f"film:{episode_id}"] = asyncio.get_running_loop().create_task(
            self._rendered(episode_id), name=f"episode film {episode_id}"
        )
        shown = " in 4K" if size == "4k" else ""
        self._say(episode, f"Asked for the film of “{episode['title']}”{shown}.", by=by)
        self._settle(episode_id)
        return self.view(episode_id)

    def _clone_similarity(self, episode: Row, voice_id: str) -> float | None:
        voice = self.store.voice_clone(voice_id) if voice_id else None
        if voice and voice["channel_id"] == self._channel_of(episode):
            return CLONE_SIMILARITY
        return None

    def _speech_identity(self, episode: Row) -> str:
        if episode["settings"].get("voice") == "local":
            return f"local:{local_speech.engine()}:en:165:v1"
        voice_id = self._voice_id(episode)
        similarity = self._clone_similarity(episode, voice_id)
        return f"{voice_id}:similarity:{similarity}" if similarity is not None else voice_id

    async def preview_clip(self, episode_id: str, unit_id: str) -> Row:
        """Play the saved artwork with this cut's narration or takes, including older silent clips."""
        gate = self._gates.setdefault(f"{episode_id}:mix:{unit_id}", asyncio.Semaphore(1))
        async with gate:
            episode = self._episode(episode_id)
            full = self._full(episode) or {}
            unit = next((u for u in self._units(episode, full) if u["id"] == unit_id), None)
            have = self.store.picture(episode_id, unit_id)
            if not unit or not have or have["status"] not in ("go", "made") or not have["clip"]:
                raise ValueError("This picture does not have a playable preview yet.")
            await self._narrate(episode_id, unit["chapter"])
            episode = self._episode(episode_id)
            spans = (have.get("generation") or {}).get("clip_lines") or picture.clock(
                unit, timeline.schedule(full)
            )["lines"]
            voice = self._voice(episode, full)
            takes = {t["id"]: t for t in self.store.takes(episode_id) if t["kept"]}
            clock = timeline.schedule(full, self._kept(episode_id), voice)
            segments = []
            for line in clock["lines"]:
                fid = line["frame"]
                if fid not in spans:
                    continue
                source = line["source"]
                file_id = ""
                if source["kind"] == "take":
                    file_id = takes[source["take"]]["audio"]
                elif source["kind"] == "voice":
                    file_id = voice[fid]["file"]
                start, end = spans[fid]
                segments.append((start, end, file_id, source.get("offset", 0), line["seconds"]))
            original = self._file(have["clip"])
            if not original:
                raise ValueError("The saved picture clip is missing.")
            if not any(s[2] for s in segments):
                return original
            signature = plans.digest(have["clip"], segments)
            cached = (have.get("generation") or {}).get("audio_preview", {})
            if cached.get("sig") == signature and (file := self._file(cached.get("file"))):
                return file
            content = await asyncio.to_thread(self._mix_preview, episode, have["clip"], segments)
            current = self.store.picture(episode_id, unit_id)
            if not current or current["clip"] != have["clip"]:
                raise ValueError("The picture changed while preparing playback. Press play again.")
            saved = self.host.save_file(
                str(episode["thread_id"]),
                f"{picture.composition_id(unit_id)}-narrated.mp4",
                content,
                origin="episode",
            )
            self.store.set_picture(
                episode_id,
                unit_id,
                generation={
                    **(current.get("generation") or {}),
                    "audio_preview": {"sig": signature, "file": saved["id"]},
                },
            )
            return self.host.file_view(saved)

    def _mix_preview(
        self, episode: Row, clip: str, segments: list[tuple[float, float, str, float, float]]
    ) -> bytes:
        """Retime each visual to the actual spoken line and keep the speaker's natural pace."""
        computer = self._computer(episode)
        folder = f"{PROJECTS}/{episode['id']}/preview/{new_id('mix')}"

        def file_bytes(fid: str) -> bytes:
            row = self.store.file(fid)
            if not row or row["thread_id"] != episode["thread_id"]:
                raise ValueError("A preview source is unavailable.")
            return self.host.blobs.read(row)

        files = [(f"{folder}/art.mp4", file_bytes(clip))]
        inputs = ["-i art.mp4"]
        filters = []
        for i, (start, end, fid, offset, duration) in enumerate(segments):
            filters.append(
                f"[0:v]trim=start={start:.3f}:end={end:.3f},setpts=(PTS-STARTPTS)*{duration / max(end - start, 0.001):.8f},fps=30,tpad=stop_mode=clone:stop_duration=1,trim=duration={duration:.3f}[v{i}]"
            )
            if fid:
                files.append((f"{folder}/sound-{i}", file_bytes(fid)))
                inputs.append(f"-ss {offset:.3f} -i sound-{i}")
                audio = f"[{len(inputs) - 1}:a]aresample=48000,apad"
            else:
                audio = "anullsrc=r=48000:cl=mono"
            filters.append(f"{audio},atrim=duration={duration:.3f},asetpts=PTS-STARTPTS[a{i}]")
        pairs = "".join(f"[v{i}][a{i}]" for i in range(len(segments)))
        filters.append(f"{pairs}concat=n={len(segments)}:v=1:a=1[v][a]")
        try:
            computer.put(files)
            command = f"cd {folder} && ffmpeg -v error -y {' '.join(inputs)} -filter_complex '{';'.join(filters)}' -map '[v]' -map '[a]' -c:v libx264 -preset ultrafast -crf 20 -threads 2 -pix_fmt yuv420p -c:a aac -movflags +faststart preview.mp4"
            ran = computer.run(command, timeout=600)
            content = computer.get(f"{folder}/preview.mp4") if ran.ok else None
            if not content:
                raise ValueError("The narrated preview could not be encoded.")
            return content
        finally:
            computer.run(f"rm -rf {folder}")

    async def preview_voice(self, episode_id: str, chapter: str) -> Row:
        episode = self._episode(episode_id)
        full = self._full(episode) or {}
        if not any(ch["id"] == chapter for ch in full.get("chapters", [])):
            raise KeyError(chapter)
        await self._narrate(episode_id, chapter)
        return self.view(episode_id)

    async def _narrate(self, episode_id: str, chapter: str = "") -> None:
        gate = self._gates.setdefault(f"{episode_id}:voice-cache", asyncio.Semaphore(1))
        async with gate:
            await self._speak_lines(episode_id, chapter)

    async def _speak_lines(self, episode_id: str, chapter: str) -> None:
        """Speak uncovered lines, reusing audio when the words and voice settings match."""
        episode = self._episode(episode_id)
        full = self._full(episode)
        mode = episode["settings"].get("voice")
        if full is None or mode not in ("narrator", "local"):
            return
        if mode == "narrator" and not self._speaks():
            raise ValueError("Narration needs ELEVENLABS_API_KEY.")
        identity = self._speech_identity(episode)
        if not identity:
            raise ValueError("Narration needs a voice: pick one under Voice, or clone yours.")
        from design_agent.tools.media import MediaKeys, Spoken, speak

        keys = MediaKeys.from_settings(self.host.settings)
        voice_id = self._voice_id(episode)
        similarity = self._clone_similarity(episode, voice_id) if mode == "narrator" else None
        clock = timeline.schedule(full, self._kept(episode_id))
        lines = [f for _, _, f in plans.frames_of(full)]
        spoken: Row = dict((episode["film"] or {}).get("voice") or {})
        for i, f in enumerate(lines):
            line = timeline.line_of(clock, f["id"])
            if chapter and (line is None or line["chapter"] != chapter):
                continue
            words = str(f.get("vo") or "")
            mark = plans.digest(words, identity)
            if line is None or line["source"]["kind"] == "take" or not words.strip():
                continue
            if (spoken.get(f["id"]) or {}).get("h") == mark:
                continue
            said: Spoken | str
            if mode == "local":
                said = await asyncio.to_thread(local_speech.synthesize, words)
            else:
                said = await speak(
                    keys,
                    words,
                    voice_id,
                    similarity_boost=similarity,
                    previous_text=str(lines[i - 1].get("vo") or "") if i else None,
                    next_text=str(lines[i + 1].get("vo") or "") if i + 1 < len(lines) else None,
                )
            if isinstance(said, str):
                raise ValueError(f"Narration stopped at line {f['id']}: {said}")
            row = self.host.save_file(
                str(episode["thread_id"]),
                f"voice-{f['id'].replace('.', '-')}.{'wav' if mode == 'local' else 'mp3'}",
                said.audio,
                origin="episode",
            )
            spoken[f["id"]] = {
                "file": row["id"],
                "seconds": said.seconds,
                "words": said.words,
                "h": mark,
                "mode": mode,
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
                "video": t.get("video"),
            }
            for t in self.store.takes(episode_id)
            if t["kept"]
        ]

    def _voice(self, episode: Row, full: Row) -> Row:
        """Cached narration that matches the current speaker, settings, and words."""
        mode = episode["settings"].get("voice")
        if mode not in ("local", "narrator"):
            return {}
        identity = self._speech_identity(episode)
        cached = (episode["film"] or {}).get("voice") or {}
        return {
            f["id"]: clip
            for _, _, f in plans.frames_of(full)
            if (clip := cached.get(f["id"]))
            and clip.get("mode", "narrator") == mode
            and clip.get("h") == plans.digest(f.get("vo") or "", identity)
        }

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
        channel_clones = self.store.voice_clone_ids()
        rows = [
            {
                "id": v.id,
                "name": v.name,
                "own": v.own,
                "usual": v.id == usual,
                **({"preview": v.preview} if v.preview else {}),
            }
            for v in heard[1]
            if v.id not in channel_clones
        ]
        if usual and usual not in channel_clones and not any(row["usual"] for row in rows):
            # a voice from ElevenLabs' library, used by its id without being kept in the account
            rows.insert(0, {"id": usual, "name": "The house's voice", "own": False, "usual": True})
        return {"voices": rows}

    @staticmethod
    def _clone_pick(voice: Row) -> Row:
        pick = {"id": voice["id"], "name": voice["name"]}
        if voice.get("verify"):
            pick["verify"] = True
        return pick

    def channel_voices(self, channel_id: str) -> list[Row]:
        if self.store.channel(channel_id) is None:
            raise KeyError(channel_id)
        return [self._clone_pick(row) for row in self.store.channel_voice_clones(channel_id)]

    @staticmethod
    def _voice_preview_url(episode_id: str, voice_id: str) -> str:
        return f"/api/episodes/{episode_id}/voice/{voice_id}/preview?similarity={CLONE_SIMILARITY}"

    @staticmethod
    def _voice_preview_name(voice_id: str) -> str:
        return f"voice-preview-{voice_id}-similarity-{CLONE_SIMILARITY}.mp3"

    def _current_voice_preview(self, voice: Row) -> bool:
        file = self.store.file(voice["preview_file"]) if voice["preview_file"] else None
        return file is not None and file["name"] == self._voice_preview_name(voice["id"])

    def _channel_voice(self, episode: Row, voice_id: str) -> Row:
        voice = self.store.voice_clone(voice_id)
        if not voice or voice["channel_id"] != self._channel_of(episode):
            raise KeyError(voice_id)
        return voice

    def channel_voice_file(self, episode_id: str, voice_id: str) -> Row:
        voice = self._channel_voice(self._episode(episode_id), voice_id)
        file = self.store.file(voice["preview_file"]) if voice["preview_file"] else None
        if file is None:
            raise KeyError(voice_id)
        return file

    async def preview_channel_voice(self, episode_id: str, voice_id: str) -> Row:
        """Generate one reusable sample on request for a voice saved in the episode's channel."""
        episode = self._episode(episode_id)
        self._channel_voice(episode, voice_id)
        gate = self._gates.setdefault(f"voice-preview:{voice_id}", asyncio.Semaphore(1))
        async with gate:
            voice = self._channel_voice(episode, voice_id)
            if not self._current_voice_preview(voice):
                from design_agent.tools.media import MediaKeys, speak

                said = await speak(
                    MediaKeys.from_settings(self.host.settings),
                    "Here’s how this voice sounds. A clear explanation starts with one good question.",
                    voice_id,
                    similarity_boost=CLONE_SIMILARITY,
                )
                if isinstance(said, str):
                    raise ValueError(said)
                file = self.host.save_file(
                    str(episode["thread_id"]),
                    self._voice_preview_name(voice_id),
                    said.audio,
                    origin="episode",
                )
                self.store.save_voice_preview(voice_id, str(file["id"]))
        return {"url": self._voice_preview_url(episode_id, voice_id)}

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
            samples.append((str(row["name"]), self.host.blobs.read(row)))
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
        channel_id = self._channel_of(episode)
        title = self._clone_title(name, consent)
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
        picked = await self._save_clone(channel_id, title, samples, noisy=noisy)
        episode = self._episode(episode_id)
        self.store.update_episode(
            episode_id,
            settings={
                **episode["settings"],
                "voice": "narrator",
                "narrator": picked,
                "cloned_voice": picked,
            },
        )
        self._say(
            episode,
            f"Cloned a voice with ElevenLabs, “{title}”, from {source}, having confirmed the "
            "voice is theirs to clone. It narrates the lines nobody recorded.",
            by=by,
        )
        self._settle(episode_id)
        return self.view(episode_id)

    async def clone_channel_voice(
        self, channel_id: str, *, name: str, consent: bool, sample: tuple[str, bytes]
    ) -> Row:
        """Save a channel voice from a recording before there is an episode to attach it to."""
        if self.store.channel(channel_id) is None:
            raise KeyError(channel_id)
        return await self._save_clone(channel_id, self._clone_title(name, consent), [sample])

    def _clone_title(self, name: str, consent: bool) -> str:
        if not self._speaks():
            raise ValueError("Cloning a voice needs ELEVENLABS_API_KEY.")
        if not consent:
            raise ValueError("Say that the voice is yours, or that its speaker agreed.")
        title = _clean(name, 60)
        if not title:
            raise ValueError("Give the voice a name.")
        return title

    async def _save_clone(
        self,
        channel_id: str,
        title: str,
        samples: Sequence[tuple[str, bytes]],
        *,
        noisy: bool = False,
    ) -> Row:
        from design_agent.tools.media import MediaKeys, clone_voice

        made = await clone_voice(
            MediaKeys.from_settings(self.host.settings), title, samples, noisy=noisy
        )
        if isinstance(made, str):
            raise ValueError(made)
        picked = self._clone_pick({"id": made.voice_id, "name": title, "verify": made.verify})
        self.store.add_voice_clone(channel_id, picked)
        self._listed = None
        return picked

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
                    "ended_at": time.time(),
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
        size = str((episode["film"] or {}).get("making") or "hd")
        computer = self._ready(episode)
        attempt = new_id("render")
        folder = f"{PROJECTS}/{episode_id}/{attempt}/film"
        kept = [t for t in self.store.takes(episode_id) if t["kept"]]
        spoken = self._voice(episode, full)
        clock = timeline.schedule(full, kept, spoken)
        self._room_for(computer, size, float(clock["total"]))
        media: list[tuple[str, bytes]] = []
        voice: dict[str, str] = {}
        for frame_id, said in spoken.items():
            row = self.store.file(str(said.get("file")))
            if row is not None:
                suffix = "wav" if said.get("mode") == "local" else "mp3"
                voice[frame_id] = f"voice/{frame_id.replace('.', '-')}.{suffix}"
                media.append(
                    (
                        f"{folder}/{voice[frame_id]}",
                        self.host.blobs.read(row),
                    )
                )

        # The takes wait on the thread's computer between renders: each is linked into the
        # film's folder, its copy for 4K in a film in 4K (a take with none is its HD one, scaled).
        def shown(take: Row) -> str:
            return "uhd" if size == "4k" and take.get("uhd") else "video"

        placed = self._in_sandbox(
            computer, episode, [(t, kind) for t in kept for kind in (shown(t), "audio")]
        )
        takes: dict[str, Row] = {}
        links: list[tuple[str, str]] = []
        upscaled = 0
        for take in kept:
            take_id = str(take["id"])
            entry: Row = {"video": "", "audio": ""}
            shows = shown(take)
            if size == "4k" and shows == "video" and (take_id, "video") in placed:
                upscaled += 1
            for kind, which, suffix in (("video", shows, "mp4"), ("audio", "audio", "m4a")):
                there = placed.get((take_id, which))
                if there is None:
                    continue
                path = f"takes/{take_id}.{suffix}"
                links.append((there, f"{folder}/{path}"))
                entry[kind] = path
            takes[take_id] = entry
        found = self._units(episode, full)
        rows = self.store.pictures(episode_id)
        blocked = self._render_blocked(rows, kept)
        if blocked:
            raise ValueError(blocked)
        look = self._look(episode)
        signature = self._film_sig(episode, full, rows, kept, look, clock)
        pictures = {
            p["unit"]: p["html"] for p in rows if p["html"] and p["status"] in ("made", "go")
        }
        files = film.project(
            full,
            clock,
            found,
            pictures,
            takes=takes,
            voice=voice,
            look=look,
            portrait=episode["settings"].get("portrait", "mira"),
        )
        pictured_frames = {
            frame for unit in found if unit["id"] in pictures for frame in unit["frames"]
        }
        cover_line = next(
            (line for line in clock["lines"] if line["frame"] in pictured_frames), clock["lines"][0]
        )
        cover_at = cover_line["start"] + cover_line["seconds"] * 0.8
        slug = (
            re.sub(r"[^a-z0-9]+", "-", str(episode["title"]).lower()).strip("-")[:48] or "episode"
        )
        thread_id = str(episode["thread_id"])
        poster = None
        try:
            computer.put(
                [(f"{folder}/{path}", text.encode()) for path, text in files.items()] + media
            )
            if links:
                linked = computer.run(
                    f"mkdir -p {folder}/takes && "
                    + " && ".join(
                        f"{{ ln -f {a} {b} 2>/dev/null || cp {a} {b}; }}" for a, b in links
                    ),
                    timeout=1800,
                )
                if not linked.ok:
                    raise ValueError(
                        "The takes couldn't be put beside the film: "
                        + _clean(linked.output[-200:], 200)
                    )
            setup = computer.run(
                f"mkdir -p {folder}/out && {episode_render.launch(folder, attempt, size)}",
                timeout=60,
            )
            if not setup.ok:
                raise ValueError(
                    "The renderer could not start: " + _clean(setup.output[-240:], 240)
                )
            started = time.monotonic()
            hours = 3 * (SLOWER_4K if size == "4k" else 1)
            while True:
                time.sleep(3.0)
                if self._closing:
                    return
                poll = computer.run(episode_render.probe(folder, attempt), timeout=60)
                if not poll.ok:
                    raise ValueError("Lost contact with the renderer. Retry the render.")
                state = poll.output.partition("\n")[0].strip()
                update = episode_render.progress(poll.output)
                current = self._episode(episode_id)["film"]
                if any(current.get(k) != v for k, v in update.items()):
                    self.store.update_episode(episode_id, film={**current, **update})
                    self._changed(episode_id)
                if state == "stopped":
                    raise ValueError("The renderer stopped before finishing. Retry the render.")
                if state != "running":
                    break
                if time.monotonic() - started > hours * 3600:
                    raise ValueError(f"The render took longer than {hours} hours.")

            def write(into: IO[bytes]) -> None:
                computer.get_into(f"{folder}/out/episode.mp4", into, timeout=4 * 3600)

            # Kept as the episode's own file: its card holds the film, and an earlier render
            # never lingers on the canvas as something delivered loose. A film in 4K runs to
            # gigabytes, so it is copied out as a file.
            try:
                if state != "0":
                    raise FileNotFoundError(folder)
                row = self.host.save_file_from(thread_id, f"{slug}.mp4", write, origin="episode")
            except FileNotFoundError:
                tail = computer.run(f"tail -5 {folder}/render.log").output
                raise ValueError(f"The render stopped: {_clean(tail[-300:])}") from None
            # A thumbnail failure must not discard a successfully rendered film.
            with contextlib.suppress(Exception):
                captured = computer.run(
                    f"ffmpeg -v error -ss {cover_at:.3f} -i {folder}/out/episode.mp4 "
                    f"-frames:v 1 -vf scale=640:-2 -q:v 3 {folder}/out/poster.jpg",
                    timeout=30,
                )
                if captured.ok:
                    poster = computer.get(f"{folder}/out/poster.jpg")
        finally:
            # Each attempt owns its scratch files. A retry cannot read another attempt's MP4.
            with contextlib.suppress(Exception):
                computer.run(f"rm -rf {PROJECTS}/{episode_id}/{attempt}", timeout=60)
        poster_id = None
        if poster:
            with contextlib.suppress(Exception):
                poster_id = self.host.save_file(
                    thread_id, f"{slug}-poster.jpg", poster, origin="episode"
                )["id"]
        episode = self._episode(episode_id)
        # The narration stays with the film: it is what the film's clock and signature were
        # made from, and a line already spoken is not paid for again at the next render.
        narration = (episode["film"] or {}).get("voice")
        self.store.update_episode(
            episode_id,
            film={
                **({"voice": narration} if narration else {}),
                "status": "done",
                "started_at": episode["film"]["started_at"],
                "ended_at": time.time(),
                "fraction": 1.0,
                "file": row["id"],
                "poster": poster_id,
                "sig": signature,
                "seconds": clock["total"],
                "size": size,
                "making": size,
                "upscaled": upscaled,
                "failure": "",
                "at": time.time(),
            },
        )
        self.host.file_asset(str(episode["asset_id"]), row)

    def _room_for(self, computer: Computer, size: str, seconds: float) -> None:
        """A render the thread's computer hasn't the room for is refused before it starts, with
        how much it needs: a film's frames are kept on its disk while it renders (a minute of
        film in 4K takes about 2.5 GB)."""
        need = int(seconds * SCRATCH[size]) + SCRATCH_FLOOR
        said = computer.run(
            "df -Pk /workspace /tmp 2>/dev/null | awk 'NR > 1 {print $4}'", timeout=60
        ).output
        free = [int(v) * 1024 for v in re.findall(r"^(\d+)$", said, re.M)]
        if free and min(free) < need:
            minutes = max(1, round(seconds / 60))
            raise ValueError(
                f"A {minutes}-minute film in {'4K' if size == '4k' else 'HD'} needs about "
                f"{_gb(need)} free on the render computer, which has {_gb(min(free))}. "
                "Free some space there (or give Docker more disk), then render again."
            )

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
            or any(key.startswith(f"import:{episode_id}:") for key in self._jobs)
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
                    self._unmade(episode_id, have["unit"], "Stopped when the house restarted.")
            if (episode["film"] or {}).get("status") == "rendering":
                self.store.update_episode(
                    episode_id,
                    film={
                        **episode["film"],
                        "status": "failed",
                        "ended_at": time.time(),
                        "failure": "Stopped when the house restarted.",
                    },
                )
            imports = episode.get("imports") or {}
            if any(entry.get("state") != "failed" for entry in imports.values()):
                # a recording half brought in is not a take: it is brought in again
                self.store.update_episode(
                    episode_id,
                    imports={
                        chapter: entry
                        if entry.get("state") == "failed"
                        else {
                            **entry,
                            "state": "failed",
                            "ended_at": time.time(),
                            "failure": "Stopped when the house restarted. Bring it in again.",
                        }
                        for chapter, entry in imports.items()
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
        poster = self._file(film_state.get("poster"))
        if not poster and film_state.get("file"):
            # Older exports have no captured poster. Use artwork that already exists.
            poster = self._file(
                next((fid for p in pictures for fid in (p["stills"] or {}).values() if fid), None)
            )
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
            "film": {
                **{
                    k: film_state.get(k)
                    for k in ("status", "fraction", "failure", "seconds", "size", "making")
                },
                "poster": poster,
            },
        }

    def cards(self, thread_id: str) -> list[dict[str, Any]]:
        return [self.card(e) for e in self.store.episodes(thread_id)]

    def view(self, episode_id: str) -> dict[str, Any]:
        """Everything the studio draws."""
        episode = self._episode(episode_id)
        thread = self.store.thread(str(episode["thread_id"]))
        full = self._full(episode)
        brand = self._brand_look(episode)
        look = self._look(episode, brand)
        found = self._units(episode, full, look) if full is not None else []
        pictures = {p["unit"]: p for p in self.store.pictures(episode_id)}
        said_now = {str(f["id"]): f for _, _, f in plans.frames_of(full or {})}
        kept = self._kept(episode_id)
        spoken = self._voice(episode, full or {})
        clock = timeline.schedule(full, kept, spoken) if full is not None else None
        if clock and spoken:
            for line in clock["lines"]:
                clip = spoken.get(line["frame"], {})
                if line["source"]["kind"] == "voice" and clip.get("file"):
                    line["audio_url"] = f"/api/files/{clip['file']}"
        film_state = {k: v for k, v in (episode["film"] or {}).items() if k != "voice"}
        picture_rows = list(pictures.values())
        film_state["blocked"] = self._render_blocked(picture_rows, kept)
        if full is not None and film_state.get("status") == "done":
            film_state["stale"] = film_state.get("sig") != self._film_sig(
                episode, full, picture_rows, kept, look, clock
            )
        film_state["file"] = self._file(film_state.get("file"))
        report = episode["report"] or {}
        changed = self.store.snapshot_note(episode_id)
        if changed and said_now:
            # A line has an entry iff one retained version differs from its current fields.
            remaining = _history_fields(episode["plan"] or {})
            for record in self.store.previous_plans(episode_id):
                previous = _history_fields(record["plan"])
                for fid in list(remaining):
                    if remaining[fid] != previous.get(fid, {}):
                        said_now[fid]["has_history"] = True
                        del remaining[fid]
                if not remaining:
                    break
        undone = self.store.snapshot_note(episode_id, "undone")
        said: dict[str, float] = {}
        for t in self.store.takes(episode_id):
            if t["kept"]:
                key = str(t["frame"] or t["chapter"])
                said[key] = max(said.get(key, 0.0), float(t["created_at"]))
        every = self.store.runs(str(episode["thread_id"]))
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
            for r in every
            if r["lane"]
        ]
        # The work under way, as it happens: the writer's steps and notes on the plan, newest
        # last, and for each picture being built the step its builder is on and its turn's own.
        live = next(
            (r for r in reversed(every) if r["lane"] == "plan" and r["state"] == "working"), None
        )
        doing: dict[str, str] = {}
        building: dict[str, Row] = {}
        turns: dict[str, list[Row]] = {}
        for r in every:
            lane = str(r["lane"])
            if lane.startswith("picture:"):
                turns.setdefault(lane.removeprefix("picture:"), []).append(r)
            if lane.startswith("picture:") and r["state"] == "working":
                doing[lane.removeprefix("picture:")] = _doing(r)
                building[lane.removeprefix("picture:")] = _live(
                    r, self.store.pulses.get(str(r["id"]))
                )
        return {
            **self.card(episode),
            "background": {
                "brand_color": brand.palette["ground"],
                "color": look.palette["ground"],
                "textures": picture.TEXTURES,
            },
            "channel_id": thread["channel_id"] if thread else "",
            "channel_voices": [
                {
                    **self._clone_pick(voice),
                    **(
                        {"preview": self._voice_preview_url(episode_id, voice["id"])}
                        if self._current_voice_preview(voice)
                        else {}
                    ),
                }
                for voice in self.store.channel_voice_clones(str(thread["channel_id"]))
            ]
            if thread
            else [],
            "settings": episode["settings"],
            "steps": [{"id": key, "label": label} for key, label in STEPS],
            "plan_stages": _plan_stages(
                episode["stage"] or {}, [r for r in every if r["lane"] == "plan"]
            ),
            "plan": full,
            "sample_notes": episode["material"]
            if episode["settings"].get("writer") == DEMO
            else None,
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
                    "picture": {
                        **self._picture_view(pictures.get(unit["id"]), unit, said_now),
                        "doing": doing.get(unit["id"], ""),
                        "live": building.get(unit["id"]),
                        **self._build_view(
                            episode_id, unit, pictures.get(unit["id"]), turns.get(unit["id"], [])
                        ),
                    },
                    "kind_of_picture": unit["picture"],
                }
                for unit in found
            ],
            "takes": [self._take_view(t) for t in self.store.takes(episode_id)],
            # recordings coming in for chapters, and the ones that could not be, with why
            "imports": [
                {"chapter": chapter, **entry}
                for chapter, entry in (episode.get("imports") or {}).items()
            ],
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
            # what the person's picks leave the writer, waiting for them to apply them
            # (a pick that needs a picture, a line added with one, or words a step no longer finds)
            "waiting": [
                {"line": str(x["where"]), "do": str(x["do"]), "kind": str(x.get("kind") or "pick")}
                for x in self._waiting(episode, full)
            ],
            # who builds each chapter's pictures: the agent picked for it, else the film's writer
            "builders": {
                str(c["id"]): self._chapter_builders(episode).get(
                    str(c["id"]), str(episode["settings"].get("writer") or "")
                )
                for c in (full or {}).get("chapters", [])
            },
            "runs": runs[-40:],
            "working": _live(live, self.store.pulses.get(str(live["id"]))) if live else None,
            "options": self.options(episode["settings"].get("writer")),
        }

    def _file(self, file_id: Any) -> dict[str, Any] | None:
        row = self.store.file(str(file_id)) if file_id else None
        return self.host.file_view(row) if row is not None else None

    def _build_view(
        self, episode_id: str, unit: Row, have: Row | None, turns: Sequence[Row]
    ) -> Row:
        """A picture's latest build as the studio follows it: its stages, how long it has taken
        in all, what its builder said when it reviewed the picture, and the notes the person
        left the builder, waiting or taken in."""
        key = (episode_id, str(unit["id"]))
        level = str((have or {}).get("level") or unit["level"])
        began = self._began.get(key) or _started(have)
        stages, reviewed = _stages(turns, have, level, began)
        return {
            "stages": stages,
            "timing": _timing_view(have, began),
            "reviewed": reviewed,
            "queued": [dict(note) for note in self._steer.get(key, [])],
            "steered": [dict(note) for note in self._steered.get(key, [])],
            "steerable": self._steerable(episode_id, str(unit["id"]), have),
        }

    def _picture_view(
        self, have: Row | None, unit: Row, lines: Mapping[str, Row] | None = None
    ) -> dict[str, Any]:
        if have is None:
            return {
                "status": "none",
                "level": "",
                "builder": "",
                "motion": None,
                "stills": {},
                "clip": None,
                "stale": False,
                "reworded": False,
                "made_for": {},
                "failure": "",
                "note": "",
                "version": 1,
                "versions": [],
            }
        return {
            "status": have["status"],
            "generation": have.get("generation") or None,
            # what it was built as (empty for one made before levels were kept), by whom, and
            # a rich one's motion plan
            "level": have["level"],
            "builder": have["builder"],
            "motion": have["motion"] or None,
            "stills": {
                frame: view
                for frame, file_id in (have["stills"] or {}).items()
                if (view := self._file(file_id)) is not None
            },
            "clip": self._file(have["clip"]),
            "stale": _outdated(have, unit),
            # made for words its lines no longer say: it may still fit, which is for the
            # person to say; they can keep it, have it planned again or drawn again. `made_for`
            # is what each changed line said when it was made.
            "reworded": (reworded := _reworded(have, unit)),
            "made_for": _made_for(have, unit, lines or {}) if reworded else {},
            "failure": have["failure"],
            "note": have["note"],
            # which version it is (or will be, while it is made), and the ones it stood as
            # before, the one it last stood as first, to look back at and to put back
            "version": have["version"],
            "versions": [self._version_view(kept) for kept in have.get("versions") or []],
        }

    def _version_view(self, kept: Row) -> Row:
        """A version kept to look back at and to put back, as the studio shows it: its number,
        its stills and its clip as files, how and by whom it was made, when, and how long its
        build took."""
        return {
            "n": kept["n"],
            "stills": {
                frame: view
                for frame, file_id in (kept["stills"] or {}).items()
                if (view := self._file(file_id)) is not None
            },
            "clip": self._file(kept["clip"]),
            "level": kept["level"],
            "builder": kept["builder"],
            "generation": kept["generation"] or None,
            "made_at": kept["made_at"],
            "seconds": (kept["timing"] or {}).get("seconds"),
        }

    def _take_view(self, take: Row) -> dict[str, Any]:
        return {
            "id": take["id"],
            "chapter": take["chapter"],
            "frame": take["frame"],
            "n": take["n"],
            "label": take.get("label", ""),
            "seconds": take["seconds"],
            "marks": take["marks"],
            "kept": take["kept"],
            "video": self._file(take["video"]),
            "audio": self._file(take["audio"]),
            # its copy for a film in 4K, for a recording taller than the film's frame
            "uhd": self._file(take.get("uhd")),
            # what it was and where it came from, and where it is kept as it arrived
            "recording": take.get("recording") or {},
            "kept_at": take.get("raw") or "",
            "created_at": take["created_at"],
        }

    # -- the production board: every episode's jobs, and handing them to agents ----------------

    def production(self) -> Row:
        """Everything the production board draws, across every episode of every channel: the
        agents (how busy each is, and how long a picture takes it), the episodes newest first,
        and the jobs: a picture of a plan in the studio, or a script that is being written,
        waits to be approved or stopped. It is read often and for the whole house, so it stays
        light: what an agent offers is asked once, a brand is read once, and only a turn under
        way has its runs read."""
        options = self.options()
        generation = _remembered(self._generation)
        channels = {str(c["id"]): str(c["name"]) for c in self.store.channels()}
        brands: dict[Path | str | None, picture.Look] = {}
        episodes: list[Row] = []
        jobs: list[Row] = []
        made: list[tuple[str, float, float]] = []
        for episode in reversed(self.store.all_episodes()):
            episodes.append(self._board_episode(episode, channels))
            pictures = self.store.pictures(str(episode["id"]))
            made += [
                (str(p["builder"]), float(timing["ended_at"]), float(timing["seconds"]))
                for p in pictures
                if p["status"] in ("made", "go")
                and (timing := p["timing"] or {}).get("seconds") is not None
            ]
            script = self._script_job(episode, generation)
            if script is not None:
                jobs.append(script)
            if episode["status"] == "studio":
                jobs += self._picture_jobs(episode, pictures, brands, generation)
        standing = Counter((job["agent"], job["state"]) for job in jobs)
        return {
            "agents": [
                {
                    "id": agent["id"],
                    "title": agent["title"],
                    "ready": agent["ready"],
                    "models": options["generation_models"][agent["id"]],
                    "running": standing[(agent["id"], "running")],
                    "waiting": standing[(agent["id"], "waiting")],
                    "seconds": _usual_seconds(made, agent["id"]),
                }
                for agent in options["picture_writers"]
            ],
            "episodes": episodes,
            "jobs": jobs,
        }

    def _board_episode(self, episode: Row, channels: Mapping[str, str]) -> Row:
        """An episode as the production board names it: its channel, where it stands, and its
        chapters once its plan has them."""
        thread = self.store.thread(str(episode["thread_id"])) or {}
        channel_id = str(thread.get("channel_id") or "")
        return {
            "id": episode["id"],
            "title": episode["title"],
            "channel_id": channel_id,
            "channel": channels.get(channel_id, ""),
            "status": episode["status"],
            "writer": str(episode["settings"].get("writer") or ""),
            "chapters": [
                {"id": c.get("id"), "n": n, "question": c.get("question", "")}
                for n, c in enumerate((episode["plan"] or {}).get("chapters", []), 1)
            ],
        }

    def _script_job(self, episode: Row, generation: Generation) -> Row | None:
        """An episode's script as a job, while it needs showing: being written (a first plan,
        or a turn on one that stands), written and waiting to be approved, or stopped. None for
        a plan in the studio with nothing under way."""
        episode_id = str(episode["id"])
        under_way = episode["status"] == "planning" or self.planning(episode_id)
        waits = {"plan": "go", "failed": "failed"}.get(str(episode["status"]))
        state = "running" if under_way else waits
        if state is None:
            return None
        stage = episode["stage"] or {}
        said = str(stage.get("said") or "")
        writer = str(episode["settings"].get("writer") or "")
        turns = self.store.runs(str(episode["thread_id"]), "plan") if under_way else []
        return _job(
            episode_id,
            "script",
            what="script",
            kind="script",
            state=state,
            agent=writer,
            **self._film_pick(episode, generation),
            failure=said if state == "failed" else "",
            doing=said,
            started_at=stage.get("at"),
            **self._liveness(_working(turns), writer),
        )

    def _picture_jobs(
        self,
        episode: Row,
        pictures: Sequence[Row],
        brands: dict[Path | str | None, picture.Look],
        generation: Generation,
    ) -> list[Row]:
        """A job for each picture of an episode's plan, in the film's order. `brands` keeps
        each brand's look as it is first read, for the episodes that wear it too."""
        full = self._full(episode)
        if full is None:
            return []
        root = self._brand_root(str(episode["thread_id"]))
        key = root.version if isinstance(root, BrandSnapshot) else root
        if key not in brands:
            brands[key] = self._brand_look(episode)
        look = self._look(episode, brands[key])
        have = {str(p["unit"]): p for p in pictures}
        # every line, with the number of its beat in its chapter
        lines = {
            str(f["id"]): (n, f)
            for ch in full.get("chapters", [])
            for n, b in enumerate(ch.get("beats", []), 1)
            for f in b.get("frames", [])
        }
        return [
            self._picture_job(episode, unit, have.get(str(unit["id"])), lines)
            for unit in self._units(episode, full, look, generation)
            if unit["kind"] == "picture"
        ]

    def _picture_job(
        self, episode: Row, unit: Row, have: Row | None, lines: Mapping[str, tuple[int, Row]]
    ) -> Row:
        """One picture as a job: where it stands, who it is set to (or, once made, who made
        it), and its latest build as the studio follows one."""
        episode_id, unit_id = str(episode["id"]), str(unit["id"])
        stale = have is not None and (_outdated(have, unit) or _reworded(have, unit))
        state = "todo" if stale else JOB_STATES[str(have["status"]) if have else "none"]
        on_its_way = state in ("waiting", "running")
        # only a build under way has turns worth reading: they say which stage it is at
        lane = f"picture:{unit_id}"
        turns = self.store.runs(str(episode["thread_id"]), lane) if state == "running" else []
        turn = _working(turns)
        build = self._build_view(episode_id, unit, have, turns)
        timing = build["timing"] or {}
        agent, on = str(unit["builder"]), unit["model_now"]
        if have is not None and state in ("go", "done"):
            # one made before its builder was kept is shown as its beat is set
            agent, on = str(have["builder"] or agent), have["generation"] or unit["generation"]
        still = self._file(((have or {}).get("stills") or {}).get(unit["frames"][-1]))
        return _job(
            episode_id,
            unit_id,
            what="picture",
            unit=unit_id,
            chapter=unit["chapter"],
            kind=unit["picture"],
            shows=unit["shows"],
            says=_clean(str(lines[unit["frames"][0]][1].get("vo") or ""), 160),
            beats=list(dict.fromkeys(lines[frame][0] for frame in unit["frames"])),
            lines=len(unit["frames"]),
            level=unit["level"],
            state=state,
            stale=stale,
            agent=agent,
            model=on["model"],
            effort=on["effort"],
            picked=bool(unit["builder_pick"]),
            failure=have["failure"] if have else "",
            stage=next((s["id"] for s in build["stages"] if s["state"] == "running"), ""),
            doing=_doing(turn) if turn else "",
            asked_at=self._asked.get((episode_id, unit_id)) if on_its_way else None,
            started_at=timing.get("started_at"),
            ended_at=timing.get("ended_at"),
            seconds=timing.get("seconds"),
            still=still["url"] if still else None,
            **self._liveness(turn, agent),
        )

    def _liveness(self, turn: Row | None, agent: str) -> Row:
        """A job's signs of life: whether its agent says what its model is doing as it goes
        and, while a turn of it is under way, the turn's pulse and when it was last heard from
        (the newest of its start, its last event and its pulse). A turn that has said nothing
        yet was heard from when it began, so a time is missing only when no turn is under way."""
        if turn is None:
            return {"tells": _tells(agent), "heard_at": None, "pulse": None}
        live = _live(turn, self.store.pulses.get(str(turn["id"])))
        heard = [float(live["since"])]
        heard += [float(event["at"]) for event in live["events"][-1:] if event["at"]]
        if live["pulse"]:
            heard.append(float(live["pulse"]["at"]))
        return {"tells": live["tells"], "heard_at": max(heard), "pulse": live["pulse"]}

    def assign(
        self,
        jobs: Sequence[tuple[str, str]],
        *,
        by: str,
        agent: str = "",
        model: str = "",
        effort: str = "",
        start: bool = True,
    ) -> Row:
        """Hand pictures, each named by its episode and unit, to an agent, and start them.
        With a model or an effort every picture gets the agent on those as its own pick. With
        neither, one already with that agent keeps what it runs on, and one with another agent
        moves to this one's default. With no agent each keeps the one it is set to. With
        `start` they are then asked for by name, as `make` asks: one made and up to date is
        left as it is. An episode that refuses says why and does not stop the others. Returns
        the jobs this started and the refusals."""
        if not jobs:
            raise ValueError("There is no picture to hand over.")
        if agent and not self._can_write(agent):
            raise ValueError("That agent isn't ready on this computer.")
        if agent and (model or effort):
            # a pick the agent does not offer is refused here, once, not by every episode
            self._generation(agent, {"model": model, "effort": effort})
        named: dict[str, list[str]] = {}
        for episode_id, unit_id in dict.fromkeys(jobs):
            named.setdefault(episode_id, []).append(unit_id)
        started: list[str] = []
        refused: list[Row] = []
        for episode_id, unit_ids in named.items():
            try:
                picks = self._handed(episode_id, unit_ids, agent, model, effort)
                if picks:
                    self.choose(episode_id, by=by, change={"units": picks})
                if start:
                    started += self._make_named(episode_id, unit_ids, by=by)
            except KeyError:
                refused.append({"episode": episode_id, "reason": "That episode is no longer here."})
            except ValueError as refusal:
                refused.append({"episode": episode_id, "reason": str(refusal)})
        return {"started": started, "refused": refused}

    def _handed(
        self, episode_id: str, unit_ids: Sequence[str], agent: str, model: str, effort: str
    ) -> Row:
        """The picks that hand an episode's pictures to an agent (see `assign`), by unit."""
        if not agent:
            return {}
        if model or effort:
            return dict.fromkeys(unit_ids, {"builder": agent, "model": model, "effort": effort})
        episode = self._episode(episode_id)
        theirs = {
            str(unit["id"])
            for unit in self._units(episode, self._full(episode) or {})
            if unit["builder"] == agent
        }
        return {unit_id: {"builder": agent} for unit_id in unit_ids if unit_id not in theirs}

    def _make_named(self, episode_id: str, unit_ids: Sequence[str], *, by: str) -> list[str]:
        """Ask for an episode's pictures by name (`make`). Returns, as jobs, the ones this
        started: one already on its way was not, and neither was one `make` left as it is."""
        before = {unit_id for unit_id in unit_ids if self._building(episode_id, unit_id)}
        self.make(episode_id, by=by, only=list(unit_ids))
        return [
            f"{episode_id}:{unit_id}"
            for unit_id in unit_ids
            if unit_id not in before and self._building(episode_id, unit_id)
        ]

    def _building(self, episode_id: str, unit_id: str) -> bool:
        """Whether a build of a picture is under way, one waiting its turn included."""
        build = self._builds.get((episode_id, unit_id))
        return build is not None and not build.done()


def _outdated(have: Row, unit: Row) -> bool:
    """Whether a made picture no longer fits its unit: drawn from the plan as it was, or at
    another level. One made before levels were kept is judged by what it was drawn from."""
    if have["status"] not in ("made", "go"):
        return False
    built_as = str(have["level"] or "")
    previous = have.get("generation") or {}
    if previous.get("catalog_version", catalog.CATALOG_VERSION) != catalog.CATALOG_VERSION:
        return True
    if (
        have.get("builder") == DEMO
        and unit.get("visual", {}).get("component") in catalog.ILLUSTRATED
        and previous.get("drawing_version", 1) != catalog.DRAWING_VERSION
    ):
        return True
    theme = previous.get("theme_sig")
    return (
        not units.same(str(have["sig"]), unit)
        or (bool(built_as) and built_as != unit["level"])
        or bool(theme and theme != unit.get("theme_sig"))
        or bool(not theme and unit.get("custom_background"))
    )


def _said(lines: Sequence[Row]) -> str:
    """What a picture's lines say, line by line, as it is kept beside the picture: one run of
    spaces, so spacing alone is never a change."""
    return json.dumps(
        {str(f.get("id")): " ".join(str(f.get("vo") or "").split()) for f in lines if f},
        sort_keys=True,
        ensure_ascii=False,
    )


def _reworded(have: Row, unit: Row) -> bool:
    """Whether a made picture was made for words its lines no longer say; words put back as
    they were make it current again. One made before its words were kept is judged by when a
    person last changed one of its lines."""
    if have["status"] not in ("made", "go"):
        return False
    if str(have["words"] or "").startswith("{"):
        return str(have["words"]) != str(unit["words_now"])
    return float(unit.get("reworded_at") or 0.0) > float(have["updated_at"] or 0.0)


def _made_for(have: Row, unit: Row, lines: Mapping[str, Row]) -> dict[str, str]:
    """The words a picture was made for, for each of its lines that says something else now.
    One made before its words were kept is shown against the words its lines had before a
    person changed them."""
    now = json.loads(unit["words_now"])
    if str(have["words"] or "").startswith("{"):
        then = json.loads(have["words"])
        return {k: str(v) for k, v in then.items() if k in now and now[k] != v}
    out: dict[str, str] = {}
    for frame in unit["frames"]:
        mark = (lines.get(str(frame)) or {}).get("by_person") or {}
        if mark and " ".join(str(mark.get("was") or "").split()) != now.get(str(frame)):
            out[str(frame)] = str(mark.get("was") or "")
    return out


def _guides(skill: str) -> str:
    """Where HyperFrames' own guides are for a builder, beside the episode skill it was given:
    a copy in its folder for a coding agent on this computer, the vendored skill for the
    engine's agent."""
    if skill.startswith("/skills/"):
        return "/skills/hyperframes/references"
    return f"{skill}/hyperframes"


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


def _craft_notes(report: str) -> list[str]:
    """What the renderer's craft pass flags in a picture, each as one line with where it is."""
    section = ""
    notes: list[str] = []
    for raw in report.splitlines():
        line = raw.strip()
        if line in CHECK_SECTIONS:
            section = line
            continue
        if section != "Craft":
            continue
        found = CRAFT_NOTE.match(line)
        if found is not None:
            if found.group(1) not in CRAFT_SKIPPED:
                notes.append(f"{found.group(1)}: {found.group(2).strip()[:300]}")
            else:
                notes.append("")
        elif notes and line and not line.startswith(("◇", "0 error")) and "error(s)" not in line:
            # the line under a finding says where and when it is, or how to fix it
            if notes[-1]:
                notes[-1] += f" ({line[:160]})"
    return [note for note in notes if note][:12]


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


def _line_words(text: str) -> str:
    """A person's words for one line, in one run of spaces."""
    words = " ".join(str(text).split())
    if not words:
        raise ValueError("A line needs words. To drop it, cut it.")
    if len(words) > 700:
        raise ValueError("That is long for one line. Ask for the chapter to be changed.")
    return words


def _follow(merged: Row, frames: Sequence[str]) -> None:
    """How each of `frames` follows the line before it now that the lines around it changed,
    where who has the two frames settles it. A reading of the two pictures stays as it was,
    unless it was the person and the content changing places, which they no longer do: then
    one picture follows another as a new one, on a cut."""
    order = [f for _, _, f in plans.frames_of(merged)]
    for k, f in enumerate(order):
        if f["id"] not in frames or not f.get("_designed"):
            continue
        settled = classify.follows(order[k - 1] if k else None, f)
        if settled is None and f.get("relation") == "swap":
            settled = "new-topic", str(WAYS_BY_RELATION["new-topic"])
        if settled is not None:
            f["relation"], f["transition"] = settled


def _turn_stage(prompt: str) -> str:
    """The stage of a picture builder's turn, read from how its own prompt opens (after the
    earlier turns an agent without a session of its own is retold)."""
    asked = asked_now(prompt)
    return next((stage for opening, stage in TURN_STAGES if asked.startswith(opening)), "")


def _stages(
    turns: Sequence[Row], have: Row | None, level: str, began: float | None
) -> tuple[list[Row], str]:
    """A picture's latest build, stage by stage, from its builder's turns on it: when each
    stage began and ended, how it stands (pending, running, done, failed, or waiting on the
    person), and what the builder said when it reviewed the picture. The stills between the
    drawing and the review are the house's own: they begin when the drawing ends. While a build
    is under way only the turns since it began count; otherwise the build is the one opened by
    the latest turn that plans or draws the picture."""
    status = str((have or {}).get("status") or "none")
    if status == "none":
        return [], ""
    own = sorted(
        (r for r in turns if _turn_stage(str(r["prompt"]))),
        key=lambda r: float(r["started_at"] or 0.0),
    )
    if status == "queued":
        own = []
    elif began is not None:
        # a build that ended is the turns it ran: a version put back is not read with the turns
        # of a later build that did not land
        ended = float(((have or {}).get("timing") or {}).get("ended_at") or "inf")
        own = [r for r in own if began <= float(r["started_at"] or 0.0) <= ended]
    else:
        opening = BUILD_OPENINGS.get(level, BUILD_OPENINGS[units.SIMPLE])
        opened = [i for i, r in enumerate(own) if asked_now(str(r["prompt"])).startswith(opening)]
        own = own[opened[-1] :] if opened else []
    spans: dict[str, list[Row]] = {}
    for r in own:
        spans.setdefault(_turn_stage(str(r["prompt"])), []).append(r)
    out: list[Row] = []
    for stage in BUILD_STAGES.get(level, BUILD_STAGES[units.SIMPLE]):
        runs = spans.get(stage, [])
        row: Row = {"id": stage, "state": "pending", "started_at": None, "ended_at": None}
        if runs:
            row["started_at"] = runs[0]["started_at"]
            if any(r["state"] == "working" for r in runs):
                row["state"] = "running"
            else:
                row["ended_at"] = runs[-1]["ended_at"]
                failed = runs[-1]["state"] in ("failed", "stopped")
                row["state"] = "failed" if failed else "done"
        out.append(row)
    by_id = {r["id"]: r for r in out}
    draw, pose, review, go = (by_id.get(k) for k in ("draw", "pose", "review", "go"))
    if draw is not None and pose is not None and draw["state"] == "done":
        pose["started_at"] = draw["ended_at"]
        if review is not None and review["started_at"] is not None:
            pose["state"], pose["ended_at"] = "done", review["started_at"]
        elif status in ("go", "made"):
            pose["state"] = "done"
    if go is not None:
        go["state"] = "waiting" if status == "go" else "done" if status == "made" else "pending"
    if status in ("making", "posing") and not any(r["state"] == "running" for r in out):
        # between two turns the house works on its own: the first stage not done is under way
        upcoming = next((r for r in out if r["state"] == "pending" and r["id"] != "go"), None)
        if upcoming is not None:
            upcoming["state"] = "running"
    if status == "failed" and not any(r["state"] == "failed" for r in out):
        # the build stopped in the first stage it did not finish
        stopped = next((r for r in out if r["state"] in ("running", "pending")), None)
        if stopped is not None:
            stopped["state"] = "failed"
    reviewed = ""
    if review is not None and review["state"] == "done":
        # said as markdown; shown as plain words
        said = re.sub(r"\*\*|__|`", "", str(spans["review"][-1]["answer"] or ""))
        reviewed = _clean(said, 400)
    return out, reviewed


#: The stages a plan is written in, as its page times them.
PLAN_STAGES = ("brief", "script", "frames")


def _plan_stages(stage: Row, turns: Sequence[Row]) -> list[Row]:
    """The plan's stages as its page follows them, each with when it began and ended and how
    it stands. A stage begins when the house moves to it and ends when the next one begins;
    checking the plan is the house's own reading after the writer's last turn. A plan written
    before the house logged its stages has none."""
    began: dict[str, float] = {}
    order: list[str] = []
    for entry in stage.get("log") or []:
        name = str(entry.get("name") or "")
        if name in (*PLAN_STAGES, "done") and name not in began:
            began[name] = float(entry["at"])
            order.append(name)
    if not any(name in began for name in PLAN_STAGES):
        return []
    stopped = stage.get("state") == "stopped"
    out: list[Row] = []
    for key in PLAN_STAGES:
        row: Row = {"id": key, "state": "pending", "started_at": began.get(key), "ended_at": None}
        if key in began:
            after = order[order.index(key) + 1 :]
            row["ended_at"] = began[after[0]] if after else None
            row["state"] = "done" if after else "failed" if stopped else "running"
        out.append(row)
    check: Row = {"id": "check", "state": "pending", "started_at": None, "ended_at": None}
    if "done" in began and "frames" in began:
        ends = [
            float(t["ended_at"])
            for t in turns
            if t.get("ended_at") and float(t["started_at"] or 0.0) >= began["frames"]
        ]
        # the writer's frames end with its last turn; the house's checks run on from there
        last = min(max(ends), began["done"]) if ends else began["done"]
        out[-1]["ended_at"] = last
        check.update(state="done", started_at=last, ended_at=began["done"])
    out.append(check)
    return out


def _kept_version(have: Row | None) -> Row | None:
    """A made picture as a version to keep: its number, when it was made, and all it needs to
    stand again as it was made. None for a picture that was not made."""
    if have is None or have["status"] not in ("made", "go") or not have["html"]:
        return None
    return {
        "n": int(have["version"]),
        "made_at": (have["timing"] or {}).get("ended_at") or have["updated_at"],
        **{key: have[key] for key in VERSION_KEEPS},
    }


def _standing(kept: Row) -> Row:
    """A kept version as the picture's own record, to stand again."""
    return {"version": kept["n"], **{key: kept[key] for key in VERSION_KEEPS}}


def _started(have: Row | None) -> float | None:
    """When a picture's latest build began, as its beat's record dates it."""
    began = ((have or {}).get("timing") or {}).get("started_at")
    return float(began) if began else None


def _timing(began: float, ended: float, stages: Sequence[Row]) -> Row:
    """A build's times as the beat keeps them: when it began and ended, how long it took in
    all, and each of its own stages (the go is the person's) with its times and how long it
    took."""

    def took(stage: Row) -> float | None:
        start, end = stage.get("started_at"), stage.get("ended_at")
        return round(float(end) - float(start), 1) if start and end else None

    return {
        "started_at": began,
        "ended_at": ended,
        "seconds": round(ended - began, 1),
        "stages": [
            {
                "id": s["id"],
                "state": s["state"],
                "started_at": s["started_at"],
                "ended_at": s["ended_at"],
                "seconds": took(s),
            }
            for s in stages
            if s["id"] != "go"
        ],
    }


def _timing_view(have: Row | None, began: float | None) -> Row | None:
    """How long a picture's latest build has taken in all: while it runs, the time it began, so
    the clock runs on from stage to stage; once it ends, as the beat's record keeps it."""
    status = str((have or {}).get("status") or "none")
    if status in ("none", "queued"):
        return None
    if status in ("making", "posing"):
        return {"started_at": began, "ended_at": None, "seconds": None} if began else None
    kept = (have or {}).get("timing") or {}
    if not kept.get("ended_at"):
        return None
    return {key: kept[key] for key in ("started_at", "ended_at", "seconds")}


def _live(run: Row, pulse: Row | None = None) -> Row:
    """A turn under way as the studio follows it: who runs it, since when, its newest steps,
    notes (the agent's own words) and stretches of thinking, newest last, and what its model is
    doing now between two of them (`Store.pulse`). `tells` is whether this agent says that as
    it goes: from one that does, a long silence is a sign that something is wrong."""
    told = [e for e in (run["steps"] or []) if e.get("text") or e.get("kind") == "thought"]
    return {
        "harness": run["harness"],
        "since": run["started_at"],
        "tells": _tells(str(run["harness"])),
        "pulse": {k: v for k, v in pulse.items() if k != "lane"} if pulse else None,
        "events": [
            {
                "kind": e.get("kind"),
                "text": _clean(str(e.get("text") or ""), 400),
                "at": e.get("at"),
                **({"seconds": e.get("seconds") or 0} if e.get("kind") == "thought" else {}),
            }
            for e in told[-14:]
        ],
    }


def _tells(agent: str) -> bool:
    """Whether an agent says what its model is doing between its steps as it goes."""
    harness = research.HARNESSES.get(agent)
    return bool(harness and harness.tells) or agent == DEMO


def _doing(run: Row) -> str:
    """The step a turn under way is on: its newest step or note, never a stretch of thinking."""
    last = next(
        (e for e in reversed(run["steps"] or []) if e.get("text") and e.get("kind") != "thought"),
        None,
    )
    return _clean(str(last["text"]), 120) if last else ""


def _working(turns: Sequence[Row]) -> Row | None:
    """The newest of a lane's turns that is under way, if one is."""
    return next((r for r in reversed(turns) if r["state"] == "working"), None)


def _job(episode_id: str, name: str, *, what: str, kind: str, state: str, **known: Any) -> Row:
    """A job as the production board lists it: what this one says of itself, with everything
    it does not say left empty, so every job has the same fields."""
    return {
        "id": f"{episode_id}:{name}",
        "what": what,
        "episode": episode_id,
        "unit": "",
        "chapter": "",
        "kind": kind,
        "shows": "",
        "says": "",
        "beats": [],
        "lines": 0,
        "level": "",
        "state": state,
        "stale": False,
        "agent": "",
        "model": "",
        "effort": "",
        "picked": False,
        "failure": "",
        "stage": "",
        "doing": "",
        "asked_at": None,
        "started_at": None,
        "ended_at": None,
        "seconds": None,
        "still": None,
        "tells": False,
        "heard_at": None,
        "pulse": None,
        **known,
    }


def _usual_seconds(made: Sequence[tuple[str, float, float]], agent: str) -> float | None:
    """How long a picture takes an agent to build: the mean over its newest made ones, or None
    when it has made none. `made` is every made picture's builder, when its build ended and how
    long that took."""
    newest = sorted((ended, took) for by, ended, took in made if by == agent)[-BUILDS_MEANT:]
    return round(sum(took for _, took in newest) / len(newest), 1) if newest else None


def _remembered(ask: Generation) -> Generation:
    """`ask` with every answer kept, for one read of the whole house: an agent is asked what a
    pick builds on once, however many pictures share the pick. A pick it refuses is not kept."""
    known: dict[tuple[str, str, str], Row] = {}

    def asked(builder: str, pick: Row) -> Row:
        key = (builder, str(pick.get("model") or ""), str(pick.get("effort") or ""))
        if key not in known:
            known[key] = ask(builder, pick)
        return dict(known[key])

    return asked


def _history_fields(plan: Row, frame: str | None = None) -> dict[str, dict[str, str]]:
    """The displayed fields, keyed by stable line ID, for both the picker and its detail view."""
    lines = {}
    for _, _, line in plans.frames_of(plans.merged(plan, {})):
        if frame is not None and line["id"] != frame:
            continue
        values = {
            "Transcript": str(line.get("vo") or ""),
            "Visual direction": str(line.get("shows") or ""),
        }
        if line.get("hold"):
            values["Layout"] = "Continue the preceding picture"
        if line.get("focal"):
            values["Focus"] = str(line["focal"])
        for i, obj in enumerate(line.get("objects") or []):
            label = str(obj.get("id") or i + 1).replace("_", " ")
            values[f"Object · {label}"] = " · ".join(
                f"{key}: {value}" for key, value in obj.items() if key != "id"
            )
        for i, cue in enumerate(line.get("cues") or []):
            values[f"Cue {i + 1}"] = " · ".join(f"{key}: {value}" for key, value in cue.items())
        lines[line["id"]] = {key: value for key, value in values.items() if value}
    return lines


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
