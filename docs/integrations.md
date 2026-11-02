# Integrations

The agent reaches other tools through MCP servers: Notion for a brief, Linear for the request
behind it, Figma for the frames, GitHub for the pull request a video explains. Each server's tools
are named `{server}_{tool}` and found through tool search, so a dozen servers do not crowd the
agent's context, and one that fails to load leaves the rest working. What a server returns is
treated as untrusted input, like any file someone attaches.

`config/mcp.example.toml` has ready entries for the services below. Copy it to `config/mcp.toml`
(Git-ignored) and uncomment the ones you want.

## On Managed Deep Agents

Every hosted server here signs in with OAuth through a workspace connection. Choose who it signs
in as with `owner`.

**Each person's own account** (`owner = "user"`, the preset's default). The agent acts as whoever
asked, so it sees only what they can see.

```bash
uv run mda connections create notion --mcp https://mcp.notion.com/mcp
uv run mda deploy
```

The first time a person's request needs Notion, MDA's credential gate stops the run before it
starts and posts a connect link. They sign in once, and the next request goes through. Runs started
with an API key have no person to sign in, so they end with sign-in guidance instead.

**One shared account** (`owner = "agent"`). Everyone's requests use the account that signs in when
the connection is created:

```bash
uv run mda connections create notion --mcp https://mcp.notion.com/mcp --authorize
```

Anyone who can mention the agent can then read what that account can, so give it a workspace or
teamspace made for the agent, and narrow its tools with `include_tools`.

`uv run mda connections list` shows what exists. The connection name in `mcp.toml` must match the
one you create.

## The presets

| Service | Server | Good for | Before you start |
| --- | --- | --- | --- |
| Notion | `https://mcp.notion.com/mcp` | Briefs, launch docs, content calendars | |
| Linear | `https://mcp.linear.app/mcp` | Design requests and specs in issues | |
| GitHub | `https://api.githubcopilot.com/mcp/` | Pull requests and release notes for explainers | |
| Figma | `https://mcp.figma.com/mcp` | Frames, components and variables | Figma admits only clients in its MCP catalog |
| Atlassian | `https://mcp.atlassian.com/v1/mcp` | Jira issues and Confluence pages | Cloud sites only |
| Asana | `https://mcp.asana.com/v2/mcp` | Tasks and projects | Needs a client registered in Asana's developer console |
| Canva | `https://mcp.canva.com/mcp` | Designs and brand assets | Access is limited; check it is open to you |
| Webflow | `https://mcp.webflow.com/mcp` | Sites, CMS collections and pages | |
| Box | `https://mcp.box.com` | Files a person can already open | A Box admin enables MCP first |

Each provider runs its own server and can change it; if one stops connecting, check its docs for
the current address.

## Locally and self-hosted

Per-person connections exist only on MDA, so `owner = "user"` servers are left out locally and
self-hosted, with a warning. For a shared account there, send a token from the host environment:

```toml
[servers.github]
url = "https://api.githubcopilot.com/mcp/"
headers_env = { Authorization = "GITHUB_MCP_AUTHORIZATION" }
```

with `GITHUB_MCP_AUTHORIZATION="Bearer <token>"` in `.env`. Header values never reach the sandbox.

## Web search

LangSmith runs a managed web search server (Parallel). Uncomment its entry at the top of
`config/mcp.example.toml`: on MDA it needs nothing more, and locally and self-hosted it is sent your
`LANGSMITH_API_KEY` as `x-api-key`, so there is no header to set.

## Your own server

Any HTTP or SSE MCP server works the same way; `config/mcp.example.toml` ends with a template. A
local app's stdio server (`transport = "stdio"`) runs locally and self-hosted only. Paper is set up
with `PAPER_*` instead ([Paper](partners/paper.md)).

`uv run design-agent doctor` lists the servers this checkout declares.
