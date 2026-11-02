"""A scripted lead for the web app's demo: no API keys, the real graph, the real computer.

It plays one small job end to end so every part of the app can be seen working:

1. **Storyboard.** Asked for anything, it writes a brief, poses three beats of a teaser as HTML
   in the brand's tokens, lints and renders them in the sandbox, and puts them on the canvas.
2. **Notes.** Told there are notes on the board, it reads them (`canvas_read_feedback`),
   re-poses only the frames people commented on, and publishes the new version, saying which
   notes it answers.
3. **The film.** Told the board is approved, it builds the HyperFrames composition, runs the
   gates, starts the render as a background job and ends its turn; the watcher wakes it when the
   render exits, and it measures the film and delivers it to the thread.
4. **Assets on the canvas.** Asked for assets by id (a template's, or one someone added), it works
   through the ones it can make (a storyboard, the teaser, social cards, thumbnails from the
   teaser's frames, a GIF of it, a stat card) as their sources allow: a storyboard waits for its
   sign-off, the teaser for its render, and the rest follow. It files each under its id and
   marks the kinds it does not make as skipped.

Each step reads what the previous tool printed; a gate that fails ends the job with a line
saying so, as the offline demo does. Anything else gets a short reply.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool

from design_agent.surfaces.web.catalog import CAPABILITIES, capability
from design_agent.testing.demo_script import card_html, teaser_html
from design_agent.testing.scripted_model import last_json, last_tool_results, reply, tool_calls

PROJECT = "/workspace/projects/studio-teaser"
BOARD_DIR = f"{PROJECT}/board"
TEASER = f"{PROJECT}/teaser"
FILM = f"{PROJECT}/renders/teaser.mp4"
SIZE = "1920x1080"
NOTICE = "[Runtime notice"
FAILED = "I stopped:"

Step = Callable[[Sequence[BaseMessage]], AIMessage]

POSE_CSS = """
html, body { margin: 0; width: 1920px; height: 1080px; overflow: hidden;
  background: var(--brand-color-paper); }
#stage { position: relative; width: 1920px; height: 1080px; color: var(--brand-color-ink);
  font-family: var(--brand-font-text); }
.mark { position: absolute; top: 120px; left: 144px; width: 112px; height: 112px; }
.headline { position: absolute; left: 144px; bottom: 404px; margin: 0;
  font-family: var(--brand-font-display); font-weight: var(--brand-weight-display);
  font-size: 176px; line-height: 1; letter-spacing: -0.02em; }
.horizon { position: absolute; left: 144px; right: 144px; bottom: 330px;
  height: var(--brand-stroke); background: var(--brand-color-signal); }
.line { position: absolute; left: 144px; bottom: 200px; margin: 0; font-size: 56px;
  line-height: 1.3; color: var(--brand-color-graphite); }
.rising { transform: translateY(48px); opacity: 0.35; }
.half { right: 960px; }
.revised .headline { font-size: 192px; }
.revised .line { font-size: 72px; color: var(--brand-color-ink); }
.revised .horizon { background: var(--brand-color-moss); }
"""

#: Each beat: its file stem, its name on the board, one line on what it shows, and its pose.
BEATS: tuple[tuple[str, str, str, str], ...] = (
    (
        "beat-01",
        "Beat 1 · The name rises",
        "The name comes up into place; nothing else yet.",
        '<h1 id="headline" class="headline rising">Example Studio 2.0</h1>',
    ),
    (
        "beat-02",
        "Beat 2 · The rule draws",
        "The signal rule draws in under the name, left to right.",
        '<h1 id="headline" class="headline">Example Studio 2.0</h1>'
        '<div id="horizon" class="horizon half"></div>',
    ),
    (
        "beat-03",
        "Beat 3 · The line lands",
        "The line arrives under the rule, with time to read it.",
        '<h1 id="headline" class="headline">Example Studio 2.0</h1>'
        '<div id="horizon" class="horizon"></div>'
        '<p id="line" class="line">Every size, one pass.</p>',
    ),
)

BRIEF = """# Studio teaser

A 4-second 1920x1080 teaser announcing Example Studio 2.0, for the launch post.

