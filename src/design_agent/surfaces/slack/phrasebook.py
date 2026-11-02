"""What each step is called in the thread: a studio phrase per tool call, in both tenses.

A step card reads like a design studio at work ("Opening the storyboard playbook", "Studying the
brand book", "Rolling the render") rather than an agent narrating syscalls. A card needs two
tenses, so every phrase is a pair: what the step is doing while it runs, and what it did.

It is deterministic and grows without an entry per tool:

- **Built-in tools** (`read_file`, `grep`, `execute`, ...) are phrased from their arguments, and a
  path becomes a place: a skill is its playbook, `/workspace/brand` is the brand book, a person's
  memory is their preferences, and any other file is named by its kind (an image, the
  composition, a script).
- **This repository's host tools** have an entry each.
- **MCP tools** (`{server}_{tool}`, for the servers the caller names) read as their real name:
  the name is parsed (snake, kebab or CamelCase) for its verb and what it acts on, the server
  repeating itself is dropped, and the verb is put in both tenses with the service after it:
  `paper_write_html` is "Writing HTML in Paper". A server that adds a tool needs nothing here.
- **Other tools** are parsed the same way, without a service; a name with no verb in it is that
  name, humanized.

What a phrase may carry: a card is posted before anyone reviews it, so a phrase never carries
argument text (no path, file id, query or anybody's words). The names it shows are this
repository's own (a skill's directory) and the service a tool reaches.
"""

from __future__ import annotations

import logging
import posixpath
import re
from collections.abc import Callable, Iterable, Mapping

_LOGGER = logging.getLogger(__name__)

Phrase = tuple[str, str]
Args = Mapping[str, object]

_WS = "/workspace"

#: Services a server name reads as, when the caller gives no name of its own.
KNOWN_SERVICES: Mapping[str, str] = {"paper": "Paper", "exa": "the web", "github": "GitHub"}
#: Most work happens *in* a service; the web is worked *on*.
_ON = frozenset({"exa"})

#: Places under the workspace with a studio name, and what kind of place each is.
_PLACES: tuple[tuple[str, str, str], ...] = (
    (f"{_WS}/brand", "the brand book", "library"),
    (f"{_WS}/references", "the reference shelf", "library"),
    (f"{_WS}/fonts", "the brand fonts", "other"),
    (f"{_WS}/tools", "the toolkit", "other"),
    (f"{_WS}/.renders", "the render log", "other"),
)

#: A file nobody has a studio name for is named by what it is.
_KINDS = {
    ".html": "the composition",
    ".css": "the styles",
    ".md": "the notes",
    ".txt": "the notes",
    ".json": "the data",
    ".toml": "the settings",
    ".csv": "a table",
    ".png": "an image",
    ".jpg": "an image",
    ".jpeg": "an image",
    ".webp": "an image",
    ".gif": "an image",
    ".svg": "a graphic",
    ".d2": "the diagram",
    ".mp4": "a video",
    ".mov": "a video",
    ".webm": "a video",
    ".mp3": "the audio",
    ".wav": "the audio",
    ".pdf": "a PDF",
    ".py": "a script",
    ".js": "a script",
    ".mjs": "a script",
    ".ts": "a script",
    ".sh": "a script",
    ".log": "the render log",
}


def _words(name: str) -> str:
    """`launch-film` -> `launch film`: a directory name read aloud."""
    return re.sub(r"[-_]+", " ", name).strip()


def _norm(path: object) -> str:
    raw = str(path or "").strip()
    if not raw:
        return ""
    return posixpath.normpath(raw if raw.startswith("/") else f"{_WS}/{raw}")


def _skill(path: str) -> str:
    """The skill a path belongs to: MDA's read-only mount, or the staged workspace copy."""
    found = re.match(rf"^(?:{_WS})?/skills/([^/]+)", path)
    return found.group(1) if found else ""


