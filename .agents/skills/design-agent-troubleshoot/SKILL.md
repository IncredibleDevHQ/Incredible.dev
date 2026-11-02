---
name: design-agent-troubleshoot
description: Diagnose Design Agent when something fails. Setup, a render, a deploy, Slack or a model call. Run doctor and the connection tests, read logs and traces, match the symptom to its fix, and never print credentials. Use when a command errors, a reply never comes, or a file looks wrong.
---

# Troubleshoot Design Agent

Report missing settings by name and never paste a key, token or `.env` line.

1. `uv run design-agent doctor` (add `--json` to parse it) checks every model role, keys, the brand,
   the sandbox, MDA declarations, MCP and Paper. Fix what it names first.
2. Real calls, a few cents each: `uv run design-agent test model`, `test sandbox`, `test paper`,
   `test slack`, `test db`.
3. Match the symptom:

| Symptom | Fix |
| --- | --- |
| `demo` needs a sandbox | start Docker, then `uv run design-agent sandbox build` |
| A render is missing a font | `uv run design-agent fonts verify`; `family` in `fonts.toml` must be the name inside the file |
| Off-brand colours or a failed brand check | `uv run design-agent brand validate`, then `brand css` |
| "The connection to the model stalled" or "stayed unavailable" | check the provider's status, then reply `continue` in the thread |
| Background news arrives a minute or two late on MDA | expected: MDA schedules land on the next minute |
| "A restart may have stopped…" | a deploy or restart stopped helpers; ask the agent to resume them |
| Paper "not connected" | Paper Desktop is closed or the bridge is down; boards still render in the sandbox |
| The sandbox bake runs out of disk on `mda deploy` | `uv run design-agent sandbox publish` first |
| "Context Hub only accepts UTF-8 text files" | move the skill's binary files to `skill-binaries/<skill>/` |
| "source archive … exceeds the 200 MB limit" | clear old renders in `workspace/out/` |
| An MCP server is missing | the startup log names the one that failed; the rest keep working |

4. **Logs:** `uv run mda logs` on MDA; `docker compose -f deploy/self-host/compose.yaml logs api`
   when self-hosted. Logs carry exception classes, never provider messages or keys.
5. **Traces:** every run is traced in LangSmith (an MDA deployment's project is
   `<deployment>-production`). Follow a bad file back to the skills read, tools called and checks
   run, with the [langsmith-trace](../langsmith-trace/SKILL.md) skill. API runs attach delivered
   files to the trace. The deployed agent can read its own traces too (`list_traces`,
   `read_trace`): ask it in the thread what went wrong.
6. **A real bug:** reproduce it with a failing test before changing code, then follow `AGENTS.md`.

More: [Operations](../../../OPERATIONS.md).
