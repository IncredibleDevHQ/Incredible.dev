# Operations

Running Design Agent day to day: configuration, the sandbox, deployments, costs and what to do when
something breaks.

| Topic | Guide |
| --- | --- |
| Models, roles and the capability registry | [docs/models.md](docs/models.md) |
| Deploy with Managed Deep Agents | [docs/deploy-mda.md](docs/deploy-mda.md) |
| Self-hosting with Docker Compose | [docs/self-hosting.md](docs/self-hosting.md) |
| Brand packs, skills, learning, MCP | [docs/customization.md](docs/customization.md) |
| Paper modes and the bridge | [docs/partners/paper.md](docs/partners/paper.md) |
| Evals and the gallery | [docs/evals.md](docs/evals.md) |
| Every CLI command | [docs/cli.md](docs/cli.md) |
| How it works | [docs/architecture/](docs/architecture/README.md) |

## Configuration

Settings live in `.env` (Git-ignored); `.env.example` documents every one.
`uv run design-agent config show` prints them with secrets masked, `config set KEY=value` changes
them, `config generate` fills random tokens and passwords. `uv run design-agent doctor` checks the
model for every role, the brand pack, the sandbox and the MDA declarations without printing secrets.

Every run's trace names the template it came from (`ls_template: langchain-ai/design-agent` and its
version) so LangChain can count deployments of this repository; nothing about you or your people
goes with it. `DESIGN_AGENT_TEMPLATE_TELEMETRY=0` turns it off.

## The sandbox computer

One recipe (`sandbox/setup.sh`) builds every sandbox: the local Docker image
(`design-agent sandbox build`), the LangSmith snapshot (`sandbox publish`), MDA's bake, and CI. It
pins Chrome Headless Shell, ffmpeg, HyperFrames, D2, the Node render toolchain and open fonts by
version and checksum, and ends with a probe (`sandbox test`) that renders a page, a 2-second film
and a diagram. Change the recipe, rebuild, re-run `sandbox test` and `make render`, then publish
again for MDA.

Per thread: one container (self-hosted, local) or one LangSmith sandbox (MDA), with the thread's
files in `/workspace/projects/` kept between turns. Idle containers stop after
`DESIGN_AGENT_SANDBOX_IDLE_TTL_SECONDS` and restart on the next command; their volumes stay.

## Costs

Every model call is priced from `config/prices.toml` (list prices with the date checked and the
source) and summed per job, helper and role. Figures are estimates; your provider's invoice is the
truth. Set `DESIGN_AGENT_JOB_BUDGET_USD` to make the agent ask before going past a budget, and
`DESIGN_AGENT_HELPER_EFFORT_CAP` to cap helpers' effort.

## Troubleshooting

| Symptom | Likely cause and fix |
| --- | --- |
| `demo` says it needs a sandbox | Docker is not running or the image is missing: `uv run design-agent sandbox build` |
| A render fails with a missing font | the file is not in `fonts/` or `private-fonts/`, or `fonts.toml` names a family the file does not carry: `fonts verify` |
| "The connection to the model stalled" | a call passed `DESIGN_AGENT_MODEL_TIMEOUT_SECONDS`; reply `continue` |
| "The model stayed unavailable" | the provider failed through every retry; check the provider's status, reply `continue` |
| Background news arrives a minute or two late on MDA | expected: MDA schedules land on the next minute |
| "A restart may have stopped…" | a deploy or restart stopped helpers; ask the agent to resume them |
| Paper "not connected" | Paper Desktop is closed or the bridge is unreachable; boards still render in the sandbox |
| The sandbox bake runs out of disk on `mda deploy` | publish the snapshot first: `uv run design-agent sandbox publish` |
| An MCP server is missing | it failed to load; the startup log names it and the rest keep working |

Logs: `uv run mda logs` for MDA; `docker compose -f deploy/self-host/compose.yaml logs api` for
self-hosted. Logs carry exception classes, never provider messages or keys.

## Upgrading

- Python dependencies: `uv lock --upgrade`, then the checks in [CONTRIBUTING.md](CONTRIBUTING.md).
- HyperFrames and its skills: the [vendor-sync skill](.agents/skills/vendor-sync/SKILL.md).
- Managed Deep Agents: read the release notes for API changes (for example the 0.10 Slack
  `trigger_mode`), then `uv run mda build` and a test deployment
  (`uv run mda deploy --name design-agent-test`).

## Backups

Self-hosted state is in Postgres (`postgres` volume) and delivered files in the `out` volume; back
both up with your usual tools. MDA state is managed by LangSmith.