- Message: one pass makes every size.
- Copy, exactly: "Example Studio 2.0" and "Every size, one pass."
- Three beats: the name rises, the signal rule draws, the line lands.
- Storyboard first; the film is built from the approved poses.
"""


def pose_html(beat: tuple[str, str, str, str], *, revised: bool = False) -> str:
    _, name, _, body = beat
    stage = ' class="revised"' if revised else ""
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8" />'
        f"<title>{name}</title>"
        '<link rel="stylesheet" href="/workspace/brand/tokens.css" />'
        f"<style>{POSE_CSS}</style></head><body>"
        f'<main id="stage"{stage}>'
        '<img class="mark" src="/workspace/brand/logos/mark.svg" alt="Example Studio" />'
        f"{body}</main></body></html>\n"
    )


def _render(
    stems: Sequence[str], suffix: str = "", folder: str = BOARD_DIR, size: str = SIZE
) -> str:
    """Lint and render each page; stop at the first that fails. The tools resolve relative paths
    against /workspace, so every path here is absolute."""
    parts: list[str] = []
    for stem in stems:
        parts.append(f"node /workspace/tools/brand-lint.mjs {folder}/{stem}{suffix}.html")
        parts.append(
            f"node /workspace/tools/html2png.mjs {folder}/{stem}{suffix}.html "
            f"--out {folder}/poses --name {stem}{suffix} --size {size} --brand-fonts"
        )
    return " && ".join(parts) + f" && ls {folder}/poses"


def _pose_path(stem: str, suffix: str = "", folder: str = BOARD_DIR, size: str = SIZE) -> str:
    return f"{folder}/poses/{stem}{suffix}-{size}.png"


def _failed(messages: Sequence[BaseMessage]) -> str | None:
    for message in last_tool_results(messages):
        text = str(message.content)
        if isinstance(message, ToolMessage) and message.status == "error":
            return text[:300]
        found = re.search(r"exit code (-?\d+)", text)
        if found and found.group(1) != "0":
            return text[-300:]
    return None


def _board_id(messages: Sequence[BaseMessage]) -> str:
    for message in messages:
        if isinstance(message, ToolMessage):
            found = re.search(r"\bboard (b_[0-9a-f]+)", str(message.content))
            if found:
                return found.group(1)
    return ""


# -- the three jobs ------------------------------------------------------------------------


def storyboard_steps() -> list[Step]:
    def plan(_: Sequence[BaseMessage]) -> AIMessage:
        todos = [
            {"content": "Write the brief", "status": "completed"},
            {"content": "Pose the three beats", "status": "in_progress"},
            {"content": "Put the board on the canvas for sign-off", "status": "pending"},
            {"content": "Build the film from the approved board", "status": "pending"},
        ]
        return tool_calls(
            ("write_todos", {"todos": todos}),
            ("write_file", {"file_path": f"{PROJECT}/BRIEF.md", "content": BRIEF}),
            content="Storyboard first: three poses, then the film once they're approved.",
        )

    def pose(_: Sequence[BaseMessage]) -> AIMessage:
        return tool_calls(
            *(
                (
                    "write_file",
                    {"file_path": f"{BOARD_DIR}/{beat[0]}.html", "content": pose_html(beat)},
                )
                for beat in BEATS
            ),
            content="Posing each beat in the brand's tokens.",
        )

    def render(_: Sequence[BaseMessage]) -> AIMessage:
        return tool_calls(
            ("execute", {"command": _render([b[0] for b in BEATS]), "timeout": 300}),
            content="Checking them against the brand and rendering them.",
        )

    def publish(messages: Sequence[BaseMessage]) -> AIMessage:
        if failure := _failed(messages):
            return reply(f"{FAILED} a pose did not pass its checks ({failure}).")
        frames = [{"path": _pose_path(b[0]), "name": b[1], "note": b[2]} for b in BEATS]
        return tool_calls(
            (
                "canvas_publish_board",
                {
                    "project": "studio-teaser",
                    "title": "Storyboard",
                    "kind": "storyboard",
                    "frames": frames,
                },
            )
        )

    def answer(_: Sequence[BaseMessage]) -> AIMessage:
        return reply(
            "The storyboard is on the canvas: the name rises, the signal rule draws under it, and "
            "the line lands. Pin a note on any frame, or approve the board, and I'll build the "
            "film from it."
        )

    return [plan, pose, render, publish, answer]


def revise_steps() -> list[Step]:
    def read(messages: Sequence[BaseMessage]) -> AIMessage:
        board = _board_id(messages)
        if not board:
            return reply("I can't find a board on this thread yet; ask me for a storyboard first.")
        return tool_calls(("canvas_read_feedback", {"board": board}))

    def repose(messages: Sequence[BaseMessage]) -> AIMessage:
        asked = _asked(messages)
        if not asked:
            return reply(
                "I don't see open notes on the board. Pin one on a frame, or approve it if it "
                "reads right."
            )
        beats = [b for b in BEATS if b[1] in asked]
        return tool_calls(
            *(
                (
                    "write_file",
                    {
                        "file_path": f"{BOARD_DIR}/{beat[0]}-v2.html",
                        "content": pose_html(beat, revised=True),
                    },
                )
                for beat in beats
            ),
            content="Re-posing only the frames with notes.",
        )

    def render(messages: Sequence[BaseMessage]) -> AIMessage:
        stems = [b[0] for b in BEATS if b[1] in _asked(messages)]
        return tool_calls(("execute", {"command": _render(stems, "-v2"), "timeout": 300}))

    def publish(messages: Sequence[BaseMessage]) -> AIMessage:
        if failure := _failed(messages):
            return reply(f"{FAILED} a revised pose did not pass its checks ({failure}).")
        feedback = _feedback(messages)
        asked = list(feedback["asked"])
        frames = [
            {"path": _pose_path(b[0], "-v2"), "name": b[1], "note": b[2]}
            for b in BEATS
            if b[1] in asked
        ]
        return tool_calls(
            (
                "canvas_publish_board",
                {
                    "project": "studio-teaser",
                    "title": "Storyboard",
                    "kind": "storyboard",
                    "frames": frames,
                    "replaces": _board_id(messages),
                    "answers": feedback["notes"],
                },
            )
        )

    def answer(messages: Sequence[BaseMessage]) -> AIMessage:
        feedback = _feedback(messages)
        names = ", ".join(feedback["asked"]) or "the frames with notes"
        who = " and ".join(feedback["authors"]) or "the team"
        return reply(
            f"Version 2 of {names} is on the canvas, answering {who}'s note: a bigger name, and "
            "the rule in moss so it sits back and the words lead. The other beats are as you "
            "saw them. Approve the board when it reads right."
        )

    return [read, repose, render, publish, answer]


def film_steps() -> list[Step]:
    def compose(_: Sequence[BaseMessage]) -> AIMessage:
        todos = [
            {"content": "Write the brief", "status": "completed"},
            {"content": "Pose the three beats", "status": "completed"},
            {"content": "Put the board on the canvas for sign-off", "status": "completed"},
            {"content": "Build the film from the approved board", "status": "in_progress"},
        ]
        return tool_calls(
            ("write_todos", {"todos": todos}),
            ("write_file", {"file_path": f"{TEASER}/index.html", "content": teaser_html()}),
            content="Building the film from the approved poses.",
        )

    def gate(_: Sequence[BaseMessage]) -> AIMessage:
        return tool_calls(
            (
                "execute",
                {
                    "command": (
                        "cp /workspace/brand/tokens.css /workspace/brand/logos/mark.svg "
                        f"/opt/design-agent/render/node_modules/gsap/dist/gsap.min.js {TEASER}/ && "
                        f"node /workspace/tools/video-gate.mjs {TEASER}/index.html --json && "
                        f"node /workspace/tools/brand-lint.mjs {TEASER}/index.html && "
                        f"hyperframes check {TEASER}"
                    ),
                    "timeout": 300,
                },
            )
        )

    def render(messages: Sequence[BaseMessage]) -> AIMessage:
        if failure := _failed(messages):
            return reply(f"{FAILED} the film did not pass its checks ({failure}).")
        return tool_calls(
            (
                "start_render_job",
                {
                    "command": f"hyperframes render {TEASER} --quality draft --fps 30 --output {FILM}",
                    "label": "the film",
                    "kind": "hyperframes",
                },
            )
        )

    def answer(_: Sequence[BaseMessage]) -> AIMessage:
        return reply(
            "The film passed its checks and is rendering now: four seconds at 1920×1080. I'll "
            "post it here the moment it's done."
        )

    return [compose, gate, render, answer]


def finish_steps() -> list[Step]:
    def measure(_: Sequence[BaseMessage]) -> AIMessage:
        return tool_calls(
            (
                "execute",
                {
                    "command": (
                        f"node /workspace/tools/artifact-contract.mjs --expect {FILM}:{SIZE}@4 --json"
                    )
                },
            )
        )

    def deliver(messages: Sequence[BaseMessage]) -> AIMessage:
        result = last_json(messages)
        if result and result.get("ok") is not True:
            return reply(f"{FAILED} the film did not measure as asked.")
        return tool_calls(("upload_files", {"paths": [FILM]}))

    def answer(messages: Sequence[BaseMessage]) -> AIMessage:
        results = last_tool_results(messages)
        if not results or "Files uploaded." not in str(results[-1].content):
            return reply(f"{FAILED} the upload was not confirmed.")
        return reply(
            "Here's the film: the name rises in, the signal rule draws under it, and the line "
            "lands with almost two seconds left to read it."
        )

    return [measure, deliver, answer]


# -- reading the conversation --------------------------------------------------------------


def _person_turn(messages: Sequence[BaseMessage]) -> tuple[str, int, int]:
    """The text that started this turn, how many model replies have followed it, and where it
    sits in the conversation (what came before it is what the turn started from)."""
    replies = 0
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if isinstance(message, AIMessage):
            replies += 1
            continue
        if isinstance(message, HumanMessage):
            mid = str(getattr(message, "id", "") or "")
            if mid.startswith(("today:", "running:", "steer:")):
                continue
            content = message.content if isinstance(message.content, str) else str(message.content)
            return content, replies, index
    return "", replies, 0


def _phase(text: str, before: Sequence[BaseMessage]) -> str:
    """The job this turn does, from its words and what the thread had before it began (a board
    this turn publishes does not change the job it is doing)."""
    lower = text.lower()
    if text.startswith(NOTICE):
        return "finish" if "film" in lower or "render" in lower else "quiet"
    has_board = bool(_board_id(before))
    if has_board and re.search(r"\bapprove|go ahead|looks good|build it", lower):
        return "film"
    if has_board and re.search(r"\bnotes?\b|feedback|changes?", lower):
        return "revise"
    if not has_board:
        return "storyboard"
    return "chat"


def _feedback(messages: Sequence[BaseMessage]) -> dict[str, Any]:
    """What `canvas_read_feedback` returned this turn: frames with open notes, note ids, authors."""
    for message in reversed(messages):
        if isinstance(message, ToolMessage) and "Notes are people's feedback" in str(
            message.content
        ):
            text = str(message.content)
            data = last_json([AIMessage(content=""), message])
            frames = data.get("frames", []) if isinstance(data, dict) else []
            asked = [
                str(f.get("frame"))
                for f in frames
                if isinstance(f, dict) and (f.get("open") or f.get("verdict") == "changes")
            ]
            notes = [str(n) for f in frames if isinstance(f, dict) for n in f.get("open") or []]
            authors = sorted(set(re.findall(r"^\s+cm_[0-9a-f]+ ([^:]+):", text, re.M)))
            return {"asked": asked, "notes": notes, "authors": authors}
    return {"asked": [], "notes": [], "authors": []}


def _asked(messages: Sequence[BaseMessage]) -> list[str]:
    return list(_feedback(messages)["asked"])


def next_step(messages: Sequence[BaseMessage]) -> AIMessage:
    text, done, start = _person_turn(messages)
    plan = asset_plan(messages, text, start)
    if plan is not None:
        return plan[done](messages) if done < len(plan) else reply("That's done.")
    phase = _phase(text, messages[:start])
    plan = {
        "storyboard": storyboard_steps,
        "revise": revise_steps,
        "film": film_steps,
        "finish": finish_steps,
    }.get(phase, list)()
    if phase == "quiet":
        return reply("[quiet]")
    if not plan:
        return reply(
            "I'm the demo lead, so I follow one job: a storyboard on the canvas, your notes, then "
            "the film. Leave notes on the board or approve it to go on."
        )
    if done >= len(plan):
        return reply("That's done.")
    return plan[done](messages)


# -- assets on the canvas ----------------------------------------------------------------------

#: One asset in an ask's list: `- as_… “Title”, <how the lead reads its kind>: brief. Made from …`
ASSET_LINE = re.compile(r"^- (as_[0-9a-f]+) “([^”]*)”, (.*)$", re.M)
#: One asset asked for by its kind alone.
ONE_ASSET = re.compile(r"\(What they want back: (.+?)\. On the canvas it is (as_[0-9a-f]+):")
CARD_SIZES: tuple[tuple[int, int, str], ...] = (
    (1080, 1350, "Portrait"),
    (1080, 1080, "Square"),
    (1600, 900, "Landscape"),
)
THUMB_SIZE = "1280x720"
SKIPPED = "The demo lead doesn't make this kind of work; a model does."
THUMB_CSS = """
html, body { margin: 0; width: 1280px; height: 720px; overflow: hidden;
  background: var(--brand-color-paper); }
