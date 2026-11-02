"""Several creative looks at once: copies of one project, made in parallel, one picked and merged.

A person picks between looks better than a model does: vision-language judges trail people on
video pairs and flip when the pair is swapped. So a helper makes each look, the looks go side by
side, and a person picks. Looks are made at the cheap stage (stills and a storyboard, not a
render), where running several is affordable, and only the winner is built.

Each look is a folder, `<project>/looks/<id>/`: a copy of the project without `looks/`, `out/` and
`node_modules/`. `node_modules` is linked back to the project's, so the renderer runs from the copy
as it does from the project. One helper works there in one direction and writes `look.json`
(`{id, direction, summary, stills}`) when it is done. `LookWatch` hears every look's helper end and
publishes `JOB_ATTENTION` with a ping, so a person picks. `pick` backs the project up to
`looks/_backup-<ts>/`, then copies the chosen look's files over it, newer wins, so an edit made to
the project while the looks ran survives. Folders rather than git worktrees: a media project is
mostly binary assets and is not a repository.

`SnapshotBranches` is the heavy path: a whole sandbox per branch, captured from the thread's sandbox
and spawned from the snapshot (snapshots hold the filesystem only). One sandbox per thread is the
default, so nothing wires it by default.
"""

from __future__ import annotations

import json
import posixpath
import re
import shlex
import time
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from design_agent.harness import events as ev
from design_agent.harness.protocols import HelperRunner, SandboxExec

#: Top-level entries a look leaves out of its copy, and a pick leaves out of its merge.
EXCLUDED = ("looks", "out", "node_modules")
LOOKS_DIR = "looks"
LOOK_FILE = "look.json"
#: Where each look's direction is kept, outside the look's folder so a pick never merges it.
META_DIR = ".meta"
BACKUP_PREFIX = "_backup-"
#: A look id: short, one path segment, never `_backup-…` or `.meta`.
LOOK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,39}")
#: Terminal task events: how a look's helper can end.
TASK_ENDS = {
    ev.TASK_DONE: "done",
    ev.TASK_FAILED: "failed",
    ev.TASK_CANCELLED: "cancelled",
    ev.TASK_INTERRUPTED: "interrupted",
}

_PREPARED = "@@prepared@@ "
_LOOK = "@@look@@ "
_META = "@@meta@@"
_JSON = "@@json@@"
_CHANGED = "@@changed@@ "
_BACKUP = "@@backup@@ "

DEFAULT_TEMPLATE = """\
ROLE
You make one look for the project "{project}": one creative direction, shown as a few stills or a
storyboard, so a person can put the looks side by side and pick one to build. This is the cheap
stage: stills now, the full build after the pick.

THE JOB
{context}

YOUR DIRECTION (look {id})
{direction}

WHERE YOU WORK
- {dir}/ is a full copy of the project, made for this look. Its node_modules, when the project has
  one, links to the project's, so the renderer runs from there as it does from the project.
- Other helpers are making the other looks in the folders beside yours, under {project_dir}/looks/,
  at the same time, and {project_dir}/ itself is the person's current version. So everything you
  change goes in {dir}/.
- If this look is picked, the files you changed in {dir}/ are copied over the project. So make the
  look in the project's own files (compositions, styles, copy, assets), the way the project would
  carry it.
- {dir}/out/ is yours for renders and stays out of that copy.

DELIVERABLES
1. The look, in the project's files under {dir}/, as far as the stills need.
2. Stills or a storyboard that show the direction at its key moments, rendered into {dir}/out/. The
   person compares the looks from these and your summary alone.
3. Last, {look_json}:
   {{"id": "{id}", "direction": "<the direction, as given>", "summary": "<two or three sentences:
   what this look does and why it fits>", "stills": ["<absolute paths, in viewing order>"]}}

REPORT
Your final message: the summary, the stills' paths, and what you would change with more time.
"""

#: What a look's brief says under THE JOB when the lead gives no shared context.
DEFAULT_CONTEXT = (
    "The direction below is the whole ask. The project's own brief files (BRIEF.md, brief.yaml, "
    "outline.yaml), where they exist, say what it is for."
)


