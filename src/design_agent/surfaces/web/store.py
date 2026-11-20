"""What the channels and the canvas show, kept in one SQLite file beside the engine's own state.

The engine keeps the agent's side of a thread: its conversation (the checkpointer), its computer
(the sandbox), its helpers, watches and events. This keeps the people's side: who is in the
workspace, the channels, every message (a person's, the agent's reply, a turn's progress), the
files that went in and out, each task's assets on the canvas (with the boards their review goes up
as) and the feedback people leave on them, the research a task can start from (the questions
asked of a coding agent on this computer, and the notes kept from its answers), every run of such
an agent (what it was told, what it did and what it said, so a conversation's history is the
house's own and not only the agent's), and episodes: the plan, the pictures built for it and the
takes recorded.

One connection, one lock: writes are small and the app is one process.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

Row = dict[str, Any]

SCHEMA = """
CREATE TABLE IF NOT EXISTS people (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, initials TEXT NOT NULL, hue INTEGER NOT NULL,
  agent INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS channels (
  id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, topic TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS threads (
  id TEXT PRIMARY KEY, channel_id TEXT NOT NULL, task INTEGER NOT NULL, title TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'idle', started_by TEXT NOT NULL,
  started_at REAL NOT NULL, updated_at REAL NOT NULL, footer TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY, channel_id TEXT NOT NULL, thread_id TEXT NOT NULL, author_id TEXT NOT NULL,
  kind TEXT NOT NULL, text TEXT NOT NULL DEFAULT '', to_agent INTEGER NOT NULL DEFAULT 0,
  data TEXT NOT NULL DEFAULT '{}', created_at REAL NOT NULL, updated_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS messages_by_thread ON messages(thread_id, created_at);
CREATE INDEX IF NOT EXISTS messages_by_channel ON messages(channel_id, created_at);
CREATE TABLE IF NOT EXISTS files (
  id TEXT PRIMARY KEY, thread_id TEXT NOT NULL DEFAULT '', name TEXT NOT NULL, mime TEXT NOT NULL,
  size INTEGER NOT NULL, origin TEXT NOT NULL, rel_path TEXT NOT NULL, sha256 TEXT NOT NULL,
  author_id TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS boards (
  id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, project TEXT NOT NULL, title TEXT NOT NULL,
  kind TEXT NOT NULL, version INTEGER NOT NULL, status TEXT NOT NULL, created_at REAL NOT NULL,
  updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS frames (
  id TEXT PRIMARY KEY, board_id TEXT NOT NULL, position INTEGER NOT NULL, name TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '', versions TEXT NOT NULL DEFAULT '[]',
  verdict TEXT NOT NULL DEFAULT '', verdict_by TEXT NOT NULL DEFAULT '', updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS comments (
  id TEXT PRIMARY KEY, board_id TEXT NOT NULL, frame_id TEXT NOT NULL,
  parent_id TEXT NOT NULL DEFAULT '', author_id TEXT NOT NULL, text TEXT NOT NULL, x REAL, y REAL,
  version INTEGER NOT NULL, resolved INTEGER NOT NULL DEFAULT 0,
  resolved_by TEXT NOT NULL DEFAULT '', answered_in INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS work (
  id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, kind TEXT NOT NULL, label TEXT NOT NULL DEFAULT '',
  effort TEXT NOT NULL DEFAULT '', status TEXT NOT NULL, fraction REAL, phase TEXT NOT NULL DEFAULT '',
  eta REAL, note TEXT NOT NULL DEFAULT '', steps TEXT NOT NULL DEFAULT '[]',
  started_at REAL NOT NULL, finished_at REAL, updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS activity (
  id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, kind TEXT NOT NULL, source TEXT NOT NULL DEFAULT '',
  label TEXT NOT NULL DEFAULT '', text TEXT NOT NULL DEFAULT '', data TEXT NOT NULL DEFAULT '{}',
  at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS activity_by_thread ON activity(thread_id, at);
CREATE TABLE IF NOT EXISTS assets (
  id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, kind TEXT NOT NULL, title TEXT NOT NULL,
  brief TEXT NOT NULL DEFAULT '', status TEXT NOT NULL, sources TEXT NOT NULL DEFAULT '[]',
  gate INTEGER NOT NULL DEFAULT 0, board_id TEXT NOT NULL DEFAULT '',
  files TEXT NOT NULL DEFAULT '[]', note TEXT NOT NULL DEFAULT '', position INTEGER NOT NULL,
  template TEXT NOT NULL DEFAULT '', added_by TEXT NOT NULL, created_at REAL NOT NULL,
  updated_at REAL NOT NULL, preview TEXT NOT NULL DEFAULT '{}');
CREATE INDEX IF NOT EXISTS assets_by_thread ON assets(thread_id, position);
CREATE TABLE IF NOT EXISTS research (
  id TEXT PRIMARY KEY, repo TEXT NOT NULL, harness TEXT NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS conversations (
  id TEXT PRIMARY KEY, frame_id TEXT NOT NULL, parent_id TEXT NOT NULL DEFAULT '',
  quote TEXT NOT NULL DEFAULT '', harness TEXT NOT NULL, repo TEXT NOT NULL,
  session TEXT NOT NULL DEFAULT '', position INTEGER NOT NULL, created_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS conversations_by_frame ON conversations(frame_id, position);
CREATE TABLE IF NOT EXISTS notes (
  id TEXT PRIMARY KEY, frame_id TEXT NOT NULL, text TEXT NOT NULL,
  conversation_id TEXT NOT NULL DEFAULT '', message_id TEXT NOT NULL DEFAULT '',
  author_id TEXT NOT NULL, position INTEGER NOT NULL, created_at REAL NOT NULL,
  updated_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS notes_by_frame ON notes(frame_id, position);
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, lane TEXT NOT NULL DEFAULT '',
  harness TEXT NOT NULL, session TEXT NOT NULL DEFAULT '', prompt TEXT NOT NULL,
  answer TEXT NOT NULL DEFAULT '', failure TEXT NOT NULL DEFAULT '', state TEXT NOT NULL,
  steps TEXT NOT NULL DEFAULT '[]', started_at REAL NOT NULL, ended_at REAL);
CREATE INDEX IF NOT EXISTS runs_by_thread ON runs(thread_id, lane, started_at);
CREATE TABLE IF NOT EXISTS episodes (
  id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, asset_id TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL, status TEXT NOT NULL, material TEXT NOT NULL DEFAULT '',
  settings TEXT NOT NULL DEFAULT '{}', stage TEXT NOT NULL DEFAULT '{}',
  plan TEXT NOT NULL DEFAULT '{}', labels TEXT NOT NULL DEFAULT '{}',
  picks TEXT NOT NULL DEFAULT '{}', report TEXT NOT NULL DEFAULT '{}',
  film TEXT NOT NULL DEFAULT '{}', approved INTEGER NOT NULL DEFAULT 0,
  started_by TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS episodes_by_thread ON episodes(thread_id, created_at);
CREATE TABLE IF NOT EXISTS channel_voice_clones (
  id TEXT PRIMARY KEY, channel_id TEXT NOT NULL, name TEXT NOT NULL,
  verify INTEGER NOT NULL DEFAULT 0, preview_file TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS voice_clones_by_channel
  ON channel_voice_clones(channel_id, created_at);
INSERT OR IGNORE INTO channel_voice_clones (id, channel_id, name, verify, created_at)
  SELECT json_extract(e.settings, '$.cloned_voice.id'), t.channel_id,
         COALESCE(json_extract(e.settings, '$.cloned_voice.name'), 'Cloned voice'),
         COALESCE(json_extract(e.settings, '$.cloned_voice.verify'), 0), e.updated_at
  FROM episodes e JOIN threads t ON t.id = e.thread_id
  WHERE json_extract(e.settings, '$.cloned_voice.id') IS NOT NULL
  ORDER BY e.updated_at;
CREATE TABLE IF NOT EXISTS pictures (
  id TEXT PRIMARY KEY, episode_id TEXT NOT NULL, unit TEXT NOT NULL, sig TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL, html TEXT NOT NULL DEFAULT '', stills TEXT NOT NULL DEFAULT '{}',
  clip TEXT NOT NULL DEFAULT '', go_sig TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '',
  failure TEXT NOT NULL DEFAULT '', updated_at REAL NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS pictures_by_unit ON pictures(episode_id, unit);
CREATE TABLE IF NOT EXISTS takes (
  id TEXT PRIMARY KEY, episode_id TEXT NOT NULL, chapter TEXT NOT NULL,
  frame TEXT NOT NULL DEFAULT '', n INTEGER NOT NULL, seconds REAL NOT NULL,
  marks TEXT NOT NULL DEFAULT '[]', video TEXT NOT NULL DEFAULT '', audio TEXT NOT NULL DEFAULT '',
  kept INTEGER NOT NULL DEFAULT 1, added_by TEXT NOT NULL, created_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS takes_by_episode ON takes(episode_id, chapter, created_at);
CREATE TABLE IF NOT EXISTS history (
  n INTEGER PRIMARY KEY AUTOINCREMENT, episode_id TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'before', why TEXT NOT NULL DEFAULT '',
  summary TEXT NOT NULL DEFAULT '{}', data TEXT NOT NULL DEFAULT '{}', at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS history_by_episode ON history(episode_id, kind, n);
"""
#: A research conversation's thread: it lives on its research frame, not in the channel.
CONVERSATION = "conversation"
#: How many of an episode's changes are kept to be taken back. Each holds the plan and its
#: pictures as they stood, so the count is small.
HISTORY = 12
#: Columns added since a table was first made, put into a store that predates them.
ADDED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    # A film's Studio preview on the thread's computer, and the proof frames that came with it.
    ("assets", "preview", "TEXT NOT NULL DEFAULT '{}'"),
    # The brand pack a channel's work wears (a folder under workspace/brands); empty for the
    # configured one.
    ("channels", "brand", "TEXT NOT NULL DEFAULT ''"),
    # Where a take's recording, as it arrived, is kept (`s3://bucket/key`); empty when there
    # is no bucket for footage.
    ("takes", "raw", "TEXT NOT NULL DEFAULT ''"),
    ("takes", "label", "TEXT NOT NULL DEFAULT ''"),
    # A take's copy for a film in 4K, no taller than 2160 (a file's id); empty for a recording
    # no taller than the film's own 1080.
    ("takes", "uhd", "TEXT NOT NULL DEFAULT ''"),
    # What the recording was (the studio's own take, a file brought, a camera's clip), its name,
    # when it was recorded, what the house noticed of it, and, for a camera's clip matched to a
    # take by sound, which take and where.
    ("takes", "recording", "TEXT NOT NULL DEFAULT '{}'"),
    # The recordings being brought in for an episode's chapters, by chapter, while they are,
    # and the ones that could not be, with why.
    ("episodes", "imports", "TEXT NOT NULL DEFAULT '{}'"),
    # What a picture was built as and by whom: its level (simple or rich), the agent that built
    # it, and for a rich one the motion plan its builder wrote before drawing it.
    ("pictures", "level", "TEXT NOT NULL DEFAULT ''"),
    # The words its lines said when it was made (a digest), so a picture made for other words
    # can say so.
    ("pictures", "words", "TEXT NOT NULL DEFAULT ''"),
    ("pictures", "builder", "TEXT NOT NULL DEFAULT ''"),
    ("pictures", "generation", "TEXT NOT NULL DEFAULT '{}'"),
    ("pictures", "motion", "TEXT NOT NULL DEFAULT '{}'"),
    # How long its latest build took, kept with the beat: when it began and ended, in all, and
    # each of its stages with its own times.
    ("pictures", "timing", "TEXT NOT NULL DEFAULT '{}'"),
    # The versions it stood as before, the one it last stood as first, each kept whole (its
    # picture, stills and clip, how and by whom it was made, when and how long it took) to look
    # back at and to put back; and which version it is (or will be, while it is made), counting
    # up from 1. A store from before versions were numbered keeps none of the ones it had.
    ("pictures", "versions", "TEXT NOT NULL DEFAULT '[]'"),
    ("pictures", "version", "INTEGER NOT NULL DEFAULT 1"),
    # What a conversation's agent runs on, a model it offers and how hard it thinks (empty for
    # the agent's own default), and the research frame's last pick, which its next question
    # starts from.
    ("conversations", "model", "TEXT NOT NULL DEFAULT ''"),
    ("conversations", "effort", "TEXT NOT NULL DEFAULT ''"),
    ("research", "model", "TEXT NOT NULL DEFAULT ''"),
    ("research", "effort", "TEXT NOT NULL DEFAULT ''"),
)
#: What adding a column to a store that predates it also does.
ADDED_THEN = {("pictures", "version"): "UPDATE pictures SET versions = '[]'"}

#: Columns that hold JSON, decoded on the way out.
JSON_COLUMNS = frozenset(
    {
        "data",
        "footer",
        "versions",
        "steps",
        "sources",
        "files",
        "preview",
        # an episode's
        "settings",
        "stage",
        "plan",
        "labels",
        "picks",
        "report",
        "film",
        "imports",
        "recording",
        "stills",
        "marks",
        "motion",
        "generation",
        "timing",
    }
)
#: Columns that hold a SQLite boolean.
BOOL_COLUMNS = frozenset({"agent", "task", "to_agent", "resolved", "gate", "approved", "kept"})

AGENT_ID = "agent"
#: The workspace a fresh store starts with: you, two teammates to review with, and the agent.
SEED_PEOPLE: tuple[tuple[str, str, str, int, bool], ...] = (
    ("you", "You", "Y", 152, False),
    ("maya", "Maya Chen", "MC", 28, False),
    ("leo", "Leo Park", "LP", 210, False),
    (AGENT_ID, "Agent", "A", 145, True),
)
SEED_CHANNELS: tuple[tuple[str, str], ...] = (
    ("launch", "The launch: films, cards and posts"),
    ("brand", "The brand pack and how it is used"),
)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _decode(row: sqlite3.Row) -> Row:
    out: Row = {}
    for key in row.keys():
        value = row[key]
        if key in JSON_COLUMNS and isinstance(value, str):
            value = json.loads(value or "null")
        elif key in BOOL_COLUMNS:
            value = bool(value)
        out[key] = value
    return out


def _encode(values: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in values.items():
        if key in JSON_COLUMNS and not isinstance(value, str):
            out[key] = json.dumps(value, separators=(",", ":"))
        elif key in BOOL_COLUMNS:
            out[key] = 1 if value else 0
        else:
            out[key] = value
    return out


class Store:
    """Typed enough to keep the app honest; rows come back as plain dicts."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        #: What each turn under way is doing between its steps (`pulse`), by run. In memory
        #: only: a restart ends the turns it was about.
        self.pulses: dict[str, Row] = {}
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.executescript(SCHEMA)
            for table, column, kind in ADDED_COLUMNS:
                have = {row[1] for row in self._db.execute(f"PRAGMA table_info({table})")}
                if column not in have:
                    self._db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
                    if then := ADDED_THEN.get((table, column)):
                        self._db.execute(then)
        self._seed()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # -- plumbing ----------------------------------------------------------------------------

    def _all(self, sql: str, args: Sequence[Any] = ()) -> list[Row]:
        with self._lock:
            return [_decode(r) for r in self._db.execute(sql, tuple(args)).fetchall()]

    def _one(self, sql: str, args: Sequence[Any] = ()) -> Row | None:
        with self._lock:
            row = self._db.execute(sql, tuple(args)).fetchone()
        return _decode(row) if row is not None else None

    def _insert(self, table: str, values: Mapping[str, Any]) -> None:
        encoded = _encode(values)
        columns = ", ".join(encoded)
        marks = ", ".join("?" for _ in encoded)
        with self._lock:
            self._db.execute(
                f"INSERT INTO {table} ({columns}) VALUES ({marks})",  # noqa: S608 - fixed tables
                tuple(encoded.values()),
            )

    def _update(self, table: str, row_id: str, values: Mapping[str, Any]) -> None:
        if not values:
            return
        encoded = _encode(values)
        sets = ", ".join(f"{key} = ?" for key in encoded)
        with self._lock:
            self._db.execute(
                f"UPDATE {table} SET {sets} WHERE id = ?",  # noqa: S608 - fixed tables
                (*encoded.values(), row_id),
            )

    def _seed(self) -> None:
        if self._one("SELECT id FROM people LIMIT 1") is None:
            for pid, name, initials, hue, agent in SEED_PEOPLE:
                self._insert(
                    "people",
                    {"id": pid, "name": name, "initials": initials, "hue": hue, "agent": agent},
                )
        if self._one("SELECT id FROM channels LIMIT 1") is None:
            for name, topic in SEED_CHANNELS:
                self.add_channel(name, topic)

    # -- people and channels -----------------------------------------------------------------

    def people(self) -> list[Row]:
        return self._all("SELECT * FROM people ORDER BY agent, name")

    def person(self, person_id: str) -> Row | None:
        return self._one("SELECT * FROM people WHERE id = ?", (person_id,))

    def channels(self) -> list[Row]:
        return self._all("SELECT * FROM channels ORDER BY created_at")

    def channel(self, channel_id: str) -> Row | None:
        return self._one("SELECT * FROM channels WHERE id = ?", (channel_id,))

    def add_channel(self, name: str, topic: str = "") -> Row:
        row = {"id": new_id("c"), "name": name, "topic": topic, "created_at": time.time()}
        self._insert("channels", row)
        found = self.channel(str(row["id"]))
        assert found is not None  # noqa: S101 - written just above
        return found

    def update_channel(self, channel_id: str, **values: Any) -> Row:
        self._update("channels", channel_id, values)
        found = self.channel(channel_id)
        if found is None:
            raise KeyError(channel_id)
        return found

    # -- threads and messages ----------------------------------------------------------------

    def add_thread(
        self, *, thread_id: str, channel_id: str, task: bool, title: str, kind: str, by: str
    ) -> Row:
        now = time.time()
        row: Row = {
            "id": thread_id,
            "channel_id": channel_id,
            "task": task,
            "title": title,
            "kind": kind,
            "status": "idle",
            "started_by": by,
            "started_at": now,
            "updated_at": now,
            "footer": {},
        }
        self._insert("threads", row)
        return row

    def thread(self, thread_id: str) -> Row | None:
        return self._one("SELECT * FROM threads WHERE id = ?", (thread_id,))

    def threads(self, channel_id: str) -> list[Row]:
        return self._all(
            "SELECT * FROM threads WHERE channel_id = ? ORDER BY started_at", (channel_id,)
        )

    def update_thread(self, thread_id: str, **values: Any) -> Row | None:
        self._update("threads", thread_id, {**values, "updated_at": time.time()})
        return self.thread(thread_id)

    def set_footer(self, thread_id: str, footer: Mapping[str, Any]) -> None:
        """A recount, not news: the thread keeps its place."""
        self._update("threads", thread_id, {"footer": dict(footer)})

    def add_message(
        self,
        *,
        channel_id: str,
        thread_id: str,
        author_id: str,
        kind: str,
        text: str = "",
        to_agent: bool = False,
        data: Mapping[str, Any] | None = None,
        message_id: str | None = None,
    ) -> Row:
        now = time.time()
        row: Row = {
            "id": message_id or new_id("m"),
            "channel_id": channel_id,
            "thread_id": thread_id,
            "author_id": author_id,
            "kind": kind,
            "text": text,
            "to_agent": to_agent,
            "data": dict(data or {}),
            "created_at": now,
            "updated_at": now,
        }
        self._insert("messages", row)
        return row

    def message(self, message_id: str) -> Row | None:
        return self._one("SELECT * FROM messages WHERE id = ?", (message_id,))

    def update_message(self, message_id: str, **values: Any) -> Row | None:
        self._update("messages", message_id, {**values, "updated_at": time.time()})
        return self.message(message_id)

    def messages(self, thread_id: str) -> list[Row]:
        return self._all(
            "SELECT * FROM messages WHERE thread_id = ? ORDER BY created_at", (thread_id,)
        )

    def roots(self, channel_id: str) -> list[Row]:
        """A channel's top-level messages: each thread's first message (a research conversation's
        is on its frame instead)."""
        return self._all(
            "SELECT * FROM messages WHERE channel_id = ? AND id = thread_id AND thread_id NOT IN "
            "(SELECT id FROM threads WHERE kind = ?) ORDER BY created_at",
            (channel_id, CONVERSATION),
        )

    def reply_counts(self, channel_id: str) -> dict[str, int]:
        with self._lock:
            rows = self._db.execute(
                "SELECT thread_id, COUNT(*) FROM messages WHERE channel_id = ? AND id != thread_id "
                "AND kind IN ('person', 'agent') AND thread_id NOT IN "
                "(SELECT id FROM threads WHERE kind = ?) GROUP BY thread_id",
                (channel_id, CONVERSATION),
            ).fetchall()
        return {str(r[0]): int(r[1]) for r in rows}

    # -- files -------------------------------------------------------------------------------

    def add_file(self, values: Mapping[str, Any]) -> Row:
        row: Row = {"id": new_id("f"), "created_at": time.time(), **values}
        self._insert("files", row)
        return row

    def file(self, file_id: str) -> Row | None:
        return self._one("SELECT * FROM files WHERE id = ?", (file_id,))

    def delete_file(self, file_id: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM files WHERE id = ?", (file_id,))

    def files(self, thread_id: str, origin: str | None = None) -> list[Row]:
        if origin is None:
            return self._all(
                "SELECT * FROM files WHERE thread_id = ? ORDER BY created_at", (thread_id,)
            )
        return self._all(
            "SELECT * FROM files WHERE thread_id = ? AND origin = ? ORDER BY created_at",
            (thread_id, origin),
        )

    def attach_files(self, file_ids: Iterable[str], thread_id: str) -> None:
        for file_id in file_ids:
            self._update("files", file_id, {"thread_id": thread_id})

    # -- boards, frames, comments ------------------------------------------------------------

    def add_board(self, values: Mapping[str, Any]) -> Row:
        now = time.time()
        row: Row = {"id": new_id("b"), "created_at": now, "updated_at": now, **values}
        self._insert("boards", row)
        return row

    def board(self, board_id: str) -> Row | None:
        return self._one("SELECT * FROM boards WHERE id = ?", (board_id,))

    def boards(self, thread_id: str) -> list[Row]:
        return self._all(
            "SELECT * FROM boards WHERE thread_id = ? ORDER BY created_at", (thread_id,)
        )

    def update_board(self, board_id: str, **values: Any) -> None:
        self._update("boards", board_id, {**values, "updated_at": time.time()})

    def add_frame(self, values: Mapping[str, Any]) -> Row:
        row: Row = {"id": new_id("fr"), "updated_at": time.time(), **values}
        self._insert("frames", row)
        return row

    def frame(self, frame_id: str) -> Row | None:
        return self._one("SELECT * FROM frames WHERE id = ?", (frame_id,))

    def frames(self, board_id: str) -> list[Row]:
        return self._all("SELECT * FROM frames WHERE board_id = ? ORDER BY position", (board_id,))

    def update_frame(self, frame_id: str, **values: Any) -> None:
        self._update("frames", frame_id, {**values, "updated_at": time.time()})

    def add_comment(self, values: Mapping[str, Any]) -> Row:
        row: Row = {"id": new_id("cm"), "created_at": time.time(), **values}
        self._insert("comments", row)
        return row

    def comment(self, comment_id: str) -> Row | None:
        return self._one("SELECT * FROM comments WHERE id = ?", (comment_id,))

    def comments(self, board_id: str) -> list[Row]:
        return self._all(
            "SELECT * FROM comments WHERE board_id = ? ORDER BY created_at", (board_id,)
        )

    def update_comment(self, comment_id: str, **values: Any) -> None:
        self._update("comments", comment_id, values)

    # -- assets: each task's pieces of work on the canvas ----------------------------------------

    def add_asset(self, values: Mapping[str, Any]) -> Row:
        now = time.time()
        row: Row = {
            "id": new_id("as"),
            "status": "planned",
            "sources": [],
            "files": [],
            "created_at": now,
            "updated_at": now,
            **values,
        }
        self._insert("assets", row)
        found = self.asset(row["id"])
        assert found is not None  # noqa: S101 - written just above
        return found

    def asset(self, asset_id: str) -> Row | None:
        return self._one("SELECT * FROM assets WHERE id = ?", (asset_id,))

    def assets(self, thread_id: str) -> list[Row]:
        return self._all(
            "SELECT * FROM assets WHERE thread_id = ? ORDER BY position, created_at", (thread_id,)
        )

    def update_asset(self, asset_id: str, **values: Any) -> Row | None:
        self._update("assets", asset_id, {**values, "updated_at": time.time()})
        return self.asset(asset_id)

    # -- research: a frame's repository, its conversations, the notes kept from them ------------

    def add_research(self, frame_id: str, *, repo: str, harness: str) -> Row:
        row: Row = {"id": frame_id, "repo": repo, "harness": harness, "created_at": time.time()}
        self._insert("research", row)
        return row

    def research(self, frame_id: str) -> Row | None:
        return self._one("SELECT * FROM research WHERE id = ?", (frame_id,))

    def update_research(self, frame_id: str, **values: Any) -> Row | None:
        self._update("research", frame_id, values)
        return self.research(frame_id)

    def add_conversation(self, values: Mapping[str, Any]) -> Row:
        frame_id = str(values["frame_id"])
        with self._lock:
            count = self._db.execute(
                "SELECT COUNT(*) FROM conversations WHERE frame_id = ?", (frame_id,)
            ).fetchone()[0]
        row: Row = {"position": int(count), "created_at": time.time(), **values}
        self._insert("conversations", row)
        found = self.conversation(str(row["id"]))
        assert found is not None  # noqa: S101 - written just above
        return found

    def conversation(self, conversation_id: str) -> Row | None:
        return self._one("SELECT * FROM conversations WHERE id = ?", (conversation_id,))

    def conversations(self, frame_id: str) -> list[Row]:
        return self._all(
            "SELECT * FROM conversations WHERE frame_id = ? ORDER BY position", (frame_id,)
        )

    def update_conversation(self, conversation_id: str, **values: Any) -> None:
        self._update("conversations", conversation_id, values)

    def add_note(self, values: Mapping[str, Any]) -> Row:
        frame_id = str(values["frame_id"])
        with self._lock:
            last = self._db.execute(
                "SELECT COALESCE(MAX(position), -1) FROM notes WHERE frame_id = ?", (frame_id,)
            ).fetchone()[0]
        now = time.time()
        row: Row = {
            "id": new_id("nt"),
            "position": int(last) + 1,
            "created_at": now,
            "updated_at": now,
            **values,
        }
        self._insert("notes", row)
        found = self.note(row["id"])
        assert found is not None  # noqa: S101 - written just above
        return found

    def note(self, note_id: str) -> Row | None:
        return self._one("SELECT * FROM notes WHERE id = ?", (note_id,))

    def notes(self, frame_id: str) -> list[Row]:
        return self._all("SELECT * FROM notes WHERE frame_id = ? ORDER BY position", (frame_id,))

    def update_note(self, note_id: str, **values: Any) -> Row | None:
        self._update("notes", note_id, {**values, "updated_at": time.time()})
        return self.note(note_id)

    def delete_note(self, note_id: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM notes WHERE id = ?", (note_id,))

    # -- runs: what an agent on this computer (or the engine) was told and said ----------------

    def add_run(self, *, thread_id: str, lane: str, harness: str, prompt: str, session: str) -> Row:
        row: Row = {
            "id": new_id("run"),
            "thread_id": thread_id,
            "lane": lane,
            "harness": harness,
            "session": session,
            "prompt": prompt,
            "state": "working",
            "steps": [],
            "started_at": time.time(),
        }
        self._insert("runs", row)
        found = self.run(str(row["id"]))
        assert found is not None  # noqa: S101 - written just above
        return found

    def run(self, run_id: str) -> Row | None:
        return self._one("SELECT * FROM runs WHERE id = ?", (run_id,))

    def update_run(self, run_id: str, **values: Any) -> Row | None:
        self._update("runs", run_id, values)
        return self.run(run_id)

    def runs(self, thread_id: str, lane: str | None = None) -> list[Row]:
        """A thread's runs, oldest first; one lane of them when `lane` is given."""
        if lane is None:
            return self._all(
                "SELECT * FROM runs WHERE thread_id = ? ORDER BY started_at", (thread_id,)
            )
        return self._all(
            "SELECT * FROM runs WHERE thread_id = ? AND lane = ? ORDER BY started_at",
            (thread_id, lane),
        )

    def working_runs(self) -> list[Row]:
        return self._all("SELECT * FROM runs WHERE state = 'working' ORDER BY started_at")

    def pulse(
        self, run_id: str, lane: str, doing: str = "", text: str = "", amount: int = 0
    ) -> Row:
        """A sign of life from a turn between two of its steps: what its model is at
        ("thinking", "writing" its own words, "step" for a tool call it is writing, or nothing
        known), the newest words of the thought or the step the call will be, and how much so
        far (tokens of thought, characters written). `since` is when it began what it is at."""
        now = time.time()
        was = self.pulses.get(run_id)
        going_on = was is not None and bool(doing) and was["doing"] == doing
        row: Row = {
            "lane": lane,
            "at": now,
            "doing": doing,
            "text": text,
            "amount": amount,
            "since": was["since"] if was is not None and going_on else now,
        }
        self.pulses[run_id] = row
        return row

    # -- episodes: the plan, the pictures built for it, the takes recorded ----------------------

    def add_episode(self, values: Mapping[str, Any]) -> Row:
        now = time.time()
        row: Row = {"id": new_id("ep"), "created_at": now, "updated_at": now, **values}
        self._insert("episodes", row)
        found = self.episode(str(row["id"]))
        assert found is not None  # noqa: S101 - written just above
        return found

    def episode(self, episode_id: str) -> Row | None:
        return self._one("SELECT * FROM episodes WHERE id = ?", (episode_id,))

    def episodes(self, thread_id: str) -> list[Row]:
        return self._all(
            "SELECT * FROM episodes WHERE thread_id = ? ORDER BY created_at", (thread_id,)
        )

    def all_episodes(self) -> list[Row]:
        return self._all("SELECT * FROM episodes ORDER BY created_at")

    def update_episode(self, episode_id: str, **values: Any) -> Row | None:
        self._update("episodes", episode_id, {**values, "updated_at": time.time()})
        return self.episode(episode_id)

    def voice_clone(self, voice_id: str) -> Row | None:
        return self._one("SELECT * FROM channel_voice_clones WHERE id = ?", (voice_id,))

    def channel_voice_clones(self, channel_id: str) -> list[Row]:
        return self._all(
            "SELECT * FROM channel_voice_clones WHERE channel_id = ? ORDER BY created_at, id",
            (channel_id,),
        )

    def voice_clone_ids(self) -> set[str]:
        return {str(row["id"]) for row in self._all("SELECT id FROM channel_voice_clones")}

    def add_voice_clone(self, channel_id: str, voice: Row) -> None:
        self._insert(
            "channel_voice_clones",
            {**voice, "channel_id": channel_id, "created_at": time.time()},
        )

    def save_voice_preview(self, voice_id: str, file_id: str) -> None:
        self._update("channel_voice_clones", voice_id, {"preview_file": file_id, "verify": 0})

    def picture(self, episode_id: str, unit: str) -> Row | None:
        return self._one(
            "SELECT * FROM pictures WHERE episode_id = ? AND unit = ?", (episode_id, unit)
        )

    def pictures(self, episode_id: str) -> list[Row]:
        return self._all("SELECT * FROM pictures WHERE episode_id = ?", (episode_id,))

    def set_picture(self, episode_id: str, unit: str, **values: Any) -> Row:
        """A unit's picture, made on first use."""
        existing = self.picture(episode_id, unit)
        now = time.time()
        if existing is None:
            row: Row = {
                "id": new_id("pic"),
                "episode_id": episode_id,
                "unit": unit,
                "status": "queued",
                "updated_at": now,
                **values,
            }
            self._insert("pictures", row)
        else:
            self._update("pictures", str(existing["id"]), {**values, "updated_at": now})
        found = self.picture(episode_id, unit)
        assert found is not None  # noqa: S101 - written just above
        return found

    # An episode's changes, oldest first. A row is a change and the other side of it: while the
    # change stands (`before`) it holds the episode as it stood before, and once the change is
    # taken back (`undone`) it holds the episode as the change left it.

    def put_snapshot(self, episode_id: str, *, why: str, data: Mapping[str, Any]) -> None:
        """A change begins: the episode as it stands is kept. What was taken back before it
        can no longer be put back, and only the newest `HISTORY` changes are kept."""
        with self._lock:
            self._db.execute(
                "DELETE FROM history WHERE episode_id = ? AND kind = 'undone'", (episode_id,)
            )
            self._db.execute(
                "INSERT INTO history (episode_id, kind, why, summary, data, at) "
                "VALUES (?, 'before', ?, '{}', ?, ?)",
                (episode_id, why, json.dumps(data), time.time()),
            )
            self._db.execute(
                "DELETE FROM history WHERE episode_id = ? AND n NOT IN "
                "(SELECT n FROM history WHERE episode_id = ? ORDER BY n DESC LIMIT ?)",
                (episode_id, episode_id, HISTORY),
            )

    def _history(self, episode_id: str, kind: str, columns: str) -> Any:
        # the change that stands last is the next to take back; the one taken back first is
        # the last to put back
        order = "DESC" if kind == "before" else "ASC"
        with self._lock:
            return self._db.execute(
                f"SELECT {columns} FROM history WHERE episode_id = ? AND kind = ? "  # noqa: S608
                f"ORDER BY n {order} LIMIT 1",
                (episode_id, kind),
            ).fetchone()

    def snapshot(self, episode_id: str, kind: str = "before") -> Row | None:
        """The newest change whole. `data` is large and stays text until asked for here."""
        row = self._history(episode_id, kind, "n, why, summary, data, at")
        if row is None:
            return None
        return {
            "n": row["n"],
            "why": row["why"],
            "summary": json.loads(row["summary"] or "{}"),
            "data": json.loads(row["data"] or "{}"),
            "at": row["at"],
        }

    def previous_plans(self, episode_id: str) -> list[Row]:
        with self._lock:
            rows = self._db.execute(
                "SELECT n, why, at, json_extract(data, '$.plan') AS plan FROM history "
                "WHERE episode_id = ? AND kind = 'before' ORDER BY n DESC",
                (episode_id,),
            ).fetchall()
        return [{**dict(row), "plan": json.loads(row["plan"] or "{}")} for row in rows]

    def snapshot_note(self, episode_id: str, kind: str = "before") -> Row | None:
        """What the newest change did, without the snapshot's weight."""
        row = self._history(episode_id, kind, "n, why, summary, at")
        if row is None:
            return None
        return {
            "n": row["n"],
            "why": row["why"],
            "summary": json.loads(row["summary"] or "{}"),
            "at": row["at"],
        }

    def snapshots(self, episode_id: str) -> int:
        """How many changes stand and can be taken back."""
        with self._lock:
            row = self._db.execute(
                "SELECT COUNT(*) FROM history WHERE episode_id = ? AND kind = 'before' "
                "AND summary != '{}'",
                (episode_id,),
            ).fetchone()
        return int(row[0])

    def note_snapshot(self, n: int, summary: Mapping[str, Any]) -> None:
        with self._lock:
            self._db.execute("UPDATE history SET summary = ? WHERE n = ?", (json.dumps(summary), n))

    def turn_snapshot(self, n: int, *, kind: str, data: Mapping[str, Any]) -> None:
        """A change is taken back, or put back: its row now holds the other side of it."""
        with self._lock:
            self._db.execute(
                "UPDATE history SET kind = ?, data = ?, at = ? WHERE n = ?",
                (kind, json.dumps(data), time.time(), n),
            )

    def drop_snapshot(self, n: int) -> None:
        with self._lock:
            self._db.execute("DELETE FROM history WHERE n = ?", (n,))

    def delete_picture(self, episode_id: str, unit: str) -> None:
        with self._lock:
            self._db.execute(
                "DELETE FROM pictures WHERE episode_id = ? AND unit = ?", (episode_id, unit)
            )

    def add_take(self, values: Mapping[str, Any]) -> Row:
        episode_id, chapter, frame = (str(values[k]) for k in ("episode_id", "chapter", "frame"))
        with self._lock:
            count = self._db.execute(
                "SELECT COUNT(*) FROM takes WHERE episode_id = ? AND chapter = ? AND frame = ?",
                (episode_id, chapter, frame),
            ).fetchone()[0]
        row: Row = {"id": new_id("tk"), "n": int(count) + 1, "created_at": time.time(), **values}
        self._insert("takes", row)
        found = self.take(str(row["id"]))
        assert found is not None  # noqa: S101 - written just above
        return found

    def take(self, take_id: str) -> Row | None:
        return self._one("SELECT * FROM takes WHERE id = ?", (take_id,))

    def takes(self, episode_id: str) -> list[Row]:
        return self._all(
            "SELECT * FROM takes WHERE episode_id = ? ORDER BY created_at", (episode_id,)
        )

    def update_take(self, take_id: str, **values: Any) -> Row | None:
        self._update("takes", take_id, values)
        return self.take(take_id)

    def delete_take(self, take_id: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM takes WHERE id = ?", (take_id,))

    # -- background work and activity --------------------------------------------------------

    def work_item(self, work_id: str) -> Row | None:
        return self._one("SELECT * FROM work WHERE id = ?", (work_id,))

    def upsert_work(self, work_id: str, thread_id: str, kind: str, **values: Any) -> Row:
        existing = self.work_item(work_id)
        now = time.time()
        if existing is None:
            row: Row = {
                "id": work_id,
                "thread_id": thread_id,
                "kind": kind,
                "status": "running",
                "started_at": now,
                "updated_at": now,
                "steps": [],
                **values,
            }
            self._insert("work", row)
        else:
            self._update("work", work_id, {**values, "updated_at": now})
        found = self.work_item(work_id)
        assert found is not None  # noqa: S101 - written just above
        return found

    def work(self, thread_id: str) -> list[Row]:
        return self._all("SELECT * FROM work WHERE thread_id = ? ORDER BY started_at", (thread_id,))

    def add_activity(self, values: Mapping[str, Any]) -> Row:
        row: Row = {"id": new_id("a"), **values}
        self._insert("activity", row)
        return row

    def activity(self, thread_id: str, limit: int = 200) -> list[Row]:
        return self._all(
            "SELECT * FROM activity WHERE thread_id = ? ORDER BY at DESC LIMIT ?",
            (thread_id, limit),
        )

    def usage(self, thread_id: str) -> list[Row]:
        """Every model call the thread paid for, oldest first, as the meter priced it."""
        return self._all(
            "SELECT * FROM activity WHERE thread_id = ? AND kind = 'usage' ORDER BY at",
            (thread_id,),
        )