#thumb { position: relative; width: 1280px; height: 720px; color: var(--brand-color-ink);
  font-family: var(--brand-font-text); }
.mark { position: absolute; top: 56px; left: 64px; width: 72px; height: 72px; }
.frame { position: absolute; inset: 0; width: 1280px; height: 720px; object-fit: cover; }
.band { position: absolute; left: 0; right: 0; bottom: 0; height: 232px;
  background: var(--brand-color-paper); }
.headline { position: absolute; left: 64px; right: 64px; bottom: 64px; margin: 0;
  font-family: var(--brand-font-display); font-weight: var(--brand-weight-display);
  font-size: 120px; line-height: 1; letter-spacing: -0.02em; }
.lead .headline { bottom: 180px; font-size: 168px; }
"""


@dataclass
class Asked:
    """An asset the thread asked for, as the demo lead reads the ask."""

    id: str
    kind: str
    title: str
    sources: list[str] = field(default_factory=list)
    gate: bool = False
    #: Films its sources handed over, as the ask names them.
    films: list[str] = field(default_factory=list)


@dataclass
class Track:
    """Where the assets stood when this turn began, from the conversation."""

    boards: dict[str, str] = field(default_factory=dict)
    by_title: dict[str, str] = field(default_factory=dict)
    approved: set[str] = field(default_factory=set)
    noted: set[str] = field(default_factory=set)
    delivered: set[str] = field(default_factory=set)
    skipped: set[str] = field(default_factory=set)
    rendering: set[str] = field(default_factory=set)


def _text(message: BaseMessage) -> str:
    return message.content if isinstance(message.content, str) else str(message.content)


def _kind_of(words: str) -> str:
    return next((c.id for c in CAPABILITIES if words.startswith(c.asks)), "")


def asked_assets(messages: Sequence[BaseMessage]) -> list[Asked]:
    found: dict[str, Asked] = {}
    for message in messages:
        if not isinstance(message, HumanMessage):
            continue
        text = _text(message)
        for asset_id, title, rest in ASSET_LINE.findall(text):
            made_from = rest.split(" Made from ", 1)[1] if " Made from " in rest else ""
            found[asset_id] = Asked(
                id=asset_id,
                kind=_kind_of(rest),
                title=title,
                sources=re.findall(r"as_[0-9a-f]+", made_from),
                gate="signs it off" in rest,
                films=re.findall(r"/workspace/\S+?\.(?:mp4|mov|webm)", made_from),
            )
        for asks, asset_id in ONE_ASSET.findall(text):
            made = capability(_kind_of(asks))
            title = made.title if made is not None else "Work"
            found.setdefault(asset_id, Asked(id=asset_id, kind=_kind_of(asks), title=title))
    return list(found.values())


def _signoffs(text: str, track: Track) -> tuple[set[str], set[str]]:
    """The assets a person's message approved and sent notes on, by their boards' titles."""
    approved = {track.by_title[t] for t in re.findall(r"Approved “([^”]+)”", text)}
    noted = {track.by_title[t] for t in re.findall(r"I left notes on “([^”]+)”", text)}
    return approved - {""}, noted - {""}


def track_assets(messages: Sequence[BaseMessage]) -> Track:
    track = Track()
    track.by_title = _TitleMap()
    results = {m.tool_call_id: _text(m) for m in messages if isinstance(m, ToolMessage)}
    for message in messages:
        if isinstance(message, HumanMessage):
            approved, noted = _signoffs(_text(message), track)
            track.approved |= approved
            track.noted |= noted
            continue
        if not isinstance(message, AIMessage):
            continue
        for call in message.tool_calls:
            args = call.get("args") or {}
            said = results.get(str(call.get("id") or ""), "")
            asset = str(args.get("asset") or "")
            if call["name"] == "canvas_publish_board" and asset:
                board = re.search(r"\bboard (b_[0-9a-f]+)", said)
                if board:
                    track.boards[asset] = board.group(1)
                track.by_title[str(args.get("title") or "")] = asset
            elif call["name"] == "canvas_deliver" and re.search(r"Delivered|already on", said):
                track.delivered.add(asset)
            elif call["name"] == "canvas_update_asset" and args.get("status") == "skipped":
                track.skipped.add(asset)
            elif call["name"] == "start_render_job":
                command = str(args.get("command") or "")
                track.rendering.update(re.findall(r"renders/(as_[0-9a-f]+)\.mp4", command))
    return track


class _TitleMap(dict[str, str]):
    """A board's title to its asset; a title nobody published reads as no asset."""

    def __missing__(self, key: str) -> str:
        return ""


