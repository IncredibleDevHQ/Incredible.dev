# HyperFrames

[HyperFrames](https://hyperframes.heygen.com) (HeyGen, Apache-2.0) turns HTML into video: a
composition is a web page with timing in `data-*` attributes and motion on a paused GSAP timeline,
rendered frame by frame in Chrome Headless Shell and encoded with ffmpeg, so the same file renders
the same video every time. It is Design Agent's only video engine.

## How the agent uses it

| Step | Command |
| --- | --- |
| Gate before a render | `node /workspace/tools/video-gate.mjs index.html` (determinism), `hyperframes check` (lint plus runtime, layout, motion and contrast checks) |
| Look at a frame | `hyperframes snapshot --at <t>` |
| Render | `hyperframes render <dir> --quality draft\|looks\|delivery --fps 30 --output <file>`; long renders run detached with a watcher that wakes the agent on exit, failure or stall |
| Measure | `node /workspace/tools/artifact-contract.mjs --expect file.mp4:WxH@seconds` |
| Media helpers | `hyperframes transcribe`, `remove-background`, registry blocks (`hyperframes add`) |

The sandbox is offline: compositions load GSAP from the image
(`/opt/design-agent/render/node_modules/gsap/dist/gsap.min.js`) and brand files from the workspace,
copied next to the composition. Voice, music and sound effects come from host tools, so no key
ever enters the sandbox.

## Pinning

- The CLI is pinned in `sandbox/render/package.json` (0.8.169) and installed from a lockfile embedded
  in `sandbox/setup.sh`; Chrome Headless Shell and the other binaries are pinned by checksum.
- Upstream agent skills are vendored unmodified at the matching release commit into `skills/`, with
  a per-file `sha256` in `skills-lock.json` that CI verifies. Upstream assets without a recorded
  license (sound effects, caption fonts, bundled GSAP) are left out. Our guidance sits in sibling
  skills (`motion-direction`, `storyboard`, `launch-film`); the resident skill list shows each
  vendored skill as a one-line summary from `config/vendored-skills.toml`.
- Upgrades follow the [vendor-sync skill](../../.agents/skills/vendor-sync/SKILL.md).

## Telemetry

The sandbox wrapper sets `HYPERFRAMES_NO_TELEMETRY=1`, `DO_NOT_TRACK=1`,
`HYPERFRAMES_NO_UPDATE_CHECK=1` and `HYPERFRAMES_NO_AUTO_INSTALL=1`, and the sandbox image sets the
first two for every process: the vendored `media-use` scripts report usage to PostHog (with a
public ingestion key in their source) unless opted out. The sandbox has no egress by default, so
nothing would leave it either way.

## Open questions for HeyGen

1. The license covering the skills folder (the package and repository are Apache-2.0).
2. Versioned skill releases or a recommended commit pin, and whether `hyperframes skills check` is
   the supported drift check.
3. A supported way to override routing or providers (host-side TTS) without forking skill files.
4. Where bundled sound effects and the matting model live, and their licenses.
5. Machine-readable render progress for watchers (the CLI prints `@hf-progress` JSON lines in
   non-interactive logs today; is that a stable contract?).
6. Whether a pinned CLI or `--docker` is the recommended reproducibility path.
7. Registry pinning: a tag instead of `main`.
8. An open-source key or free tier for HeyGen TTS and audio, and the status of cloud render targets.
9. GSAP guidance for open-source users (we load it from the pinned npm package, never a CDN).
10. Co-marketing: an ADOPTERS listing, a joint example, a launch quote.
