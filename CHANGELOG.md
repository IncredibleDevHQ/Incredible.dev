# Changelog

## Unreleased

### Removed in this fork

- Slack: MDA's Slack channel, the self-hosted Slack adapter (`design-agent slack`, `test slack`),
  live progress cards, the reply footer, steering of the lead's own busy run from a Slack thread,
  and the `SLACK_*` and `DESIGN_AGENT_SLACK_*` settings. Steering of background helpers stays.
- Paper: the Paper MCP server and its scope policy, the bridge (`design-agent paper-bridge`,
  `test paper`), the `paper-design` skill and the `PAPER_*` settings.
- Managed Deep Agents and LangSmith hosting: the MDA project files, MDA's waker, memory and
  identity, LangSmith Sandboxes (`sandbox publish`, `sandbox use`, `DESIGN_AGENT_SANDBOX_SNAPSHOT`,
  `DESIGN_AGENT_SANDBOX_FS_GIB`), per-person MCP connections and trace-attachment delivery.
  LangSmith tracing stays.

### Added in this fork

- Episodes: a presenter-led explainer of one idea, taken from notes to a rendered film in a
  studio of its own (`surfaces/web/episode_desk.py`, `design_agent/episode/`, the `episode`
  skill). It starts from a channel's material or a research frame's notes.
  - The plan is written in stages (the brief, the script, a frame for every line) by a writer
    the person picks: Claude Code, Codex or Kimi Code on this computer, in a folder of the
    episode's own where it may change files and nothing else, or the built-in agent on the
    episode's thread. After each stage the words are read by a typed classifier (Jev with
    `TYPESAFE_API_KEY`; otherwise the writer's own model answers the same questions) and held
    to the checks by code, and the report opens the writer's next turn. The writer never types
    a label or a number.
  - An episode's length is asked for as a least and a most (4 to 10 minutes, at least 30
    seconds apart; the sheet opens on 5 to 7), and the script must land between the two. A
    plan that ends outside them says what was asked for beside its length. On Auto no length
    is asked for and none is checked: the material decides how long it runs.
  - The studio is the plan and the recording in one place: the film's page (its chapters, the
    look, the voice, the pictures' level) and, per chapter, the script, the frame for the
    picked line and that line's choices (who has the frame, the layout, a simple picture or a
    rich one posed as stills for the person's go). A pick is kept beside the plan and never
    undone by a later stage. A layout can be used for the chapter or the film, a picture can
    sit beside the person or fill the screen, and the line that brings a picture in can be
    given another type of picture and another transition (cut, push, crossfade, zoom), which
    the film renders by moving the picture's whole box. A new look redraws every picture, so
    the film's page says how many and waits for a yes; while pictures are being made it shows
    how far they are with a Stop, and the ones that stopped are made again on request.
  - The plan is read, and changed, before anything is drawn. A line's words are changed where
    they are read (nothing is read or drawn again; the writer only fits a step whose word is
    gone). Anything else is asked for in words in a change bar under the script, of the line,
    its picture, the chapter or the film; the writer makes it while the studio stays open, and
    a note on how a picture is drawn goes to its builder. While the writer works the bar shows
    what was asked and for how long, and takes the next change, which waits its turn. What a
    change did is marked in the script word by word, with the lines it cut; changes are taken
    back one at a time, newest first, a change taken back can be put back, and the picks made
    since stay. A change that stops can be asked again in the same words. One pick of a frame
    sets who has it and its layout, and the film's look is picked by a picture of the frame it
    is named for. One line can be recorded again. Before a take the microphone's level shows
    and the microphone and camera can be chosen (kept on that computer); during it the time
    planned for the chapter stands beside the time run, and the words to say can be made
    larger. Notes are dropped on the new-episode sheet as files, and a recording on a
    chapter's frame. Keys: R opens the camera, Cmd/Ctrl+Z takes the last change back and
    Shift+Cmd/Ctrl+Z puts it back. The studio's controls use more of affectUI's free parts
    (Segmented Control, Tooltip, Popover, Kbd, Shimmer Loader); the word marks, the drop
    place and the device choice are the studio's own.
  - Each picture is one HyperFrames sub-composition built by the same writer, in the channel's
    brand: its colours by role and its type, staged on the thread's computer. Every time in it
    comes from a clock block code rewrites, so a recording never sends a picture back to its
    builder. Each is held to the renderer's own check (lint, runtime, layout, contrast) and
    posed as a still at the end of every line, with a draft clip; a rich picture's builder
    looks at its stills once before the person does.
  - A chapter is recorded in the browser as one take (Space starts the next line), or brought as
    a file; where each line starts in the take sets how long it runs in the film and when its
    picture's cues land. The film is one HyperFrames page written by code and rendered on the
    thread's computer; before anything is recorded it renders as a draft with a stand-in.
  - A take is recorded as the camera and the microphone give it: no echo cancelling, one
    channel, H.264 where the browser can at about 16 Mbit/s for 1080p, and room noise cleaned
    up only for a microphone that sits in the computer. The recording panel names the
    microphone and the camera on a button each: the microphone's holds that switch, the
    camera's shows the picture it is giving. A recording brought as a file may be a
    camera's own, up to 8 GiB: it goes to disk and to the thread's computer as a file. The cut
    brings a high-dynamic-range picture down to the film's range and sets every take's sound
    to −16 LUFS by one gain.
  - With `DESIGN_AGENT_FOOTAGE_BUCKET`, every take's recording is also kept as it arrived in
    a bucket (`tools/footage.py`, the `s3` extra): S3 in production, MinIO or another
    S3-compatible store in development (`DESIGN_AGENT_S3_ENDPOINT`, `deploy/dev/compose.yaml`).
    The host sends it; a take stands when the bucket is down, and the thread says so.
  - With `ELEVENLABS_API_KEY`, the lines no take covers are narrated when a film's voice is
    the narrator: in a voice picked for the episode from the account's voices, in a clone of
    the person's own voice (made by ElevenLabs from the takes they kept or a recording they
    bring, after they say the voice is theirs to clone), or in the house's
    `DESIGN_AGENT_NARRATOR_VOICE_ID`.