def asset_plan(messages: Sequence[BaseMessage], text: str, start: int) -> list[Step] | None:
    """This turn's steps when the thread asked for assets by id, or None when it never did."""
    assets = asked_assets(messages)
    if not assets:
        return None
    known = {a.id for a in assets}
    track = track_assets(messages[:start])
    approved_now, noted_now = _signoffs(text, track)
    ready = track.approved | track.delivered | track.skipped | approved_now
    steps: list[Step] = []
    lines: list[str] = []
    if text.startswith(NOTICE):
        landed = [a for a in assets if a.id in track.rendering and a.id not in track.delivered]
        if not landed or "finished" not in text.lower():
            return [lambda _: reply("[quiet]")]
        for asset in landed:
            steps += finish_asset_film(asset)
            lines.append(f"“{asset.title}” is on its card: four seconds at 1920×1080.")
            ready.add(asset.id)
    for asset in assets:
        if asset.id in approved_now and asset.kind == "video" and asset.id not in track.rendering:
            steps += build_asset_film(asset)
            lines.append(f"“{asset.title}” passed its checks and is rendering.")
        elif asset.id in approved_now and asset.kind in ("still", "thumbs"):
            steps += deliver_asset_board(asset)
            lines.append(f"“{asset.title}” is delivered.")
        if asset.id in noted_now and asset.kind in ("board", "video") and asset.id in track.boards:
            steps += revise_asset(asset, track.boards[asset.id])
            lines.append(f"A new version of “{asset.title}” answers the notes.")
        elif asset.id in noted_now:
            lines.append(
                f"The demo lead revises storyboards only; approve “{asset.title}” instead."
            )
    begun = set(track.boards) | track.delivered | track.skipped | track.rendering
    begun |= approved_now | noted_now
    for asset in assets:
        if asset.id in begun or not all(s in ready or s not in known for s in asset.sources):
            continue
        made, line = make_asset(asset, assets)
        steps += made
        lines.append(line)

    def answer(messages: Sequence[BaseMessage]) -> AIMessage:
        if failure := _failed(messages):
            return reply(f"{FAILED} a step did not pass its checks ({failure}).")
        return reply(" ".join(lines) or "Nothing on the canvas is waiting on me.")

    return [*steps, answer]


