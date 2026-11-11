# Documentation

Every guide, by what you're trying to do. Working in Claude Code, Codex or Cursor? Each job also has
a step-by-step skill in [.agents/skills/](../.agents/skills/), and [AGENTS.md](../AGENTS.md) says
which one fits.

## Set it up and make it yours

| Guide | Covers |
| --- | --- |
| [README](../README.md#get-started) | the five-minute demo and your first request |
| [CLI](cli.md) | every `design-agent` command |
| [Models](models.md) | providers, the LangSmith Gateway, roles, effort, cost |
| [Customization](customization.md) | brand packs, instructions, runtime skills, learning, MCP servers |
| [Integrations](integrations.md) | GitHub and your own MCP servers, with credentials from the host |
| [HyperFrames](partners/hyperframes.md) | the video engine and its vendored skills |

## Run it for your team

| Guide | Covers |
| --- | --- |
| [Self-hosting](self-hosting.md) | Docker Compose, the HTTP API, security |
| [Supabase](supabase.md) | Google/email login, PostgreSQL and private user workspaces |
| [MinIO](minio.md) | Private S3 blobs, migration, credentials and storage backups |
| [Local Compose](local-compose.md) | Browser app, Supabase, persistent workspace and local Docker setup |
| [Operations](../OPERATIONS.md) | configuration, the sandbox, costs, troubleshooting, upgrades, backups |

## Know it's working

| Guide | Covers |
| --- | --- |
| [Evals](evals.md) | the design set, behaviors, graders, reports |

## How it's built

| Guide | Covers |
| --- | --- |
| [Product spec](spec.md) | what it's for, how it should behave, and the acceptance criteria |
| [Architecture](architecture/README.md) | the assembly, the lead and helpers, context, the sandbox, checks, keys |
| [Orchestration](architecture/orchestration.md) | background helpers, wake-ups, restarts, pipelines |
| [Context and failures](architecture/context-and-failures.md) | what the model sees, caching, cost, failure boundaries |
| [Surfaces](architecture/surfaces.md) | the presenter hook, the API, the CLI |
| [Upstream](upstream.md) | seams we work around and what we've asked for |
| [Official links](sources/official-links.md) | primary documentation for every external contract |

## Contribute

[Contributing](../CONTRIBUTING.md) · [Agent instructions](../AGENTS.md) · [Security](../SECURITY.md) ·
[Changelog](../CHANGELOG.md)