class LooksError(RuntimeError):
    """A look could not be prepared, started, read or merged. The message is safe to show."""

    def __init__(self, message: str, *, started: Mapping[str, str] | None = None) -> None:
        super().__init__(message)
        #: Looks whose helpers did start before the failure (look id -> task id).
        self.started = dict(started or {})


@dataclass(frozen=True)
class LookSpec:
    """One look to make: its id (a folder name) and the creative direction its helper follows."""

    id: str
    direction: str


@dataclass(frozen=True)
class LookResult:
    """One look as it stands on disk. `ready` means its helper wrote a readable `look.json`."""

    id: str
    direction: str
    summary: str
    stills: list[str]
    dir: str
    ready: bool


@dataclass(frozen=True)
class Picked:
    """A merged look: the project files it changed (relative paths) and where the backup is."""

    look_id: str
    changed: list[str]
    backup: str


def looks_root(project_dir: str) -> str:
    return posixpath.join(_project(project_dir), LOOKS_DIR)


def look_dir(project_dir: str, look_id: str) -> str:
    return posixpath.join(looks_root(project_dir), _look_id(look_id))


def next_ids(existing: Iterable[str], count: int) -> list[str]:
    """`count` fresh look ids after the ones on disk: a..z, then a2..z2, and so on.

    Letters read well when a person picks ("b, but warmer"), and a second round continues where the
    first stopped, so every look in a thread keeps its own letter.
    """
    taken = set(existing)
    found: list[str] = []
    round_ = 1
    while len(found) < count:
        suffix = "" if round_ == 1 else str(round_)
        for letter in "abcdefghijklmnopqrstuvwxyz":
            candidate = f"{letter}{suffix}"
            if candidate not in taken:
                found.append(candidate)
                if len(found) == count:
                    break
        round_ += 1
    return found


def _project(project_dir: str) -> str:
    """An absolute, normalized project path at least two levels deep (never `/` or `/tmp`)."""
    if (
        not project_dir.startswith("/")
        or posixpath.normpath(project_dir) != project_dir
        or len([part for part in project_dir.split("/") if part]) < 2
        or any(ch in project_dir for ch in "\x00\n\r")
    ):
        raise LooksError(f"{project_dir!r} is not a project folder path.")
    return project_dir


def _look_id(look_id: str) -> str:
    if not LOOK_ID.fullmatch(look_id):
        raise LooksError(
            f"{look_id!r} is not a look id: use letters, digits, '-' or '_', starting with a "
            "letter or digit."
        )
    return look_id


def _tail(output: str, limit: int = 600) -> str:
    text = output.strip()
    return text if len(text) <= limit else "…" + text[-limit:]


def _copy_function(use_rsync: bool | None) -> str:
    """Shell: `copy_tree SRC DEST` makes DEST a fresh copy of SRC without the excluded entries.

    rsync when the sandbox has it (anchored excludes, so `src/looks/` is still copied); otherwise
    `cp -a` of every other top-level entry into a folder emptied first.
    """
    if use_rsync is None:
        detect = "if command -v rsync >/dev/null 2>&1; then HAVE_RSYNC=1; else HAVE_RSYNC=0; fi"
    else:
        detect = f"HAVE_RSYNC={1 if use_rsync else 0}"
    excludes = " ".join(f"--exclude=/{name}" for name in EXCLUDED)
    names = "|".join(EXCLUDED)
    return f"""{detect}
copy_tree() {{
  if [ "$HAVE_RSYNC" = 1 ]; then
    mkdir -p "$2"
    rsync -a --delete --delete-excluded {excludes} "$1"/ "$2"/
  else
    rm -rf "$2"
    mkdir -p "$2"
    for entry in "$1"/* "$1"/.[!.]* "$1"/..?*; do
      [ -e "$entry" ] || [ -L "$entry" ] || continue
      case "${{entry##*/}}" in {names}) continue ;; esac
      cp -a "$entry" "$2"/
    done
  fi
}}
"""