def _place(path: str) -> tuple[str, str]:
    """A path as a studio place, and which kind of place it is."""
    if not path:
        return "the workspace", "other"
    if skill := _skill(path):
        return f"the {_words(skill)} playbook", "skill"
    if path.startswith("/memories/user"):
        return "your preferences", "memory"
    if path.startswith("/memories"):
        return "the studio's notes", "memory"
    for prefix, name, kind in _PLACES:
        if path == prefix or path.startswith(f"{prefix}/"):
            return name, kind
    if path == f"{_WS}/attachments":
        return "your files", "inbound"
    if path.startswith(f"{_WS}/attachments/"):
        return "your file", "inbound"
    named = _KINDS.get(posixpath.splitext(path)[1].lower())
    if named:
        return named, "file"
    if path.startswith(f"{_WS}/projects"):
        return "the project", "other"
    return "a file", "other"


def _read(args: Args) -> Phrase:
    place, kind = _place(_norm(args.get("file_path") or args.get("path")))
    if kind == "skill":
        return f"Opening {place}", f"Opened {place}"
    if kind == "library":
        return f"Studying {place}", f"Studied {place}"
    if kind == "memory":
        return f"Checking {place}", f"Checked {place}"
    return f"Reading {place}", f"Read {place}"


def _write(args: Args) -> Phrase:
    place, kind = _place(_norm(args.get("file_path") or args.get("path")))
    if kind == "memory":
        return f"Updating {place}", f"Updated {place}"
    return f"Drafting {place}", f"Drafted {place}"


def _edit(args: Args) -> Phrase:
    place, kind = _place(_norm(args.get("file_path") or args.get("path")))
    if kind == "memory":
        return f"Updating {place}", f"Updated {place}"
    return f"Reworking {place}", f"Reworked {place}"


def _browse(args: Args) -> Phrase:
    path = _norm(args.get("path"))
    if not path or path == _WS:
        return "Looking around the studio", "Looked around the studio"
    place, _ = _place(path)
    return f"Browsing {place}", f"Browsed {place}"


def _grep(args: Args) -> Phrase:
    path = _norm(args.get("path"))
    place, _ = _place(path) if path and path != _WS else ("the workspace", "other")
    return f"Digging through {place}", f"Dug through {place}"


#: A command's programs -> what the studio is doing; the first match in this order wins, so
#: `npx hyperframes render` is a render, not "wiring up the build".
_COMMANDS: tuple[tuple[tuple[str, ...], Phrase], ...] = (
    (("hyperframes",), ("Rolling the render", "Rolled the render")),
    (("ffmpeg",), ("Cutting the footage", "Cut the footage")),
    (("ffprobe",), ("Inspecting the footage", "Inspected the footage")),
    (("d2",), ("Drawing the diagram", "Drew the diagram")),
    (("chromium", "chromium-browser", "playwright"), ("Shooting stills", "Shot stills")),
    (("magick", "convert", "vips", "sharp"), ("Touching up the image", "Touched up the image")),
    (("fc-match", "fc-list", "fc-cache"), ("Checking the fonts", "Checked the fonts")),
    (("npx", "npm", "node", "pnpm", "yarn", "bun"), ("Wiring up the build", "Wired up the build")),
    (("python", "python3", "uv", "pip"), ("Running a script", "Ran a script")),
    (
        ("ls", "cat", "find", "head", "tail", "pwd", "echo", "stat", "du", "file", "wc"),
        ("Looking around the studio", "Looked around the studio"),
    ),
    (("git",), ("Checking the version history", "Checked the version history")),
    (("curl", "wget"), ("Pulling a reference", "Pulled a reference")),
)
#: A step that checks the work: a gate script (a lint, a probe, a score) or a HyperFrames check.
_CHECK = re.compile(r"(lint|gate|check|score|probe|verify|validate)")
_HYPERFRAMES_CHECKS = frozenset({"lint", "validate", "inspect", "doctor"})
_SCRIPTS = (".mjs", ".js", ".py", ".sh")


