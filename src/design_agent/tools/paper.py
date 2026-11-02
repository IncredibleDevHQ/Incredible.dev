"""Paper (paper.design): the tool policy the host and the bridge share, and the connection.

Paper's MCP server runs inside Paper Desktop. `PAPER_MODE` picks how the agent reaches it:

- `local`: Paper Desktop runs on the machine the agent runs on. The stdio server `paper mcp`
  (`~/.paper/bin/paper`, else `paper` on PATH) is preferred; `PAPER_MCP_URL` set to
  `http://127.0.0.1:29979/mcp` selects Desktop's legacy HTTP endpoint, served only while a file
  is open. Local and self-hosted runtimes only: MDA serves no stdio and cannot reach this loopback.
- `bridged`: Paper Desktop runs on a machine the person controls, behind `design-agent
  paper-bridge` (`design_agent.paper_bridge`), reached over a tunnel they own at `PAPER_MCP_URL`.
  Locally and self-hosted the bearer is `PAPER_BRIDGE_TOKEN`; on MDA it is the agent-owned
  workspace connection `paper-bridge`, resolved at call time and never compiled into the deploy.
- `off`: no server. Boards render in the sandbox and are attached to the thread.

`PaperPolicy` is the whole policy as data plus one pure decision, enforced twice: on the host by
`PaperScopeMiddleware` and in front of Desktop by the bridge, so neither a rolled-back bridge nor a
tool list that grows can widen what a model may do. Paper's tool names are not a stable contract
yet (`list_files` became `list_resources`), so nothing pins `include_tools`: a tool the policy
admits but the server stops advertising is missing alone, and one the server adds stays hidden
until the policy names it (`check_catalog`).
"""

from __future__ import annotations

import html
import json
import logging
import os
import re
import shutil
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from langchain_core.tools import BaseTool

from design_agent.tools.mcp import McpServer

if TYPE_CHECKING:
    from design_agent.config import RuntimeName, Settings

_LOGGER = logging.getLogger(__name__)

#: The MCP server name; its tools reach the model as `paper_<tool>` on every runtime.
SERVER = "paper"
PREFIX = f"{SERVER}_"
#: Paper Desktop's legacy HTTP endpoint, served only while a file is open.
LOCAL_HTTP = "http://127.0.0.1:29979/mcp"
#: The MDA workspace connection holding the bridge's bearer token.
BRIDGE_CONNECTION = "paper-bridge"
#: Screenshots and exports render on the Desktop machine; a cold first call can take a while.
TIMEOUT_S = 120.0

READ_TOOLS = frozenset(
    {
        "get_basic_info",
        "get_selection",
        "get_node_info",
        "get_children",
        "get_screenshot",
        "get_jsx",
        "get_tree_summary",
        "get_computed_styles",
        "get_fill_image",
        "find_nodes",
        "list_comment_threads",
        "get_comment_thread",
        "list_comment_thread_authors",
        "get_tokens",
        "get_font_family_info",
        "get_guide",
    }
)
#: Canvas edits. Drafting on the canvas is the collaboration itself, so they need no approval;
#: none of them reaches the brand file.
EDIT_TOOLS = frozenset(
    {
        "create_artboard",
        "create_page",
        "write_html",
        "set_text_content",
        "rename_nodes",
        "update_styles",
        "duplicate_nodes",
        "move_nodes",
        "finish_working_on_nodes",
    }
)
FILE_TOOLS = frozenset({"list_resources", "open_file", "create_file"})
#: Allowed whenever Paper is connected (Local and Bridged): Paper renders the bytes either way.
EXPORT_TOOLS = frozenset({"export", "export_combined_pdf"})
#: Opt-in per deployment (`PAPER_ALLOW_DELETES`, `PAPER_ALLOW_TOKEN_WRITES`); reorganizing pages
#: and renaming files has no setting yet, so it stays off.
DELETE_TOOLS = frozenset({"delete_nodes"})
TOKEN_WRITE_TOOLS = frozenset({"create_tokens", "set_tokens"})
REORG_TOOLS = frozenset({"arrange_pages", "update_pages", "rename_resource"})
#: Advertised by Paper and never admitted: resolving a comment thread tells people their review
#: was handled, which is a person's call.
NEVER_TOOLS = frozenset({"set_comment_thread_status"})
KNOWN_TOOLS = (
    READ_TOOLS
    | EDIT_TOOLS
    | FILE_TOOLS
    | EXPORT_TOOLS
    | DELETE_TOOLS
    | TOKEN_WRITE_TOOLS
    | REORG_TOOLS
    | NEVER_TOOLS
)
#: Paper Desktop writes an export into the Downloads folder of the machine it runs on and returns
#: the paths (`{"exports": [{"nodeId", "filePath"}]}`), so whatever runs beside Desktop reads them
#: back: the host in Local mode, the bridge in Bridged mode.
EXPORT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".avif": "image/avif",
    ".svg": "image/svg+xml",
    ".pdf": "application/pdf",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
}
MAX_EXPORT_BYTES = 200 * 1024 * 1024
#: A file's modification time and the clock the call started on can disagree by a moment.
_EXPORT_CLOCK_SLACK_S = 2.0