# The no-rsync merge: every file or link in the look (not the excluded entries, not look.json) that
# differs from the project's copy and is not older than it is copied over, and named.
_MERGE_FALLBACK = """cd "$look"
find . \\( -path ./look.json {prunes} \\) -prune -o \\( -type f -o -type l \\) -print |
while IFS= read -r f; do
  rel=${{f#./}}
  dst="$project/$rel"
  if [ -L "$f" ]; then
    if [ -L "$dst" ] && [ "$(readlink "$f")" = "$(readlink "$dst")" ]; then continue; fi
  elif [ -e "$dst" ] && [ ! -L "$dst" ]; then
    if cmp -s "$f" "$dst"; then continue; fi
    if [ "$dst" -nt "$f" ]; then continue; fi
  fi
  mkdir -p "$(dirname "$dst")"
  rm -f "$dst"
  cp -a "$f" "$dst"
  printf '{changed}%s\\n' "$rel"
done
"""


class _Keep(dict[str, str]):
    """Leaves an unknown `{placeholder}` in a custom template as it is."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


class Looks:
    """Make, read and merge looks in one project, through a `SandboxExec`.

    `use_rsync` forces the copy method; `None` (the default) uses rsync when the sandbox has it.
    """

    def __init__(
        self,
        sandbox: SandboxExec,
        *,
        use_rsync: bool | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._sandbox = sandbox
        self._use_rsync = use_rsync
        self._clock = clock

    async def _run(self, script: str, *, timeout: int, what: str, ends_with: str = "") -> str:
        """Run a script; a non-zero exit, or an unknown one without the script's last marker,
        is a failure."""
        result = await self._sandbox.execute(script, timeout=timeout)
        output = result.output or ""
        finished = result.exit_code == 0 or (
            result.exit_code is None and (not ends_with or ends_with in output)
        )
        if not finished:
            raise LooksError(f"{what} failed (exit {result.exit_code}): {_tail(output)}")
        return output

    def _prepare_script(
        self, project_dir: str, look_ids: Sequence[str], directions: Mapping[str, str]
    ) -> str:
        project = _project(project_dir)
        q = shlex.quote
        lines = [
            "set -eu",
            _copy_function(self._use_rsync),
            f"project={q(project)}",
            '[ -d "$project" ] || { echo "no project folder at $project"; exit 3; }',
            f'mkdir -p "$project/{LOOKS_DIR}/{META_DIR}"',
        ]
        for look_id in look_ids:
            dest = f'"$project/{LOOKS_DIR}/{_look_id(look_id)}"'
            lines += [
                f'copy_tree "$project" {dest}',
                f"mkdir -p {dest}/out",
                'if [ -d "$project/node_modules" ]; then '
                f"ln -sfn ../../node_modules {dest}/node_modules; fi",
            ]
            if look_id in directions:
                meta = json.dumps(
                    {"id": look_id, "direction": directions[look_id], "at": self._clock()}
                )
                lines.append(
                    f"printf '%s\\n' {q(meta)} > \"$project/{LOOKS_DIR}/{META_DIR}/{look_id}.json\""
                )
            lines.append(f"echo {q(_PREPARED + look_id)}")
        return "\n".join(lines) + "\n"

    async def prepare(self, project_dir: str, look_ids: Sequence[str]) -> list[str]:
        """Copy the project into `looks/<id>/` for each id (a fresh copy each time) and return the
        folders. One sandbox command for all of them."""
        return await self._prepare(project_dir, look_ids, {})

    async def _prepare(
        self, project_dir: str, look_ids: Sequence[str], directions: Mapping[str, str]
    ) -> list[str]:
        if not look_ids or len(set(look_ids)) != len(look_ids):
            raise LooksError("Give each look its own id.")
        script = self._prepare_script(project_dir, look_ids, directions)
        await self._run(
            script, timeout=900, what="Preparing the looks", ends_with=_PREPARED + look_ids[-1]
        )
        return [look_dir(project_dir, look_id) for look_id in look_ids]

    def brief_for(
        self,
        spec: LookSpec,
        project_dir: str,
        template: str = DEFAULT_TEMPLATE,
        *,
        context: str = "",
    ) -> str:
        """The brief for the helper that makes one look: its direction, its folder and what it
        leaves there (stills in `out/`, then `look.json`)."""
        folder = look_dir(project_dir, spec.id)
        values = _Keep(
            id=spec.id,
            direction=spec.direction.strip(),
            dir=folder,
            project_dir=_project(project_dir),
            project=posixpath.basename(project_dir),
            look_json=posixpath.join(folder, LOOK_FILE),
            out=posixpath.join(folder, "out"),
            context=context.strip() or DEFAULT_CONTEXT,
        )
        return template.format_map(values)

    async def start(
        self,
        project_dir: str,
        specs: Sequence[LookSpec],
        runner: HelperRunner,
        effort: str = "xhigh",
        template: str = DEFAULT_TEMPLATE,
        *,
        context: str = "",
    ) -> dict[str, str]:
        """Prepare every look, then start one helper per look, all in one wave. Returns look id ->
        task id. A helper that cannot start raises `LooksError`, naming those already running."""
        if not specs:
            raise LooksError("Give at least one direction.")
        directions = {spec.id: spec.direction.strip() for spec in specs}
        await self._prepare(project_dir, [spec.id for spec in specs], directions)
        wave = f"looks {posixpath.basename(project_dir)}"
        started: dict[str, str] = {}
        for spec in specs:
            brief = self.brief_for(spec, project_dir, template, context=context)
            label = f"look {spec.id}: {_short(spec.direction)}"
            try:
                started[spec.id] = await runner.start(brief, effort=effort, label=label, wave=wave)
            except Exception as error:  # reported with what did start
                raise LooksError(
                    f"The helper for look {spec.id} did not start: {error}", started=started
                ) from error
        return started

    async def collect(self, project_dir: str) -> list[LookResult]:
        """Every look folder in the project and what its helper left there, sorted by id."""
        root = looks_root(project_dir)
        script = f"""set -u