def _execute(args: Args) -> Phrase:
    command = str(args.get("command") or args.get("cmd") or "")
    tokens = [
        posixpath.basename(token).lower() for token in re.split(r"[\s;&|()]+", command) if token
    ]
    checking = any(_CHECK.search(token) for token in tokens if token.endswith(_SCRIPTS))
    if checking or ("hyperframes" in tokens and _HYPERFRAMES_CHECKS & set(tokens)):
        return "Checking the work", "Checked the work"
    if "hyperframes" in tokens and "snapshot" in tokens:
        return "Shooting stills", "Shot stills"
    for programs, found in _COMMANDS:
        if any(token in programs for token in tokens):
            return found
    return "Working in the sandbox", "Worked in the sandbox"


def _upload(args: Args) -> Phrase:
    paths = args.get("paths") or args.get("sandbox_paths")
    if isinstance(paths, list) and len(paths) > 1:
        return "Sending the files over", "Sent the files over"
    return "Sending it over", "Sent it over"


def _look(args: Args) -> Phrase:
    paths = args.get("paths")
    if isinstance(paths, list) and len(paths) > 1:
        return "Looking over the frames", "Looked over the frames"
    return "Taking a look", "Took a look"


#: Tools phrased from their arguments.
_BUILT: dict[str, Callable[[Args], Phrase]] = {
    "read_file": _read,
    "write_file": _write,
    "edit_file": _edit,
    "ls": _browse,
    "grep": _grep,
    "execute": _execute,
    "upload_files": _upload,
    "look": _look,
}

#: Tools phrased by name alone: this repository's host tools and deepagents' fixed ones.
_NAMED: dict[str, Phrase] = {
    "write_todos": ("Planning the work", "Planned the work"),
    "glob": ("Scouting for files", "Scouted for files"),
    "task": ("Bringing in a helper", "Brought in a helper"),
    "start_task": ("Putting a helper on it", "Put a helper on it"),
    "check_tasks": ("Checking on the background work", "Checked on the background work"),
    "cancel_task": ("Stopping a background job", "Stopped a background job"),
    "resume_task": ("Picking a background job back up", "Picked a background job back up"),
    "schedule_wakeup": ("Setting a check-in", "Set a check-in"),
    "steer_task": ("Passing your notes on", "Passed your notes on"),
    "report_progress": ("Reporting back", "Reported back"),
    "start_render_job": ("Starting the render", "Started the render"),
    "watch_progress": ("Keeping an eye on the job", "Kept an eye on the job"),
    "stop_watch": ("Stopping the watch", "Stopped the watch"),
    "run_pipeline": ("Starting the pipeline", "Started the pipeline"),
    "answer_pipeline": ("Passing your answer on", "Passed your answer on"),
    "start_looks": ("Exploring directions", "Explored directions"),
    "pick_look": ("Merging the chosen look", "Merged the chosen look"),
    "save_observations": ("Noting what this job taught", "Noted what this job taught"),
    "read_observations": ("Reading past lessons", "Read past lessons"),
    "rate_observation": ("Rating a past lesson", "Rated a past lesson"),
    "learn_from_job": ("Reviewing the job", "Reviewed the job"),
    "generate_image": ("Generating the image", "Generated the image"),
    "generate_voiceover": ("Recording the voiceover", "Recorded the voiceover"),
    "transcribe_audio": ("Transcribing the audio", "Transcribed the audio"),
    "list_recent_projects": ("Flipping through recent work", "Looked through recent work"),
    "get_render_status": ("Checking the render", "Checked the render"),
    "fetch_asset": ("Pulling a reference", "Pulled a reference"),
}

#: Single MCP tools whose own name misleads or says nothing a person would recognize.
_EXACT: dict[str, Phrase] = {
    "exa_web_search_exa": ("Searching the web", "Searched the web"),
}

