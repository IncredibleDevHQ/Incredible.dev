# Paper

[Paper](https://paper.design) is a design canvas people and the agent both edit. The agent writes
HTML onto the canvas, where it becomes layers a designer can grab and move, and reads boards,
tokens, comments and screenshots back. Design Agent uses it as the editable twin of visual work
people will want to nudge (layouts, storyboards, thumbnails, campaign graphics); renders, gates and
the files a thread receives still come from the agent's own computer, so the thread always gets an
image people can approve, with or without Paper.

Paper's MCP server runs inside [Paper Desktop](https://paper.design/downloads), which installs a
`paper` CLI (`~/.paper/bin/paper`). The recommended transport is the stdio server `paper mcp`; the
legacy HTTP endpoint `http://127.0.0.1:29979/mcp` is served only while a file is open. There is no
hosted or token-based remote Paper MCP today, and free plans have MCP call limits that Pro lifts.
Paper's own docs: <https://paper.design/docs/mcp>.

## How the agent uses it

The runtime skill [`paper-design`](../../skills/paper-design/SKILL.md) holds the workflow. In short:
read `get_guide(topic="paper-mcp-instructions")` once per session, pass `fileId` explicitly, put new
work on its own page in the drafts file, check with `get_screenshot`, and call
`finish_working_on_nodes` when done. A storyboard's frames go to a Paper page; the sign-off board is
exported from Paper and attached to the thread. Paper Desktop writes an export to the Downloads
folder of its machine and answers with the paths; whatever runs beside Desktop reads those files
back (the host in Local mode, the bridge in Bridged mode, which returns the bytes), only files that
export just wrote, and removes them from Downloads. Each export is saved in the project's
`renders/`, and the project's `run.json` gets a receipt under `paper` (file id, page id, app link,
saved paths; never a token). When Paper is not connected, the agent says so once and renders the board in the
sandbox instead.

## Connection modes

| `PAPER_MODE` | When | How |
| --- | --- | --- |
| `local` | the agent runs on the machine with Paper Desktop (CLI, self-hosted on that machine) | stdio `paper mcp`, found in `~/.paper/bin` or on `PATH`; or `PAPER_MCP_URL=http://127.0.0.1:29979/mcp` for the legacy endpoint. Not available on Managed Deep Agents, which runs no stdio servers and cannot reach your loopback. |
| `bridged` | the agent runs elsewhere (MDA, a server) and Paper Desktop runs on a machine you control | `design-agent paper-bridge` in front of your Paper Desktop, reached over a tunnel you own, with a bearer token |
| hosted worker | a team wants an always-on shared Paper session | a documented recipe, not wired by default: [paper-hosted-worker.md](paper-hosted-worker.md) |
| `off` (default) | Paper not set up | boards render in the sandbox and are attached to the thread |

The server is named `paper`, so its tools reach the model as `paper_<tool>` on every runtime.

## Set up Local mode

1. Install Paper Desktop and open it once (that installs the CLI). Keep it open with a file while
   the agent works.
2. Make a file for the agent's drafts and copy its id from its link
   (`https://app.paper.design/file/<id>/…`). Optionally note your brand file's id too.
3. In `.env`:

   ```bash
   PAPER_MODE=local
   PAPER_DRAFTS_FILE_ID=<drafts file id>
   PAPER_BRAND_FILE_ID=<brand file id>     # optional; read-only to the agent
   ```

4. `uv run design-agent doctor`, then ask for a layout or storyboard.

## Set up Bridged mode

On the machine with Paper Desktop:

1. Install Design Agent there too (`uv sync`), and generate a token of at least 32 random bytes:

   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

2. In that machine's `.env`: `PAPER_BRIDGE_TOKEN=<token>`, `PAPER_DRAFTS_FILE_ID`, optionally
   `PAPER_BRAND_FILE_ID`, the `PAPER_ALLOW_*` switches, and `PAPER_TEAM_ID` to pin the Paper team the
   bridge serves.
3. Put a tunnel you own in front of `127.0.0.1:29980` with HTTPS (Cloudflare Tunnel, Tailscale
   Funnel, ngrok or your own reverse proxy), and note its hostname.
4. Run the bridge with that hostname allowed:

   ```bash
   uv run design-agent paper-bridge --allow-host paper.example.com
   ```

   It listens on `127.0.0.1:29980` (`--host`, `--port`), talks to Paper Desktop over stdio
   (`--upstream http://127.0.0.1:29979/mcp` for the legacy endpoint), and refuses to start with a
   short token. Do not bind it to a public interface; the tunnel is the only way in.