def make_asset(asset: Asked, assets: Sequence[Asked]) -> tuple[list[Step], str]:
    kinds = {a.id: a.kind for a in assets}
    if asset.kind == "board":
        return asset_storyboard(asset), f"“{asset.title}” is on the canvas for your sign-off."
    if asset.kind == "video" and any(kinds.get(s) == "board" for s in asset.sources):
        return build_asset_film(asset), f"“{asset.title}” passed its checks and is rendering."
    if asset.kind == "video" and not asset.sources:
        return (
            asset_storyboard(asset, title="Storyboard"),
            f"The storyboard for “{asset.title}” is on the canvas; approve it and I'll build it.",
        )
    if asset.kind == "still":
        return asset_cards(asset), f"“{asset.title}” is up for review in three sizes."
    film = _film_for(asset, kinds)
    if asset.kind == "thumbs" and film:
        return asset_thumbs(asset, film), (
            f"“{asset.title}” is up for review: one arm leads with the line, one with a real frame."
        )
    if asset.kind == "gif" and film:
        return asset_gif(asset, film), f"“{asset.title}” is on its card: a 4-second loop."
    if asset.kind == "chart":
        return asset_chart(asset), f"“{asset.title}” is on its card."
    return [
        _skip(asset)
    ], f"I skipped “{asset.title}”: the demo lead doesn't make that kind of work."