@dataclass(frozen=True)
class ExportedFile:
    data: bytes
    mime_type: str


def exported_paths(text: str) -> list[str]:
    """The file paths in one block of Paper's export result, or none."""
    try:
        value = json.loads(text)
    except ValueError:
        return []
    exports = value.get("exports") if isinstance(value, dict) else None
    if not isinstance(exports, list):
        return []
    return [
        item["filePath"]
        for item in exports
        if isinstance(item, dict) and isinstance(item.get("filePath"), str)
    ]


def take_exports(
    texts: Iterable[str], *, since: float, folder: Path | None = None
) -> list[ExportedFile]:
    """The files a Paper export just wrote, read and removed from `folder` (Downloads by default).

    A path outside that folder, of another type, over the size cap or older than the call is left
    where it is, so nothing the person put there is touched.
    """
    home = (folder or Path.home() / "Downloads").resolve()
    taken: list[ExportedFile] = []
    for text in texts:
        for raw in exported_paths(text):
            try:
                path = Path(raw).resolve(strict=True)
                stat = path.stat()
            except OSError:
                continue
            mime_type = EXPORT_TYPES.get(path.suffix.lower())
            if (
                mime_type is None
                or not path.is_relative_to(home)
                or not path.is_file()
                or stat.st_size > MAX_EXPORT_BYTES
                or stat.st_mtime < since - _EXPORT_CLOCK_SLACK_S
            ):
                continue
            try:
                data = path.read_bytes()
                path.unlink()
            except OSError:
                continue
            taken.append(ExportedFile(data, mime_type))
    return taken


#: Tools that take no `fileId`.
GLOBAL_TOOLS = frozenset({"get_guide", "list_resources", "create_file", "rename_resource"})
#: File-scoped calls that must name their file instead of defaulting to the drafts file:
#: `open_file` switches the file Desktop shows the person, and a defaulted token read would answer
#: a brand question with the drafts file's tokens, which are seeded from the same definitions and
#: so look right.
ADDRESSED_TOOLS = frozenset({"open_file", "get_tokens"})
#: Calls that change the file they name, refused on the brand file whatever the opt-ins say.
WRITE_TOOLS = EDIT_TOOLS | DELETE_TOOLS | TOKEN_WRITE_TOOLS | {"arrange_pages", "update_pages"}

#: Paper's paid image generation and its local-file imports both arrive as resource URIs inside
#: ordinary arguments, so they are matched against the whole argument payload, not one field. The
#: word boundary keeps `profile:` out of it.
_IMPORT_SCHEMES = re.compile(r"\b(?:paper-asset|file):")
#: What a URL or HTML parser drops before it resolves a scheme, literal and JSON-escaped.
_SEPARATORS = re.compile(r"[\t\n\r]|\\[tnr]")
_PAPER_LINK = re.compile(r"/file/([A-Za-z0-9]+)(?:/[A-Za-z0-9-]+)*/*")
_ID_KEYS = ("fileId", "cloneFileId", "resourceId")

GENERATION_OFF = (
    "Paper's AI image generation (paper-gen:) is off for this deployment; build the visual from "
    "brand tokens, shapes and type instead."
)
IMPORTS_REFUSED = (
    "Paper local-file references (paper-asset:, file:) are refused here; build the visual from "
    "HTML, SVG and brand tokens instead."
)
BRAND_READ_ONLY = (
    "The Paper brand file is read-only; work in the drafts file and read the brand file with the "
    "read tools."
)
BRAND_NO_CLONE = (
    "The Paper brand file is not copied from here; work in the drafts file and read the brand "
    "file with the read tools."
)
BAD_FILE_ID = "That is not a Paper file id or app.paper.design link; pass the file's id."
_OFF = {
    "deletes": (
        "Deleting on the Paper canvas is off for this deployment; hide or move the layer instead."
    ),
    "tokens": "Changing Paper tokens is off for this deployment; use the tokens as they are.",
    "reorg": (
        "Reorganizing Paper pages and files is off for this deployment; leave their order and "
        "names as they are."
    ),
    "unknown": "That Paper tool is not available here; use the paper_ tools in your tool list.",
}