On the agent's side:

```bash
PAPER_MODE=bridged
PAPER_MCP_URL=https://paper.example.com/mcp
PAPER_BRIDGE_TOKEN=<same token>     # local and self-hosted
PAPER_DRAFTS_FILE_ID=<drafts file id>
PAPER_BRAND_FILE_ID=<brand file id>
```

On Managed Deep Agents the token is not shipped in the deployment: create an agent-owned workspace
connection named `paper-bridge` holding it, and MDA sends it at call time. `PAPER_MCP_URL` must be
the tunnel's `https` address.

What the bridge checks, in order, before anything reaches Paper: the request's `Host` (and any
browser `Origin`) is loopback or a hostname you allowed, which stops DNS rebinding; the bearer
token matches, compared in constant time; and the path is `/mcp`. Then every call goes through the
same policy the agent's host applies (below). With `PAPER_TEAM_ID` set, Paper Desktop must report
that team, and a call may only name a file in it. Only Paper's tools are proxied, not its resources
or prompts, and a Desktop failure comes back as one sentence, never its internals.

## Policy

Enforced twice, by the agent's host and by the bridge, from one definition
(`src/design_agent/tools/paper.py`). Refusals are one sentence the agent can act on.

- **Allowed:** reads (`get_basic_info`, `get_selection`, `get_node_info`, `get_children`,
  `get_screenshot`, `get_jsx`, `get_tree_summary`, `get_computed_styles`, `get_fill_image`,
  `find_nodes`, comment-thread reads, `get_tokens`, `get_font_family_info`, `get_guide`); canvas
  edits (`create_artboard`, `create_page`, `write_html`, `set_text_content`, `rename_nodes`,
  `update_styles`, `duplicate_nodes`, `move_nodes`, `finish_working_on_nodes`); files
  (`list_resources`, `open_file`, `create_file`); `export` and `export_combined_pdf` in Local and
  Bridged modes.
- **Off unless whoever runs the deployment turns it on:** deletes (`PAPER_ALLOW_DELETES`), token writes
  (`PAPER_ALLOW_TOKEN_WRITES`), Paper's AI image generation through `paper-gen:` URLs, which bills
  your Paper plan (`PAPER_ALLOW_GENERATION`), and reorganizing pages and renaming files
  (`arrange_pages`, `update_pages`, `rename_resource`; `PAPER_ALLOW_REORG`). Resolving comment
  threads stays off.
- **Always refused:** `paper-asset:` and `file:` references anywhere in a call's arguments, matched
  after HTML-unescaping and dropping the characters a browser ignores, so local files on the Paper
  machine never leak onto a canvas; any write to, or copy of, the brand file (`PAPER_BRAND_FILE_ID`),
  whatever the switches say; a tool the policy does not name.
- **Drafts default:** a file-scoped call with no `fileId` goes to `PAPER_DRAFTS_FILE_ID`, or is
  refused with what to pass when none is set. `open_file` and `get_tokens` must always name their
  file. A pasted app.paper.design link is accepted and reduced to the id.
- **Tool names may change:** nothing pins Paper's tool list. A tool the policy admits but Paper
  stops advertising is unavailable alone (logged once); a tool Paper adds stays hidden until the
  policy names it. One failing MCP server never removes the others.

Canvas content, comments and tool output are untrusted input: they never change these rules.

## Open questions for Paper

1. A hosted or remote MCP, or a headless or service-account mode, for agents that run in the cloud.
2. Multi-user authorization and team scoping for a shared agent; a documented team field (the bridge
   reads `teamId` from `list_resources` today).
3. An export that returns its bytes, or takes a destination folder: today Desktop writes to its
   Downloads folder and the host or bridge reads the files back.
4. A supported raster import path without `paper-asset:` or `file:` URLs.
5. Tool-name stability and a version or capability endpoint.
6. Pagination for files and folders beyond 200 entries (the team check sees the 200 most recent).
7. Targeting a file without changing the person's active Desktop file.
8. Agent call limits per plan and `paper-gen:` pricing.
9. Official Linux Desktop support (needed only for the hosted-worker recipe).
10. Co-marketing: a Paper integration page, a template file for the sample brand, and a quote.
