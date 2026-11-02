"""Project state from the thread's sandbox: recent projects and one project's render status."""

from __future__ import annotations

import json
import posixpath
import re
from datetime import datetime
from typing import Any

from deepagents.backends.protocol import BackendProtocol, FileInfo
from langchain.tools import ToolRuntime
from langchain_core.tools import BaseTool, StructuredTool

from design_agent.tools.files import BackendFor, WorkspaceError, read_bytes, require_backend

PROJECTS_ROOT = "/workspace/projects"
OUTPUT_SUFFIXES = (
    ".mp4",
    ".mov",
    ".webm",
    ".gif",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".pdf",
    ".svg",
    ".wav",
    ".mp3",
)
PROJECT_SLUG = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
STAGE_FILES = ("BRIEF.md", "PLAN.md", "run.json", "DELIVERY.json")
RUN_FIELDS = ("status", "phase", "step", "eta", "cost_usd", "started_at", "finished_at")


async def _entries(backend: BackendProtocol, path: str) -> list[FileInfo]:
    try:
        result = await backend.als(path)
    except Exception:  # noqa: BLE001 - backend errors can carry paths and hosts
        raise WorkspaceError(f"could not list {path}: sandbox read failed.") from None
    if result.error:
        raise WorkspaceError(f"could not list {path}: directory missing or unreadable.")
    return [e for e in result.entries or [] if posixpath.dirname(e["path"].rstrip("/")) == path]


def _name(entry: FileInfo) -> str:
    return posixpath.basename(entry["path"].rstrip("/"))


def _modified(entry: FileInfo) -> float:
    value = entry.get("modified_at")
    if not value:
        return 0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (ValueError, OverflowError):
        return 0


async def _outputs(backend: BackendProtocol, project: str) -> list[str]:
    try:
        entries = await _entries(backend, f"{project}/renders")
    except WorkspaceError:
        return []
    return sorted(
        _name(e)
        for e in entries
        if not e.get("is_dir", False) and _name(e).lower().endswith(OUTPUT_SUFFIXES)
    )


def build_project_tools(backend_for: BackendFor) -> list[BaseTool]:
    async def list_recent_projects(runtime: ToolRuntime, limit: int = 10) -> str:
        """List recent projects in this thread's computer and whether each has renders.

        `limit` is 1 to 50. Renders existing does not mean anything was delivered.
        """
        try:
            backend = require_backend(backend_for, runtime)
            dirs = [
                e
                for e in await _entries(backend, PROJECTS_ROOT)
                if e.get("is_dir") and PROJECT_SLUG.fullmatch(_name(e))
            ]
            if not dirs:
                return "No projects yet."
            dirs.sort(key=lambda e: (_modified(e), _name(e)), reverse=True)
            capped = max(1, min(limit, 50))
            rows = []
            for entry in dirs[:capped]:
                outputs = await _outputs(backend, f"{PROJECTS_ROOT}/{_name(entry)}")
                state = f"{len(outputs)} render(s)" if outputs else "in progress"
                rows.append(
                    f"- {_name(entry)} (updated {entry.get('modified_at') or 'unknown'}): {state}"
                )
            return f"{len(dirs)} project(s); {min(capped, len(dirs))} most recent:\n" + "\n".join(
                rows
            )
        except WorkspaceError as error:
            return str(error)

    async def get_render_status(project_slug: str, runtime: ToolRuntime) -> str:
        """One project's files on disk, its renders and the status fields of its run.json.

        Pass one project folder name. Reads only this thread's computer.
        """
        if not PROJECT_SLUG.fullmatch(project_slug):
            return "Project name is not allowed; use one project folder name."
        project = f"{PROJECTS_ROOT}/{project_slug}"
        try:
            backend = require_backend(backend_for, runtime)
            if not any(
                _name(e) == project_slug and e.get("is_dir")
                for e in await _entries(backend, PROJECTS_ROOT)
            ):
                return f"No project named '{project_slug}'."
            names = {_name(e) for e in await _entries(backend, project)}
            stages = ", ".join(f"{n} {'yes' if n in names else 'no'}" for n in STAGE_FILES)
            outputs = await _outputs(backend, project)
            summary = "not written yet"
            if "run.json" in names:
                try:
                    data: Any = json.loads(
                        await read_bytes(backend, f"{project}/run.json", cap_mb=1)
                    )
                    picked = {
                        k: data[k] for k in RUN_FIELDS if isinstance(data, dict) and k in data
                    }
                    summary = json.dumps(picked) if picked else "present"
                except (WorkspaceError, ValueError, UnicodeError):
                    summary = "present (unreadable)"
            return "\n".join(
                [
                    project_slug,
                    f"files: {stages}",
                    "renders: " + (", ".join(outputs) or "none yet"),
                    f"run.json: {summary}",
                ]
            )
        except WorkspaceError as error:
            return str(error)

    return [
        StructuredTool.from_function(coroutine=list_recent_projects, name="list_recent_projects"),
        StructuredTool.from_function(coroutine=get_render_status, name="get_render_status"),
    ]