class PaperConfigError(ValueError):
    """`PAPER_*` settings describe a connection this runtime cannot make."""


def file_id(value: object) -> str | None:
    """The bare file id behind either spelling Paper accepts, or None for anything else.

    A link is what a person pastes (`https://app.paper.design/file/<id>[/<page>]`), so both
    enforcement points compare the id behind it rather than the exact string. Case, a port or
    userinfo in the link would otherwise read as somewhere else and walk a brand-file link past
    the check.
    """
    if not isinstance(value, str):
        return None
    if value.isascii() and value.isalnum():
        return value
    url = urlsplit(value)
    if url.username or url.password or url.port not in (None, 443):
        return None
    if (url.scheme, url.hostname or "") not in {("", ""), ("https", "app.paper.design")}:
        return None
    match = _PAPER_LINK.fullmatch(url.path)
    return match[1] if match else None


def link(file: str, page: str | None = None) -> str:
    """The app link to a file (and page) this code built from validated ids."""
    return f"https://app.paper.design/file/{file}" + (f"/{page}" if page else "")


def payload(args: Mapping[str, object]) -> str:
    """The whole call as one string, normalized the way its readers normalize it.

    HTML and URL parsers drop ASCII tab, newline and carriage return before they resolve a scheme,
    so `fi&#9;le:` loads what `file:` does; they come out here in both spellings a JSON payload can
    carry (the character and its two-character escape). Entities are resolved twice because one
    can encode the character that hides the next, and lowering happens between the passes so
    `&COLON;` is resolved rather than left as written.
    """
    text = json.dumps(args, default=str)
    for _ in range(2):
        text = html.unescape(text).lower()
    return _SEPARATORS.sub("", text)


@dataclass(frozen=True)
class Decision:
    """A call's outcome: the arguments to forward, or the sentence the caller reads instead."""

    args: dict[str, Any]
    refusal: str | None = None
    file: str | None = None
    """The file the call acts on, after the drafts default."""