#: The verbs a tool's own name is parsed for. The first one in the name is the step's verb, and
#: the words around it are what it acts on: `update-page` is updating a page,
#: `SearchSoundEffects` is searching sound effects. A tool whose name carries none of these is
#: phrased as checking what it names.
_VERBS = frozenset(
    """
    add analyze animate append apply approve archive ask assign attach bind build cancel change
    check clear clone close compare complete compress confirm connect continue convert copy count
    create crop delete deploy detach disable display download draft duplicate edit enable explore
    export fill find finish follow fork generate import insert install invite link list load merge
    move open outpaint patch pause poll post predict prepare preview publish query read recommend
    reconnect reframe refresh register reject remove rename render reorder replace request reset
    resolve restore resume retry revert reveal run save scan schedule search select send set share
    show spawn start stop submit summarize switch sync test transform translate trash trigger tune
    undo unlink unpublish update upgrade upload upscale validate verify wait watch write
    """.split()
)
#: Verbs that say less than the one a person would use for the same step.
_SAY = {
    "get": "read",
    "fetch": "read",
    "retrieve": "read",
    "describe": "read",
    "view": "read",
    "exec": "run",
    "execute": "run",
    "invoke": "run",
    "lookup": "search",
}
#: A verb that takes its object through a preposition.
_THROUGH = {"wait": "for"}
#: Verbs that read naturally straight on the service when the name gives them nothing to act on:
#: "Searching Paper", not "Searching in Paper".
_DIRECT = frozenset({"analyze", "check", "explore", "list", "query", "read", "scan", "search"})
#: Words a tool name carries that are not what it does: packaging and version tags.
_FILLER = frozenset({"tool", "tools", "data", "mcp", "api"})
_VERSION = re.compile(r"^v\d+$")
#: Words that read wrong in lower case.
_CASED = {
    "ai": "AI",
    "api": "API",
    "css": "CSS",
    "csv": "CSV",
    "db": "DB",
    "github": "GitHub",
    "html": "HTML",
    "id": "ID",
    "ids": "IDs",
    "json": "JSON",
    "jsx": "JSX",
    "linkedin": "LinkedIn",
    "mcp": "MCP",
    "pdf": "PDF",
    "pr": "PR",
    "prs": "PRs",
    "sql": "SQL",
    "svg": "SVG",
    "tiktok": "TikTok",
    "ui": "UI",
    "url": "URL",
    "urls": "URLs",
    "youtube": "YouTube",
    "3d": "3D",
}
#: Past tenses that are not `-ed`.
_PAST = {
    "bind": "bound",
    "build": "built",
    "find": "found",
    "read": "read",
    "reset": "reset",
    "run": "ran",
    "send": "sent",
    "set": "set",
    "undo": "undid",
    "write": "wrote",
}
#: Verbs that double their last letter before `-ing` and `-ed`.
_DOUBLE = frozenset({"run", "set", "reset", "scan", "stop", "submit"})
#: Verbs that already say a step is looking, so a name ending in `status` keeps them.
_LOOKING = frozenset({"check", "list", "query", "read", "search"})


def _ing(verb: str) -> str:
    if verb in _DOUBLE:
        return f"{verb}{verb[-1]}ing"
    if verb.endswith("ie"):
        return f"{verb[:-2]}ying"
    if verb.endswith("e") and not verb.endswith("ee"):
        return f"{verb[:-1]}ing"
    return f"{verb}ing"


def _ed(verb: str) -> str:
    if verb in _PAST:
        return _PAST[verb]
    if verb in _DOUBLE:
        return f"{verb}{verb[-1]}ed"
    if verb.endswith("e"):
        return f"{verb}d"
    if verb.endswith("y") and verb[-2:-1] not in ("a", "e", "i", "o", "u"):
        return f"{verb[:-1]}ied"
    return f"{verb}ed"


def _tokens(name: str, server: str = "", service: str = "") -> list[str]:
    """A tool name as lower-case words, with the server's own name and packaging trimmed off."""
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    words = [word for word in re.split(r"[^A-Za-z0-9]+", spaced.lower()) if word]
    own = {*server.split("_"), *service.lower().split()} - {"the", ""}
    words = [word for word in words if not _VERSION.match(word)]
    while words and (words[0] in own or words[0] in _FILLER):
        words.pop(0)
    while words and (words[-1] in own or words[-1] in _FILLER):
        words.pop()
    return words