cd {shlex.quote(root)} 2>/dev/null || exit 0
for d in */; do
  [ -d "$d" ] || continue
  id=${{d%/}}
  case "$id" in {BACKUP_PREFIX}*) continue ;; esac
  printf '\\n{_LOOK}%s\\n' "$id"
  if [ -f "{META_DIR}/$id.json" ]; then printf '{_META}\\n'; cat "{META_DIR}/$id.json"; echo; fi
  if [ -f "$id/{LOOK_FILE}" ]; then printf '{_JSON}\\n'; cat "$id/{LOOK_FILE}"; echo; fi
done
"""
        output = await self._run(script, timeout=60, what="Reading the looks")
        return _parse_looks(output, root)

    async def pick(self, project_dir: str, look_id: str) -> Picked:
        """Merge a look into the project: back the project up to `looks/_backup-<ts>/`, then copy
        the look's files over it (not `look.json`, `out/` or `node_modules/`), skipping any file
        the project holds a newer version of. Returns the changed files and the backup folder."""
        project = _project(project_dir)
        folder = look_dir(project, look_id)
        stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime(self._clock()))
        backup = posixpath.join(looks_root(project), f"{BACKUP_PREFIX}{stamp}")
        q = shlex.quote
        skipped = [LOOK_FILE, *EXCLUDED]
        excludes = " ".join(f"--exclude=/{name}" for name in skipped)
        prunes = " ".join(f"-o -path ./{name}" for name in EXCLUDED)
        fallback = _MERGE_FALLBACK.format(prunes=prunes, changed=_CHANGED)
        script = f"""set -eu
{_copy_function(self._use_rsync)}
project={q(project)}
look={q(folder)}
backup={q(backup)}
[ -d "$look" ] || {{ echo "no look folder at $look"; exit 3; }}
copy_tree "$project" "$backup"
if [ "$HAVE_RSYNC" = 1 ]; then
  rsync -a -u --out-format={q(_CHANGED + "%n")} {excludes} "$look"/ "$project"/