@dataclass(frozen=True)
class PaperPolicy:
    """What a Paper call may do. Built from settings; identical on the host and the bridge."""

    brand_file_id: str | None = None
    drafts_file_id: str | None = None
    allow_deletes: bool = False
    allow_token_writes: bool = False
    allow_reorg: bool = False
    allow_generation: bool = False

    def __post_init__(self) -> None:
        for setting, value in (
            ("PAPER_BRAND_FILE_ID", self.brand_file_id),
            ("PAPER_DRAFTS_FILE_ID", self.drafts_file_id),
        ):
            if value is not None and file_id(value) != value:
                raise PaperConfigError(
                    f"{setting} must be a plain Paper file id, not a link or a path"
                )
        if self.brand_file_id is not None and self.brand_file_id == self.drafts_file_id:
            raise PaperConfigError(
                "PAPER_DRAFTS_FILE_ID must be a different file from PAPER_BRAND_FILE_ID"
            )

    @classmethod
    def from_settings(cls, settings: Settings) -> PaperPolicy:
        return cls(
            brand_file_id=settings.paper_brand_file_id,
            drafts_file_id=settings.paper_drafts_file_id,
            allow_deletes=settings.paper_allow_deletes,
            allow_token_writes=settings.paper_allow_token_writes,
            allow_reorg=settings.paper_allow_reorg,
            allow_generation=settings.paper_allow_generation,
        )

    @property
    def admitted(self) -> frozenset[str]:
        tools = READ_TOOLS | EDIT_TOOLS | FILE_TOOLS | EXPORT_TOOLS
        if self.allow_deletes:
            tools |= DELETE_TOOLS
        if self.allow_token_writes:
            tools |= TOKEN_WRITE_TOOLS
        if self.allow_reorg:
            tools |= REORG_TOOLS
        return tools

    def decide(self, tool: str, args: Mapping[str, Any]) -> Decision:
        """Admit, aim or refuse one call to Paper's `tool` (its bare name, no server prefix).

        Order: the allowlist, the resource schemes over the whole payload, file ids normalized to
        bare ids, the brand file's read-only and no-clone rules, then the drafts default for a
        file-scoped call that names no file.
        """
        forwarded = dict(args)
        refusal = self._not_admitted(tool) or self._scheme(forwarded)
        if refusal is not None:
            return Decision(forwarded, refusal)
        for key in _ID_KEYS:
            if forwarded.get(key) in (None, ""):
                forwarded.pop(key, None)
                continue
            bare = file_id(forwarded[key])
            if bare is None:
                return Decision(forwarded, BAD_FILE_ID)
            forwarded[key] = bare
        refusal = self._brand_target(tool, forwarded)
        if refusal is not None:
            return Decision(forwarded, refusal)
        if tool in GLOBAL_TOOLS:
            return Decision(forwarded)
        if forwarded.get("fileId"):
            return Decision(forwarded, file=forwarded["fileId"])
        if tool in ADDRESSED_TOOLS or self.drafts_file_id is None:
            return Decision(forwarded, self._name_the_file(tool))
        return Decision({**forwarded, "fileId": self.drafts_file_id}, file=self.drafts_file_id)

    def _not_admitted(self, tool: str) -> str | None:
        if tool in self.admitted:
            return None
        if tool in DELETE_TOOLS:
            return _OFF["deletes"]
        if tool in TOKEN_WRITE_TOOLS:
            return _OFF["tokens"]
        if tool in REORG_TOOLS:
            return _OFF["reorg"]
        return _OFF["unknown"]

    def _scheme(self, args: Mapping[str, Any]) -> str | None:
        text = payload(args)
        if "paper-gen:" in text and not self.allow_generation:
            return GENERATION_OFF
        return IMPORTS_REFUSED if _IMPORT_SCHEMES.search(text) else None

    def _brand_target(self, tool: str, args: Mapping[str, Any]) -> str | None:
        """Whether the call would change the brand file or copy it into a writable twin.

        A clone is the other way to a writable brand file: the copy has a new id, so every later
        write to it would pass. Making a team copy is an operator's job in Paper itself.
        """
        brand = self.brand_file_id
        if brand is None:
            return None
        if args.get("cloneFileId") == brand:
            return BRAND_NO_CLONE
        if tool == "rename_resource" and args.get("resourceId") == brand:
            return BRAND_READ_ONLY
        return BRAND_READ_ONLY if tool in WRITE_TOOLS and args.get("fileId") == brand else None

    def _name_the_file(self, tool: str) -> str:
        known = []
        if self.drafts_file_id is not None:
            known.append(f"the drafts file is {self.drafts_file_id}")
        if self.brand_file_id is not None:
            known.append(f"the brand file is {self.brand_file_id} (read-only)")
        where = "; ".join(known) if known else "list_resources lists the files"
        return f"Pass fileId on {tool}: {where}, or use the id of the file you are working in."

    def note(self) -> str | None:
        """One line for the model naming the configured files, or None when there are none."""
        parts = []
        if self.drafts_file_id is not None:
            parts.append(
                f"Paper drafts file: {self.drafts_file_id} (calls without fileId go there)."
            )
        if self.brand_file_id is not None:
            parts.append(f"Paper brand file: {self.brand_file_id} (read-only).")
        return " ".join(parts) or None


@dataclass(frozen=True)
class Catalog:
    """How the tools a Paper server advertises line up with the policy."""

    admitted: frozenset[str]
    missing: frozenset[str]
    """Admitted by the policy, not advertised: those tools alone are unavailable."""
    unknown: frozenset[str]
    """Advertised, not named by the policy: hidden until the policy names them."""


def check_catalog(advertised: Iterable[str], policy: PaperPolicy) -> Catalog:
    names = frozenset(advertised)
    return Catalog(
        admitted=names & policy.admitted,
        missing=policy.admitted - names,
        unknown=names - KNOWN_TOOLS,
    )


#: What has been logged in this process, so the load-time check and the first model call that
#: sees Paper's tools report one gap once.
_LOGGED: set[tuple[str, frozenset[str]]] = set()


