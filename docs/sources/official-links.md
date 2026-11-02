# Official engineering sources

Check the relevant primary source before changing an external contract. These APIs move weekly;
installed package behavior and a live probe outrank model memory and this list. Update the owning
architecture page when supported behavior changes.

## Deep Agents and Managed Deep Agents

- Deep Agents (OSS): <https://github.com/langchain-ai/deepagents> · docs
  <https://docs.langchain.com/oss/python/deepagents/overview>
- Deep Agents customization, subagents, skills, backends, human-in-the-loop:
  <https://docs.langchain.com/oss/python/deepagents/customization>,
  <https://docs.langchain.com/oss/python/deepagents/human-in-the-loop>
All MDA pages share the prefix `https://docs.langchain.com/langsmith/python/managed-deep-agents-`:

| Topic | Page suffixes |
| --- | --- |
| Start | `overview`, `quickstart`, `project-structure`, `migrate` |
| Agent definition | `agent-definition`, `instructions`, `skills`, `tools`, `middleware`, `runtime` |
| Integrations | `search`, `connections`, `mcp-connectors`, `mcp-endpoint` |
| State and environment | `memory`, `sandboxes`, `context-hub` |
| Identity and schedules | `identity`, `schedules` |
| Channels | `channels`, `channels-slack`, `channels-http`, `agent-owned-interrupts` |
| Develop and ship | `local-development`, `tutorial`, `deploy`, `cli`, `evals` |

- Public landing repository and changelog: <https://github.com/langchain-ai/managed-deepagents>
- Coding-agent skills for Deep Agents and MDA projects, vendored into `.agents/skills/` at the
  commit in `skills-lock.json`: <https://github.com/langchain-ai/langchain-skills>
- LangSmith skills (tracing, datasets, evaluators), vendored the same way:
  <https://github.com/langchain-ai/langsmith-skills> · trace queries use the Python SDK's
  `Client.list_runs` (<https://docs.smith.langchain.com/reference/python/client>)
- LangSmith sandboxes: <https://docs.langchain.com/langsmith/sandboxes> · regions:
  <https://docs.langchain.com/langsmith/regions-faq> · pricing: <https://www.langchain.com/pricing>
- PyPI: <https://pypi.org/project/managed-deepagents/> (0.9.4 stable on 2026-10-20; `0.10.0.devN`
  builds are cut from feature branches, never pin them) · <https://pypi.org/project/deepagents/>
  (0.7.28)
- SDK source is private to LangChain staff (`langchain-ai/managed-deepagents-sdk`; its
  examples directory holds the MIT-licensed lineage of the internal agent). Builders with access
  may read it for current behavior, but the public repository depends only on the published package
  and public docs.

Known doc drift as of 2026-10-17 (trust the installed package): the SDK README still shows
`scope: "agent"` sandboxes (rejected at runtime); the migrate page shows `define_memory(scope="agent")`
(raises in 0.9.3; use `define_memory(agent=MemoryLayer())`); the PyPI README says Python 3.9+ (3.11+
is required). Declaring a sandbox clears `permissions`; schedules require `identity.py`.

Verified against the installed 0.9.3 package while building (its README ships in
`managed_deepagents-0.9.3.dist-info/METADATA`): `mda build` reads declarations statically, so
`sandbox/__init__.py` and `schedules/*.py` hold literals or top-level constants; a static agent
declares MCP servers in `tools/mcp.py` as a module-level `mcp` (passing `mcp=` to
`define_deep_agent` is refused); connector tools are named `{server}_{tool}`; schedule delivery is
an `after_agent` hook installed ahead of authored middleware.

Confirm each URL still resolves when you move a pin forward; the docs site renames pages.

## HyperFrames (HeyGen) — video engine

- Site: <https://hyperframes.heygen.com> · Quickstart: <https://hyperframes.heygen.com/quickstart>
- Catalog: <https://hyperframes.heygen.com/catalog>
- Repository (Apache-2.0): <https://github.com/heygen-com/hyperframes> · releases
  <https://github.com/heygen-com/hyperframes/releases> · adopters list `ADOPTERS.md`
- Agent skills: `npx skills add heygen-com/hyperframes` (standalone) or the HyperFrames plugin;
  update with `npx hyperframes skills update`.
- CLI at the pinned 0.8.169 (verified with `--help` in the sandbox): `hyperframes init | lint |
  check | snapshot | preview | render --quality draft|looks|delivery --output <file>`; `validate`,
  `inspect` and `layout` are deprecated aliases of `check`.
- Studio (desktop preview app): <https://hyperframes.dev/studio/download>

## Paper — shared design canvas

- MCP docs: <https://paper.design/docs/mcp>
- Downloads (Paper Desktop): <https://paper.design/downloads>
- Agent plugins: `claude plugin marketplace add paper-design/agent-plugins && claude plugin install
  paper-desktop@paper`; Codex: `codex mcp add paper -- /path/to/paper mcp`.
- Transport: Paper Desktop starts the MCP server and installs the `paper` CLI. The recommended
  transport is the stdio server `paper mcp`; the legacy HTTP endpoint
  `http://127.0.0.1:29979/mcp` is served only while a file is open. No hosted or token-based remote
  MCP is documented as of this writing; free plans have MCP limits that reset on Pro.

## Models and tool disclosure

- LangChain prebuilt middleware (tool search, LLM tool selector, summarization, context editing):
  <https://docs.langchain.com/oss/python/langchain/middleware/built-in>
- Anthropic tool search: <https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool>
- Anthropic context editing and compaction: <https://platform.claude.com/docs/en/build-with-claude/context-editing>
- Anthropic vision (image token cost): <https://platform.claude.com/docs/en/build-with-claude/vision>
- OpenAI tool search: <https://developers.openai.com/api/docs/guides/tools-tool-search>
- OpenAI image generation: <https://developers.openai.com/api/docs/guides/image-generation>

## Media services (optional)

- ElevenLabs text to speech and music: <https://elevenlabs.io/docs>
- FFmpeg: <https://ffmpeg.org/documentation.html>
- Chrome Headless Shell: <https://developer.chrome.com/blog/chrome-headless-shell>
- sharp: <https://sharp.pixelplumbing.com>
- Apache ECharts: <https://echarts.apache.org> · D2: <https://d2lang.com>

## Slack

- Slack agents and AI apps (streaming, status): <https://docs.slack.dev/ai/>
- Bolt for Python: <https://docs.slack.dev/tools/bolt-python/>
- Socket Mode: <https://docs.slack.dev/apis/events-api/using-socket-mode>

## Skills format

- Agent Skills specification: <https://agentskills.io/specification>