def _parse(words: list[str]) -> tuple[str, str]:
    """The verb a name leads with (empty when it has none) and what it acts on."""
    for index, word in enumerate(words):
        verb = _SAY.get(word, word)
        if verb in _VERBS:
            if words[-1] == "status" and verb not in _LOOKING:
                # `publish_status` checks a publish; it does not publish a status.
                return "check", " ".join(_CASED.get(w, w) for w in words[:6])
            after, before = words[index + 1 :], words[:index]
            return verb, " ".join(_CASED.get(w, w) for w in (after or before)[:6])
    return "", " ".join(_CASED.get(w, w) for w in words[:6])


def _capital(text: str) -> str:
    return text[:1].upper() + text[1:]


def _sentence(verb: str, thing: str, where: str = "") -> Phrase:
    """`read`, `page`, `in Paper` -> ("Reading page in Paper", "Read page in Paper")."""
    verb = verb or "check"
    if thing and verb in _THROUGH:
        thing = f"{_THROUGH[verb]} {thing}"
    if not thing and where and verb in _DIRECT:
        # Nothing to act on but the service itself: "Searching Paper", not "Searching in Paper".
        where = where.split(" ", 1)[1]
    tail = " ".join(part for part in (thing, where) if part)
    return _capital(f"{_ing(verb)} {tail}".strip()), _capital(f"{_ed(verb)} {tail}".strip())


def services(names: Iterable[str] | Mapping[str, str] = ()) -> dict[str, str]:
    """MCP server names -> how a card names each service: the caller's names, then the known
    ones, then the server name itself, capitalized."""
    given = dict(names) if isinstance(names, Mapping) else {}
    listed = names.keys() if isinstance(names, Mapping) else names
    return {
        server: given.get(server) or KNOWN_SERVICES.get(server) or _capital(_words(server))
        for server in listed
    }


def _remote(name: str, servers: Mapping[str, str]) -> Phrase | None:
    """An MCP tool as its own name reads, or None when `name` is not one."""
    server, separator, tool = name.partition("_")
    if not separator or server not in servers:
        return None
    if name in _EXACT:
        return _EXACT[name]
    service = servers[server]
    where = f"{'on' if server in _ON else 'in'} {service}"
    own = _tokens(tool, server, service)
    if not own:
        return f"Working {where}", f"Worked {where}"
    return _sentence(*_parse(own), where)


def phrase(
    name: str, args: Args | None = None, *, servers: Mapping[str, str] | None = None
) -> Phrase:
    """What a tool call is called while it runs and once it has run. Never raw arguments.

    `servers` maps the declared MCP servers to the service each card names (`services`).
    """
    name = (name or "").strip()
    args = args if isinstance(args, Mapping) else {}
    try:
        if name in _BUILT:
            return _BUILT[name](args)
        if name in _NAMED:
            return _NAMED[name]
        remote = _remote(name, servers or {})
        if remote is not None:
            return remote
        verb, thing = _parse(_tokens(name))
        if verb:
            return _sentence(verb, thing)
    except Exception as error:  # noqa: BLE001 - a phrasing glitch must never cost a step its card
        _LOGGER.debug("[phrasebook] %s phrased by name: %s", name, type(error).__name__)
    readable = _words(name).capitalize() or "Working"
    return readable, readable


def todo_status(status: object) -> str:
    """A deepagents todo status as a Slack card status (pending, in_progress, complete, error)."""
    value = str(status or "").lower()
    if value in ("completed", "complete", "done"):
        return "complete"
    if value in ("in_progress", "in-progress", "running", "active", "doing"):
        return "in_progress"
    if value in ("error", "failed", "blocked", "cancelled", "canceled"):
        return "error"
    return "pending"