def log_catalog(catalog: Catalog) -> None:
    for kind, names in (("missing", catalog.missing), ("unknown", catalog.unknown)):
        if not names or (kind, names) in _LOGGED:
            continue
        _LOGGED.add((kind, names))
        listed = ", ".join(sorted(names))
        if kind == "missing":
            _LOGGER.warning(
                "[paper] the server does not advertise %s; only those tools are unavailable", listed
            )
        else:
            _LOGGER.info(
                "[paper] the server advertises %s, which the policy does not name; hidden", listed
            )


def bare_name(tool_name: str) -> str | None:
    """`write_html` for `paper_write_html`; None for any other server's tool or a host tool."""
    return (
        tool_name[len(PREFIX) :]
        if tool_name.startswith(PREFIX) and len(tool_name) > len(PREFIX)
        else None
    )


def admit_paper_tools(tools: Sequence[BaseTool], policy: PaperPolicy) -> list[BaseTool]:
    """Loaded tools with Paper's narrowed to the policy, and the catalog check logged.

    For loaders that hold the tool list (local and self-hosted); on MDA, where the platform adds
    connector tools at run time, `PaperScopeMiddleware` applies the same filter per model call.
    """
    names = [n for t in tools if (n := bare_name(t.name)) is not None]
    if names:
        log_catalog(check_catalog(names, policy))
    admitted = policy.admitted
    return [t for t in tools if (n := bare_name(t.name)) is None or n in admitted]


def paper_cli(
    home: Path | None = None, which: Callable[[str], str | None] = shutil.which
) -> str | None:
    """Paper Desktop's CLI: `~/.paper/bin/paper`, else `paper` on PATH."""
    installed = (home or Path.home()) / ".paper" / "bin" / "paper"
    if installed.is_file() and os.access(installed, os.X_OK):
        return str(installed)
    return which("paper")


def _is_local_endpoint(url: str) -> bool:
    parts = urlsplit(url)
    try:
        port = parts.port
    except ValueError:
        return False
    return (parts.scheme, parts.hostname, port, parts.path) == ("http", "127.0.0.1", 29979, "/mcp")


def paper_server(
    settings: Settings,
    *,
    runtime: RuntimeName,
    cli: Callable[[], str | None] | None = None,
) -> McpServer | None:
    """The MCP server for the configured mode on this runtime; None when Paper is off.

    Raises `PaperConfigError` naming what to change when the mode cannot be served here.
    """
    PaperPolicy.from_settings(settings)  # malformed or colliding file ids fail before a run
    url = settings.paper_mcp_url
    if settings.paper_mode == "off":
        return None
    if settings.paper_mode == "local":
        if runtime == "mda":
            raise PaperConfigError(
                "PAPER_MODE=local needs Paper Desktop on the machine the agent runs on; "
                "on Managed Deep Agents use PAPER_MODE=bridged"
            )
        if url is None or url == "stdio":
            command = (cli or paper_cli)()
            if command is None:
                raise PaperConfigError(
                    "Paper Desktop's `paper` CLI was not found in ~/.paper/bin or on PATH; open Paper "
                    f"Desktop once, or set PAPER_MCP_URL={LOCAL_HTTP}"
                )
            return McpServer(
                name=SERVER, url="", transport="stdio", command=(command, "mcp"), timeout=TIMEOUT_S
            )
        if not _is_local_endpoint(url):
            raise PaperConfigError(
                f"PAPER_MODE=local takes no PAPER_MCP_URL (stdio) or {LOCAL_HTTP}; "
                "a Paper on another machine is PAPER_MODE=bridged"
            )
        return McpServer(name=SERVER, url=url, transport="http", timeout=TIMEOUT_S)
    loopback = url is not None and url.startswith("http://127.0.0.1")
    if url is None or not (url.startswith("https://") or (loopback and runtime != "mda")):
        raise PaperConfigError(
            "PAPER_MODE=bridged needs PAPER_MCP_URL set to the bridge's https address (…/mcp)"
        )
    if runtime == "mda":
        return McpServer(
            name=SERVER, url=url, transport="http", connection=BRIDGE_CONNECTION, timeout=TIMEOUT_S
        )
    if settings.paper_bridge_token is None:
        raise PaperConfigError(
            "PAPER_MODE=bridged needs PAPER_BRIDGE_TOKEN, the bridge's bearer token"
        )
    return McpServer(
        name=SERVER,
        url=url,
        transport="http",
        bearer=settings.paper_bridge_token,
        timeout=TIMEOUT_S,
    )
