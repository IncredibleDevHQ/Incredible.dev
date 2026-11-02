# Incredible.dev

Developer content made from the material you already have. Bring a repository, docs, a blog post,
a talk or your notes, and a team of AI agents researches it, storyboards it and makes the film, the
thumbnails, the cards and the posts, in channels you can steer and on a canvas you can review.

> **A new beginning.** This is the new Incredible.dev, rebuilt on an open-source agent engine. The
> earlier video creator lives on the
> [`archive/dev-video-creator`](https://github.com/IncredibleDevHQ/Incredible.dev/tree/archive/dev-video-creator)
> branch.

## What it does

- **Channels and threads.** A message in a channel becomes a task: a lead agent with its own
  helpers and its own computer. Replies steer the work while it runs, and Stop ends it at its next
  step.
- **A canvas of assets.** Each task is a flow on the channel's canvas: what it started from, then
  each piece of work (a storyboard, a film, thumbnails, social cards, a deck, a chart), linked to
  what it was made from. People approve a board, pin notes to a frame or ask for changes, and the
  agent answers with a new version.
- **Templates.** Launch kit, Explainer, Post to social, Ad set, Pitch pack, Social pack and Talk to
  clips each place a set of linked assets for a common job.
- **Research from your code.** A research frame asks local coding agents (Claude Code, Codex, Kimi
  Code) about your repositories. Their answers become notes that record where each came from, and
  notes feed new assets.
- **Brands.** Read a brand from a website, or keep a brand pack, and choose which one each channel
  uses.
- **Films in code.** Video is built with [HyperFrames](https://hyperframes.heygen.com): a film is a
  web page on a timeline, so a change is an edit and a re-render.

## Run it locally

You need Docker, [uv](https://docs.astral.sh/uv/) and Node.js.

```bash
uv sync --all-extras --dev
uv run design-agent sandbox build                    # the agents' computer
(cd web && npm install && npm run build)             # the app
uv run python -m design_agent.surfaces.web --demo    # a scripted lead, no API keys
uv run python -m design_agent.surfaces.web           # a real model (a provider key in .env)
```

Then open http://127.0.0.1:8765. For app development, run `npm run dev` in `web/` (port 5178); it
passes `/api` through to the server. [Models](docs/models.md) lists the providers and their keys.

The app has no sign-in yet. It serves 127.0.0.1 only and takes the person from a request header,
so don't expose it on a network.

## How it's built

- **The engine** is [Design Agent](https://github.com/langchain-ai/design-agent), LangChain's
  open-source design agent built on [Deep Agents](https://github.com/langchain-ai/deepagents)
  (Apache 2.0): the lead and its helpers, a Docker sandbox per thread, skills, checks and the cost
  meter. We removed its Slack, Paper and hosted-deploy parts.
- **The surface** is ours: the server in `src/design_agent/surfaces/web/` (API, live events, store,
  canvas tools, research, brands) and the app in `web/` (React, Vite, TypeScript). It plugs in
  through one presenter hook, `src/design_agent/surfaces/presenter.py`.

More: [architecture](docs/architecture/README.md) · [instructions.md](instructions.md) ·
[skills/](skills/) · [customization](docs/customization.md) · [changelog](CHANGELOG.md).

## License

[Apache 2.0](LICENSE). [NOTICE.md](NOTICE.md) credits Design Agent and the components it vendors.
