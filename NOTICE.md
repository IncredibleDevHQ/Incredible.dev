# Notices

Design Agent is Copyright 2026 LangChain, Inc., licensed under the Apache License 2.0
([LICENSE](LICENSE)).

## Incredible.dev

Incredible.dev is a modified version of Design Agent. Starting from upstream commit cb4dc17, it
removes Slack, the Paper integration and the Managed Deep Agents / LangSmith hosting path, and adds
a presenter hook, the web surface in `src/design_agent/surfaces/web/` and its app in `web/`. The
git history and the "in this fork" sections of [CHANGELOG.md](CHANGELOG.md) list the changes.

## Provenance

Design Agent is the open-source version of LangChain's internal design and motion agent
(internal codename "Content Studio"). Its harness, middleware and gates were ported from that
agent through an allowlist with names, identifiers and company content removed. Parts of the
Managed Deep Agents project layout descend from the `managed-deepagents-sdk` example application;
that code's MIT notice is preserved in [licenses/managed-deepagents-sdk-MIT.txt](licenses/managed-deepagents-sdk-MIT.txt).

## Third-party components

| Component | Where | License |
| --- | --- | --- |
| HyperFrames agent skills (HeyGen), vendored unmodified at release v0.9.64 | `skills/` entries listed in `skills-lock.json` | Apache-2.0, [licenses/hyperframes-LICENSE.txt](licenses/hyperframes-LICENSE.txt) |
| LangSmith agent skills (LangChain), vendored unmodified at commit 1fb52e836f2d | `skills/langsmith-trace`, `.agents/skills/langsmith-dataset`, `.agents/skills/langsmith-evaluator` | MIT, [licenses/langsmith-skills-LICENSE.txt](licenses/langsmith-skills-LICENSE.txt) |
| Deep Agents agent skills (LangChain), vendored unmodified at commit 16a992f09ab3 | `.agents/skills/deep-agents-*` | MIT, [licenses/langchain-skills-LICENSE.txt](licenses/langchain-skills-LICENSE.txt) |
| affectUI free items: Select (adapted to open on hover), Text Field, Text Area, Thinking Loader, Segmented Control, Tooltip, Popover, Kbd and Shimmer Loader (as they come), Progress Tracker (adapted to follow work as it happens), each in the house's colours | `web/src/components/Select.tsx`, `TextField.tsx`, `TextArea.tsx`, `ThinkingLoader.tsx`, `SegmentedControl.tsx`, `Tooltip.tsx`, `Popover.tsx`, `Kbd.tsx`, `Shimmer.tsx`, `ProgressTracker.tsx` | MIT, [licenses/affectui-MIT.txt](licenses/affectui-MIT.txt) |
| TipTap (core, React, ProseMirror bundle, suggestion), 3.32.2 | `web/package.json`, the chapter's script editor (`web/src/components/episode/Script.tsx`) | MIT |
| HyperFrames CLI | installed in the sandbox image, not redistributed here | Apache-2.0 |
| Geist, Fragment Mono, Inter, IBM Plex Mono, Fira Code, Fraunces | `fonts/` | SIL Open Font License 1.1, [fonts/licenses/](fonts/licenses/) |
| Apache ECharts | installed in the sandbox image | Apache-2.0 |
| sharp, puppeteer-core | installed in the sandbox image | Apache-2.0 |
| GSAP | installed in the sandbox image, never vendored | GSAP Standard "no charge" license |
| D2 | binary installed in the sandbox image | MPL-2.0 |
| Chrome Headless Shell | binary installed in the sandbox image | Chromium licenses |
| FFmpeg | Debian package in the sandbox image | LGPL/GPL per the Debian build |

Only affectUI's free (MIT) items are in this repository; none of its paid source is. The web
app's other parts, among them the change bar, the word marks, the drop place, the picture
tiles, the planning trail, the pictures pill, the script's blocks and lines, the slash menu, the
prompt at the caret, the frame drawn on a canvas and the chapter's timeline
(`web/src/components/episode/Ask.tsx`, `Diff.tsx`, `Tiles.tsx`, `Work.tsx`, `Script.tsx`,
`Slash.tsx`, `AskHere.tsx`, `FrameCanvas.tsx`, `Timeline.tsx`, `web/src/components/FileDrop.tsx`),
and the agent library (the trail of an agent's work, the note for its next turn and how a run
went, `web/src/components/agent/`), are written here from notes on how such components behave
and carry this project's license.

The sample brand in [examples/brands/example-studio/](examples/brands/example-studio/) is original
work released under CC0-1.0.