def _film_for(asset: Asked, kinds: dict[str, str]) -> str:
    if asset.films:
        return asset.films[0]
    source = next((s for s in asset.sources if kinds.get(s) == "video"), "")
    return _film_path(source) if source else ""


def _film_path(asset_id: str) -> str:
    return f"{PROJECT}/renders/{asset_id}.mp4"


def _making(asset: Asked) -> tuple[str, dict[str, Any]]:
    return ("canvas_update_asset", {"asset": asset.id, "status": "making"})


def _skip(asset: Asked) -> Step:
    def skip(_: Sequence[BaseMessage]) -> AIMessage:
        return tool_calls(
            ("canvas_update_asset", {"asset": asset.id, "status": "skipped", "note": SKIPPED})
        )

    return skip


def _checked(make: Callable[[Sequence[BaseMessage]], AIMessage], what: str) -> Step:
    """A step that goes on only if the one before it passed."""

    def step(messages: Sequence[BaseMessage]) -> AIMessage:
        if failure := _failed(messages):
            return reply(f"{FAILED} {what} did not pass its checks ({failure}).")
        return make(messages)

    return step


def asset_storyboard(asset: Asked, *, title: str = "") -> list[Step]:
    folder = f"{PROJECT}/{asset.id}"

    def pose(_: Sequence[BaseMessage]) -> AIMessage:
        return tool_calls(
            _making(asset),
            *(
                (
                    "write_file",
                    {"file_path": f"{folder}/{beat[0]}.html", "content": pose_html(beat)},
                )
                for beat in BEATS
            ),
            content="Posing the three beats in the brand's tokens.",
        )

    def render(_: Sequence[BaseMessage]) -> AIMessage:
        command = _render([b[0] for b in BEATS], folder=folder)
        return tool_calls(("execute", {"command": command, "timeout": 300}))

    def publish(_: Sequence[BaseMessage]) -> AIMessage:
        frames = [
            {"path": _pose_path(b[0], folder=folder), "name": b[1], "note": b[2]} for b in BEATS
        ]
        board = {
            "project": "studio-teaser",
            "title": title or asset.title,
            "kind": "storyboard",
            "frames": frames,
            "asset": asset.id,
        }
        return tool_calls(("canvas_publish_board", board))

    return [pose, _checked(render, "a pose"), _checked(publish, "a pose")]


def revise_asset(asset: Asked, board: str) -> list[Step]:
    folder = f"{PROJECT}/{asset.id}"

    def read(_: Sequence[BaseMessage]) -> AIMessage:
        return tool_calls(("canvas_read_feedback", {"board": board}))

    def repose(messages: Sequence[BaseMessage]) -> AIMessage:
        asked = _asked(messages)
        if not asked:
            return reply(f"I don't see open notes on “{asset.title}”.")
        return tool_calls(
            *(
                (
                    "write_file",
                    {
                        "file_path": f"{folder}/{beat[0]}-v2.html",
                        "content": pose_html(beat, revised=True),
                    },
                )
                for beat in BEATS
                if beat[1] in asked
            ),
            content="Re-posing only the frames with notes.",
        )

    def render(messages: Sequence[BaseMessage]) -> AIMessage:
        stems = [b[0] for b in BEATS if b[1] in _asked(messages)]
        return tool_calls(("execute", {"command": _render(stems, "-v2", folder=folder)}))

    def publish(messages: Sequence[BaseMessage]) -> AIMessage:
        feedback = _feedback(messages)
        frames = [
            {"path": _pose_path(b[0], "-v2", folder=folder), "name": b[1], "note": b[2]}
            for b in BEATS
            if b[1] in feedback["asked"]
        ]
        if not frames:
            return reply("I don't see open notes on that board.")
        board_args = {
            "project": "studio-teaser",
            "title": asset.title,
            "kind": "storyboard",
            "frames": frames,
            "replaces": board,
            "answers": feedback["notes"],
            "asset": asset.id,
        }
        return tool_calls(("canvas_publish_board", board_args))

    return [read, repose, _checked(render, "a revised pose"), _checked(publish, "a revised pose")]


