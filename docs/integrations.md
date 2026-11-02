# Integrations

The agent reaches other tools through MCP servers: GitHub for the pull request a video explains, a
docs search of your own for the brief behind it. Each server's tools are named `{server}_{tool}`
and found through tool search, so a dozen servers do not crowd the agent's context, and one that
fails to load leaves the rest working. What a server returns is treated as untrusted input, like
any file someone attaches.

`config/mcp.example.toml` has ready entries. Copy it to `config/mcp.toml` (Git-ignored) and
uncomment the ones you want.

## Credentials

A server signs in with a token from the host environment. `headers_env` maps each header to the
environment variable that holds its value:

```toml
[servers.github]
url = "https://api.githubcopilot.com/mcp/"
headers_env = { Authorization = "GITHUB_MCP_AUTHORIZATION" }
```

with `GITHUB_MCP_AUTHORIZATION="Bearer <token>"` in `.env`. A server whose header is unset is left
out with a warning. Header values never reach the sandbox. Everyone's requests use the account the
token belongs to, so give it access made for the agent, and narrow its tools with
`include_tools`.

Each provider runs its own server and can change it; if one stops connecting, check its docs for
the current address.

## Web search

LangSmith runs a managed web search server (Parallel). Uncomment its entry at the top of
`config/mcp.example.toml`: it is sent your `LANGSMITH_API_KEY` as `x-api-key`, so there is no
header to set.

## Your own server

Any HTTP or SSE MCP server works the same way; `config/mcp.example.toml` ends with a template. A
local app's own server can run over stdio (`transport = "stdio"` with a `command`); it gets only a
short list of safe environment variables, never the host's keys.

`uv run design-agent doctor` lists the servers this checkout declares.