else
{fallback}fi
echo {q(_BACKUP)}"$backup"
"""
        output = await self._run(
            script, timeout=900, what=f"Merging look {look_id}", ends_with=_BACKUP
        )
        changed: list[str] = []
        for line in output.splitlines():
            if line.startswith(_CHANGED):
                name = line[len(_CHANGED) :].strip()
                if name and not name.endswith("/") and name not in changed:
                    changed.append(name)
        return Picked(look_id=look_id, changed=changed, backup=backup)


def _short(text: str, limit: int = 48) -> str:
    one_line = " ".join(text.split())
    return one_line if len(one_line) <= limit else one_line[: limit - 1].rstrip() + "…"


def _load(text: str) -> dict[str, Any] | None:
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _sort_key(look_id: str) -> tuple[int, str]:
    return (len(look_id), look_id)


def _parse_looks(output: str, root: str) -> list[LookResult]:
    sections: dict[str, dict[str, list[str]]] = {}
    current: list[str] | None = None
    for line in output.splitlines():
        if line.startswith(_LOOK):
            look_id = line[len(_LOOK) :].strip()
            sections[look_id] = {"meta": [], "json": []}
            current = None
        elif line == _META and sections:
            current = sections[next(reversed(sections))]["meta"]
        elif line == _JSON and sections:
            current = sections[next(reversed(sections))]["json"]
        elif current is not None:
            current.append(line)
    results: list[LookResult] = []
    for look_id in sorted(sections, key=_sort_key):
        folder = posixpath.join(root, look_id)
        meta = _load("\n".join(sections[look_id]["meta"])) or {}
        written = _load("\n".join(sections[look_id]["json"]))
        stills: list[str] = []
        summary = ""
        direction = str(meta.get("direction") or "")
        if written is not None:
            summary = str(written.get("summary") or "").strip()
            direction = str(written.get("direction") or direction).strip()
            raw = written.get("stills")
            for still in raw if isinstance(raw, list) else []:
                if isinstance(still, str) and still.strip():
                    path = still.strip()
                    stills.append(path if path.startswith("/") else posixpath.join(folder, path))
        results.append(
            LookResult(
                id=look_id,
                direction=direction,
                summary=summary,
                stills=stills,
                dir=folder,
                ready=written is not None and bool(summary or stills),
            )
        )
    return results


# -- hearing the looks end -------------------------------------------------------------------------


class LookWatch:
    """Hears every look's helper end, then asks a person to pick.

    Built before the helpers start (a quick one could end first) and told their task ids with
    `expect`; a terminal task event for this thread that lands in between is kept until then. When
    the last one has ended, it publishes `JOB_ATTENTION` with a ping, naming the looks that are
    done and the ones that are not, and stops listening. When no look is done there is nothing to
    pick, and the lead already heard each failure, so nothing more is published.
    """

    def __init__(self, thread_id: str, project: str, *, bus: ev.EventBus | None = None) -> None:
        self.thread_id = thread_id
        self.project = project
        #: The source of the attention event: this round of looks.
        self.id = f"l-{uuid.uuid4().hex[:6]}"
        self.fired = False
        self._silent = False
        self._bus = bus or ev.BUS
        self._ended: dict[str, ev.Event] = {}
        self._looks: dict[str, LookSpec] | None = None
        self._tasks: dict[str, str] = {}
        self._unsubscribe: Callable[[], None] | None = self._bus.subscribe(self._on_event)

    @property
    def look_ids(self) -> list[str]:
        """The looks this round is waiting on or waited on."""
        return list(self._looks or {})

    def silence(self) -> None:
        """Keep tracking the helpers, but ask nobody to pick when they end: someone already did."""
        self._silent = True

    def expect(self, started: Mapping[str, str], specs: Sequence[LookSpec]) -> None:
        """The looks whose helpers started (look id -> task id). Fires now if all have ended."""
        by_id = {spec.id: spec for spec in specs}
        self._tasks = {task_id: look_id for look_id, task_id in started.items()}
        self._looks = {look_id: by_id.get(look_id, LookSpec(look_id, "")) for look_id in started}
        self._ended = {k: v for k, v in self._ended.items() if k in self._tasks}
        if not self._tasks:
            self.close()
            return
        self._check()

    def pending(self) -> dict[str, str]:
        """Looks whose helpers are still running: look id -> task id."""
        return {
            look_id: task_id
            for task_id, look_id in self._tasks.items()
            if task_id not in self._ended
        }

    def close(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    def _on_event(self, event: ev.Event) -> None:
        if event.thread_id != self.thread_id or event.kind not in TASK_ENDS:
            return
        if self._looks is not None and event.source not in self._tasks:
            return
        self._ended.setdefault(event.source, event)
        self._check()

    def _check(self) -> None:
        if self._looks is None or self.fired or self.pending():
            return
        self.fired = True
        self.close()
        attention = None if self._silent else self.attention()
        if attention is not None:
            self._bus.publish(attention)

    def attention(self) -> ev.Event | None:
        """The event that asks a person to pick, or None while looks run or when none is done."""
        if self._looks is None or self.pending():
            return None
        rows: list[dict[str, str]] = []
        for task_id, look_id in self._tasks.items():
            status = TASK_ENDS.get(self._ended[task_id].kind, "ended")
            spec = self._looks[look_id]
            rows.append(
                {"id": look_id, "direction": spec.direction, "task_id": task_id, "status": status}
            )
        rows.sort(key=lambda row: _sort_key(row["id"]))
        done = [row for row in rows if row["status"] == "done"]
        if not done:
            return None
        shown = ", ".join(f"{row['id']} ({_short(row['direction'])})" for row in done)
        text = f"The looks for {self.project} are ready to compare: {shown}."
        missing = [row for row in rows if row["status"] != "done"]
        if missing:
            names = ", ".join(f"{row['id']} ({row['status']})" for row in missing)
            text += f" Not finished: {names}."
        text += " Pick the one to build on."
        return ev.Event(
            ev.JOB_ATTENTION,
            self.thread_id,
            self.id,
            label=f"looks for {self.project}",
            text=text,
            data={"ping": True, "project": self.project, "looks": rows},
        )


# -- the heavy path: a sandbox per branch -------------------------------------------------------

#: `create_sandbox` keywords `spawn` passes through.
RESOURCES = frozenset(
    {"idle_ttl_seconds", "delete_after_stop_seconds", "vcpus", "mem_bytes", "fs_capacity_bytes"}
)


class SnapshotClient(Protocol):
    """The part of a sandbox client that snapshot branches use (capture, create, delete)."""

    async def capture_snapshot(
        self, sandbox_name: str, name: str, *, tag: str | None = None
    ) -> Any: ...

    async def create_sandbox(
        self,
        snapshot_id: str | None = None,
        *,
        snapshot: str | None = None,
        name: str | None = None,
        idle_ttl_seconds: int | None = None,
        delete_after_stop_seconds: int | None = None,
        vcpus: int | None = None,
        mem_bytes: int | None = None,
        fs_capacity_bytes: int | None = None,
    ) -> Any: ...

    async def delete_sandbox(self, name: str) -> Any: ...


@dataclass(frozen=True)
class SnapshotRef:
    id: str
    name: str
    tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Branch:
    """A sandbox spawned from a snapshot: its own filesystem, its own processes."""

    name: str
    snapshot: str
    id: str = ""
    status: str = ""


class SnapshotBranches:
    """Branches as whole sandboxes: capture the thread's sandbox, spawn one sandbox per branch.

    A snapshot holds the filesystem, not running processes, and a spawned sandbox is not deleted
    on its own: `discard` each branch that lost.
    """

    def __init__(self, client: SnapshotClient) -> None:
        self._client = client

    async def capture(self, sandbox_name: str, name: str, *, tag: str | None = None) -> SnapshotRef:
        """Snapshot a running sandbox's filesystem under `name` (and `tag`); waits until ready."""
        snapshot = await self._client.capture_snapshot(sandbox_name, name, tag=tag)
        return SnapshotRef(
            id=str(getattr(snapshot, "id", "") or ""),
            name=str(getattr(snapshot, "name", "") or name),
            tags=list(getattr(snapshot, "tags", None) or []),
        )

    async def spawn(self, snapshot_name: str, name: str, **resources: int) -> Branch:
        """A new sandbox named `name`, booted from the snapshot (`name`, `name:tag` or an id).
        `resources` are `create_sandbox`'s: idle_ttl_seconds, vcpus, mem_bytes, and so on."""
        unknown = set(resources) - RESOURCES
        if unknown:
            raise TypeError(f"spawn() got unknown resources: {', '.join(sorted(unknown))}")
        options: dict[str, Any] = dict(resources)
        sandbox = await self._client.create_sandbox(snapshot=snapshot_name, name=name, **options)
        return Branch(
            name=str(getattr(sandbox, "name", "") or name),
            snapshot=snapshot_name,
            id=str(getattr(sandbox, "id", "") or ""),
            status=str(getattr(sandbox, "status", "") or ""),
        )

    async def discard(self, name: str) -> None:
        """Delete a branch's sandbox."""
        await self._client.delete_sandbox(name)