def build_asset_film(asset: Asked) -> list[Step]:
    folder = f"{PROJECT}/{asset.id}"

    def compose(_: Sequence[BaseMessage]) -> AIMessage:
        return tool_calls(
            _making(asset),
            ("write_file", {"file_path": f"{folder}/index.html", "content": teaser_html()}),
            content=f"Building “{asset.title}” from the approved storyboard.",
        )

    def gate(_: Sequence[BaseMessage]) -> AIMessage:
        command = (
            "cp /workspace/brand/tokens.css /workspace/brand/logos/mark.svg "
            f"/opt/design-agent/render/node_modules/gsap/dist/gsap.min.js {folder}/ && "
            f"node /workspace/tools/video-gate.mjs {folder}/index.html --json && "
            f"node /workspace/tools/brand-lint.mjs {folder}/index.html && "
            f"hyperframes check {folder}"
        )
        return tool_calls(("execute", {"command": command, "timeout": 300}))

    def render(_: Sequence[BaseMessage]) -> AIMessage:
        command = (
            f"hyperframes render {folder} --quality draft --fps 30 --output {_film_path(asset.id)}"
        )
        job = {"command": command, "label": asset.title, "kind": "hyperframes"}
        return tool_calls(("start_render_job", job))

    return [compose, _checked(gate, "the film"), _checked(render, "the film")]


def finish_asset_film(asset: Asked) -> list[Step]:
    film = _film_path(asset.id)

    def measure(_: Sequence[BaseMessage]) -> AIMessage:
        command = f"node /workspace/tools/artifact-contract.mjs --expect {film}:{SIZE}@4 --json"
        return tool_calls(("execute", {"command": command}))

    def deliver(messages: Sequence[BaseMessage]) -> AIMessage:
        result = last_json(messages)
        if result and result.get("ok") is not True:
            return reply(f"{FAILED} “{asset.title}” did not measure as asked.")
        note = "Four seconds at 1920×1080."
        return tool_calls(("canvas_deliver", {"asset": asset.id, "paths": [film], "note": note}))

    return [measure, deliver]


def _card_paths(asset: Asked) -> list[str]:
    return [f"{PROJECT}/{asset.id}/poses/card-{w}x{h}.png" for w, h, _ in CARD_SIZES]


def asset_cards(asset: Asked) -> list[Step]:
    folder = f"{PROJECT}/{asset.id}"

    def write(_: Sequence[BaseMessage]) -> AIMessage:
        return tool_calls(
            _making(asset),
            ("write_file", {"file_path": f"{folder}/card.html", "content": card_html()}),
            content="One page that lays itself out again for each size.",
        )

    def render(_: Sequence[BaseMessage]) -> AIMessage:
        sizes = " ".join(f"--size {w}x{h}" for w, h, _ in CARD_SIZES)
        command = (
            f"node /workspace/tools/brand-lint.mjs {folder}/card.html && "
            f"node /workspace/tools/html2png.mjs {folder}/card.html --out {folder}/poses "
            f"--name card {sizes} --brand-fonts"
        )
        return tool_calls(("execute", {"command": command, "timeout": 300}))

    def publish(_: Sequence[BaseMessage]) -> AIMessage:
        frames = [
            {"path": path, "name": f"{name} · {w}×{h}"}
            for path, (w, h, name) in zip(_card_paths(asset), CARD_SIZES, strict=True)
        ]
        board = {
            "project": "studio-teaser",
            "title": asset.title,
            "kind": "stills",
            "frames": frames,
            "asset": asset.id,
        }
        return tool_calls(("canvas_publish_board", board))

    return [write, _checked(render, "a card"), _checked(publish, "a card")]


def _thumb_paths(asset: Asked) -> list[str]:
    return [f"{PROJECT}/{asset.id}/poses/thumb-{arm}-{THUMB_SIZE}.png" for arm in ("a", "b")]


def thumb_html(arm: str) -> str:
    lead = arm == "a"
    stage = ' class="lead"' if lead else ""
    body = (
        '<img class="mark" src="/workspace/brand/logos/mark.svg" alt="Example Studio" />'
        if lead
        else '<img class="frame" src="frame.png" alt="" /><div class="band"></div>'
    )
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8" />'
        f"<title>Thumbnail {arm.upper()}</title>"
        '<link rel="stylesheet" href="/workspace/brand/tokens.css" />'
        f"<style>{THUMB_CSS}</style></head><body>"
        f'<main id="thumb"{stage}>{body}'
        '<h1 class="headline" data-thumb-role="hero">Every size, one pass.</h1>'
        "</main></body></html>\n"
    )


