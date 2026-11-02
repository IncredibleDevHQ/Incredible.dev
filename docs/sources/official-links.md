# Official engineering sources

Check the relevant primary source before changing an external contract. These APIs move weekly;
installed package behavior and a live probe outrank model memory and this list. Update the owning
architecture page when supported behavior changes.

## Deep Agents and LangSmith

- Deep Agents (OSS): <https://github.com/langchain-ai/deepagents> · docs
  <https://docs.langchain.com/oss/python/deepagents/overview>
- Deep Agents customization, subagents, skills, backends, human-in-the-loop:
  <https://docs.langchain.com/oss/python/deepagents/customization>,
  <https://docs.langchain.com/oss/python/deepagents/human-in-the-loop>
- Coding-agent skills for Deep Agents projects, vendored into `.agents/skills/` at the
  commit in `skills-lock.json`: <https://github.com/langchain-ai/langchain-skills>
- LangSmith skills (tracing, datasets, evaluators), vendored the same way:
  <https://github.com/langchain-ai/langsmith-skills> · trace queries use the Python SDK's
  `Client.list_runs` (<https://docs.smith.langchain.com/reference/python/client>)
- PyPI: <https://pypi.org/project/deepagents/> (0.7.28)

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

## Skills format

- Agent Skills specification: <https://agentskills.io/specification>