- Every run of an agent is a row in the house's own store (`runs`): what it was told, each step
  and note on the way, what it said, and the session it ran under. A local agent's own session
  is a shortcut to that record: when one can no longer be resumed, research and episodes start
  the turn again, told what was said from the record.
- One presentation hook in place of the Slack slot: `surfaces/presenter.py`'s `Presenter`, set on
  `RuntimeProfile.presenter` (`build_local_runtime(presenter=...)`). With none, runs are headless.
- Summarization counts each image at what it costs, for the lead and every helper
  (`harness/context.py`'s `compaction`). LangChain's counter charges an image 85 tokens, so a
  thread of renders and contact sheets compacted late.

### Added

- Image generation goes through the LangSmith Gateway when there is no `OPENAI_API_KEY` and the
  deployment uses the gateway (a `langsmith:` model or `LANGSMITH_GATEWAY_API_KEY`); a gateway
  workspace with no OpenAI key says so.
- LangSmith's managed tool servers (Parallel web search) work locally and self-hosted with no header
  config: they are sent `LANGSMITH_API_KEY`. `config/mcp.example.toml` has the entry.
- README: example asks, and which skills are for coding agents.

- Every run's trace names the template it came from: a `template:langchain-ai/design-agent` tag
  and `ls_template` / `ls_template_version` metadata, on MDA's root run and through the shared
  trace middleware everywhere else, so a renamed fork still counts. Nothing about the deployment
  or its people; `DESIGN_AGENT_TEMPLATE_TELEMETRY=0` turns it off.
- Memory on Managed Deep Agents (`memory.py`): a team layer every caller shares and a personal
  layer for each person, mounted anywhere in Slack rather than only in their DM. The agent saves a
  rule the turn someone states it; a team rule beats a personal one and the brand pack beats both.
  Locally and self-hosted there are no memory layers.
- Integrations: `config/mcp.example.toml` has ready entries for the official MCP servers of
  Notion, Linear, GitHub, Figma, Atlassian, Asana, Canva, Webflow and Box, and a server's
  connection can belong to each person (`owner = "user"`), so MDA asks whoever has not connected
  to sign in with a link and the agent then acts as them. `docs/integrations.md` sets each up.

### Fixed

- Self-hosted and local: summarization no longer fails with `permission_denied` offloading history
  and images (#41). Deep Agents' artifacts go to `/workspace/.agent/`, which the agent can write.

### Changed

- A plain `mda deploy` deploys the project, and `mda dev` runs it: vendored skills' binary files
  (fonts) live in `skill-binaries/`, so `skills/` syncs to Context Hub as it is. The `deploy` and
  `dev` wrappers are gone; `doctor` checks what would make `mda deploy` fail or ship the wrong
  thing. The README leads with the MDA quickstart. Requires managed-deepagents 0.9.4.
- The sample brand sets everything in Geist (Light headlines with tight tracking) with Fragment Mono
  for labels, both OFL, in place of Fraunces, Inter and IBM Plex Mono. They are staged into each
  sandbox with the brand, so no sandbox rebuild or republish is needed.
- Paper exports reach the project again: Paper Desktop now writes an export to its Downloads folder
  and answers with paths, so the host (Local) or the bridge (Bridged, returning the bytes) reads
  back the files that export just wrote, saves them in the project's `renders/` and removes them
  from Downloads.
- The product spec moved to `docs/spec.md`.
- `langsmith:anthropic/*` and `langsmith:openai/*` models use the LangSmith Gateway's native
  routes, so prompt caching, context editing, tool search and effort work through the gateway.
- Tool history drops server tool calls nothing will answer and leaves the latest assistant turn
  as written when it repairs a thread.
- Brand packs can name colour roles per mode; web-format brand fonts load through `@font-face`;
  `fonts verify` checks each file's family; the render font gate accepts web fonts.
- `ask` prints the run's estimated cost; `demo` always uses the sample brand; evals keep the task set's
  brand.

### Added

- The deployed agent reads its own LangSmith traces: `list_traces` (by time, thread, trigger or
  failure, without housekeeping noise) and `read_trace` (a run tree written to the workspace, with
  errors and slowest steps). Read-only, scoped to the run's own project, off with
  `DESIGN_AGENT_ENABLE_TRACES=0`.
- LangChain's skills vendored unmodified from their public packs: `langsmith-trace` for the
  runtime, and Deep Agents, Managed Deep Agents, LangSmith trace, dataset and evaluator skills for
  coding agents. `skills-lock.json` now pins several upstreams; `skills sync-vendor --upstream`
  re-vendors one.
- Skills for coding agents to deploy, customize, evaluate, troubleshoot and update Design Agent,
  routed from `AGENTS.md`, with a test that every skill is routed and names only real commands; a
  map of every document (`docs/README.md`) and `llms.txt`.
- One shared Deep Agents assembly for Managed Deep Agents, the CLI and the self-hosted path, with
  an exact-id model capability registry (Claude Opus 5.5 by default, direct providers, optional
  LangSmith Gateway).
- The designer's computer: a pinned, checksum-verified sandbox recipe (Chrome Headless Shell,
  ffmpeg, HyperFrames 0.8.169, sharp, ECharts, D2, open fonts) shared by MDA's bake, the published
  snapshot, the local Docker runner and CI, with a build-time probe.
- A per-thread Docker sandbox runner (no network, dropped capabilities, unprivileged agent user,
  read-only staged brand and gates) and LangSmith Sandboxes from a published snapshot.
- Workspace staging with a generated manifest, sha256 checklist and brand-font verification.
- A validated brand-pack schema, token CSS generation and an original CC0 sample brand
  (Example Studio) with OFL fonts.
- Delivery through `upload_files` on every runtime with an exactly-once `DELIVERY.json` ledger.
- Host media tools (OpenAI images with a measured alpha report, ElevenLabs voice, effects and
  music, local or Groq transcription) and an SSRF-hardened `fetch_asset`; keys stay on the host.
- HyperFrames skills vendored unmodified at the v0.8.169 release commit with a per-file
  `skills-lock.json`; third-party assets without recorded licenses are left out.
- An offline demo through the real graph with a scripted model, and `doctor`.
- A 4-second HyperFrames teaser in the offline demo, gated by `video-gate` and `hyperframes check`
  and measured by `artifact-contract`; render smoke for HyperFrames (lint, check, snapshot, render)
  and D2.
- Media runtime skills: stills, image-ops, gif-edit, visual-verify, data-viz (ECharts and D2 on
  brand tokens), thumbnails, image-generation, sound (mixer, mastering to -14 LUFS, synthesized
  cues), storyboard and film-breakdown, with their scripts and tests.
- The orchestration harness behind public interfaces: background helpers with heartbeats and
  durable transcripts (`resume_task` after a restart), coalesced wake-ups and check-ins, render
  watchers with a HyperFrames progress parser, the launch-film pipeline with a step memo and an
  approval question, parallel looks with a person's pick merged and recorded, and the learning
  loop (with an optional cheaper review model).
- Managed Deep Agents wake-ups on one-time runtime schedules, a restart sentinel kept ahead while
  the process lives, quiet check-ins that post one status line, and a 15-minute housekeeping
  schedule that ends before any model call.
- Model-call guards in one order: image clamp, a failure boundary that ends a stalled turn with a
  line, a step budget that wraps up before the graph limit, typed retries, history repair, the
  usage meter; tool-error boundaries for `task`, `upload_files` and MCP calls.
- Context discipline: vendored skills listed by one-line summaries (system prompt ~4.3k tokens on
  the first call, measured by a test), the date written into history once per turn, per-role
  prompt-cache lifetimes, fan-out stagger, optional server-side tool-result clearing for helpers,
  and an optional soft job budget.
- MCP servers from `config/mcp.toml` on every runtime (`{server}_{tool}` names), loaded per server
  with isolation, disclosed through provider tool search or a bounded selector.
- `sandbox publish` builds the computer as a LangSmith snapshot and declares it.
- The self-hosted runtime: a FastAPI surface with per-caller thread ownership, attachments,
  background updates and downloads; Postgres (or SQLite) persistence; durable check-ins; startup
  sweep, idle sandbox reaping and housekeeping; a Docker Compose stack.
- `design-agent ask` keeps threads across invocations, takes `--file` attachments and stays open
  for background work; `config show|set|generate` manages `.env` without printing secrets.
- The eval set (19 design tasks and 7 behavior scenarios on the sample brand) with deterministic
  graders, a model-matrix runner and reports; opt-in live tests.
- Coding-agent skills for onboarding, brand onboarding, vendor sync and the release check; docs for
  models, MDA deployment, self-hosting, customization, operations, evals, HyperFrames and upstream
  asks.
- Slack presentation on both paths: live progress cards in one streamed message per turn (with a
  `chat.update` fallback), a footer with agents running, time and estimated cost, steering of
  running helpers (`steer_task`) and of the lead's busy turn, and generic trace tags.
- The self-hosted Slack app (`design-agent slack`, Bolt, Socket Mode or signed HTTP) with dedupe,
  host-side attachment fetch, uploads to the thread and an example manifest.
- Paper: Local (stdio or the desktop endpoint) and Bridged modes, a host-enforced policy shared with
  the bundled bearer-authenticated bridge (`design-agent paper-bridge`), exports saved to the
  project with a receipt in `run.json`, the `paper-design` skill and partner docs.
- A parity contract: MDA, local and self-hosted runtimes assemble the same agent.
- Taste and doctrine skills: content-brief, brand-design (with an artifact-contract example),
  design-wiki (public doctrine, platform specs, review rubric), motion-direction (directing, craft,
  techniques, sound, review, motion presets), launch-film (phases, orchestration, eight briefs, aligned
  with the pipeline) and reference-study; the router points at them.
- CLI: `brand init`, `fonts verify`, `sandbox use`, `test model|sandbox|paper|slack|db`, and
  a key preflight on `ask`.