def asset_thumbs(asset: Asked, film: str) -> list[Step]:
    folder = f"{PROJECT}/{asset.id}"

    def write(_: Sequence[BaseMessage]) -> AIMessage:
        return tool_calls(
            _making(asset),
            *(
                (
                    "write_file",
                    {"file_path": f"{folder}/thumb-{arm}.html", "content": thumb_html(arm)},
                )
                for arm in ("a", "b")
            ),
            content="Two arms: the line on its own, and the line over a real frame.",
        )

    def render(_: Sequence[BaseMessage]) -> AIMessage:
        grab = f"ffmpeg -y -loglevel error -ss 3 -i {film} -frames:v 1 {folder}/frame.png"
        command = f"{grab} && " + _render(["thumb-a", "thumb-b"], folder=folder, size=THUMB_SIZE)
        return tool_calls(("execute", {"command": command, "timeout": 300}))

    def publish(_: Sequence[BaseMessage]) -> AIMessage:
        names = ("A · The line", "B · A real frame")
        frames = [
            {"path": path, "name": name}
            for path, name in zip(_thumb_paths(asset), names, strict=True)
        ]
        board = {
            "project": "studio-teaser",
            "title": asset.title,
            "kind": "thumbnails",
            "frames": frames,
            "asset": asset.id,
        }
        return tool_calls(("canvas_publish_board", board))

    return [write, _checked(render, "a thumbnail"), _checked(publish, "a thumbnail")]


def deliver_asset_board(asset: Asked) -> list[Step]:
    """A signed-off board's finals: the files its frames were rendered as."""
    paths = _thumb_paths(asset) if asset.kind == "thumbs" else _card_paths(asset)

    def deliver(_: Sequence[BaseMessage]) -> AIMessage:
        return tool_calls(("canvas_deliver", {"asset": asset.id, "paths": paths}))

    return [deliver]


def asset_gif(asset: Asked, film: str) -> list[Step]:
    out = f"{PROJECT}/{asset.id}/loop.gif"
    palette = "fps=12,scale=640:-1:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff[p];"
    palette += "[b][p]paletteuse=dither=bayer"

    def encode(_: Sequence[BaseMessage]) -> AIMessage:
        command = (
            f"mkdir -p {PROJECT}/{asset.id} && "
            f"ffmpeg -y -loglevel error -t 4 -i {film} -vf '{palette}' {out} && ls -l {out}"
        )
        return tool_calls(_making(asset), ("execute", {"command": command, "timeout": 300}))

    def deliver(_: Sequence[BaseMessage]) -> AIMessage:
        note = "A 4-second loop, 640 wide."
        return tool_calls(("canvas_deliver", {"asset": asset.id, "paths": [out], "note": note}))

    return [encode, _checked(deliver, "the GIF")]


def asset_chart(asset: Asked) -> list[Step]:
    relative = f"projects/studio-teaser/{asset.id}"
    spec = {
        "kind": "stat-card",
        "colors": {"ground": "--brand-color-paper"},
        "width": 1080,
        "height": 1080,
        "data": {
            "value": 3,
            "label": "Sizes from one pass",
            "baseline": {"value": 1, "label": "Up from"},
            "change": "ratio",
        },
        "out": f"{relative}/stat.png",
    }

    def write(_: Sequence[BaseMessage]) -> AIMessage:
        content = json.dumps(spec, indent=2)
        return tool_calls(
            _making(asset),
            ("write_file", {"file_path": f"/workspace/{relative}/stat.json", "content": content}),
        )

    def render(_: Sequence[BaseMessage]) -> AIMessage:
        command = (
            f"cd /workspace && node skills/data-viz/scripts/viz.mjs --spec {relative}/stat.json"
        )
        return tool_calls(("execute", {"command": command, "timeout": 300}))

    def deliver(_: Sequence[BaseMessage]) -> AIMessage:
        paths = [f"/workspace/{relative}/stat.png"]
        return tool_calls(("canvas_deliver", {"asset": asset.id, "paths": paths}))

    return [write, _checked(render, "the stat card"), _checked(deliver, "the stat card")]


class DemoDirector(BaseChatModel):
    """The demo's lead (module doc). Stateless: each call reads the conversation."""

    provider_name: str = "scripted"
    model_name: str = "house-demo"

    @property
    def _llm_type(self) -> str:
        return "house-demo-director"

    def _get_ls_params(self, stop: list[str] | None = None, **kwargs: Any) -> Any:  # noqa: ARG002
        return {"ls_provider": self.provider_name, "ls_model_name": self.model_name}

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Callable[..., Any] | BaseTool],
        *,
        tool_choice: str | None = None,  # noqa: ARG002 - provider signature
        **kwargs: Any,
    ) -> Runnable[LanguageModelInput, AIMessage]:
        formatted = [t if isinstance(t, dict) else convert_to_openai_tool(t) for t in tools]
        return self.bind(tools=formatted, **kwargs)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,  # noqa: ARG002 - provider signature
        run_manager: CallbackManagerForLLMRun | None = None,  # noqa: ARG002
        **kwargs: Any,  # noqa: ARG002
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=next_step(messages))])
