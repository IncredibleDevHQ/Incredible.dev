# Workspace tools: gates and renderers

Deterministic Node tools the agent runs inside the sandbox. The model owns creative judgment; these
own rendering, measurement and every number a report states. They are staged to `/workspace/tools/`
and run with `node /workspace/tools/<tool>.mjs`.

## Exit codes (every tool)

| Code | Meaning |
| --- | --- |
| `0` | Pass. Warnings may be printed; they never fail a gate. |
| `1` | Findings: at least one ERROR in the artifact or input. Fix and run again. |
| `2` | The check could not run: bad arguments, a missing or unreadable file, a missing binary or package, a page that would not load, a crash. **Never a pass.** Report it as a tooling failure, not as a clean result. |

A gate that could not look is not a gate that found nothing. Callers treat any code other than `0`
as "not passed".

## Paths, brand pack and toolchain

- Relative paths resolve against the workspace: the folder that holds `tools/` (`/workspace` in the
  sandbox). Gates that read inputs (`brand-lint`, `video-gate`, `artifact-contract`, `audio-lint`,
  `film-probe`, `film-analysis`, `video-score`, `review-thumb`, `fetch-asset`) refuse paths outside
  it; `--root <dir>` points them at another workspace (tests use this).
- Brand facts come only from the active pack: `--tokens` defaults to `<root>/brand/tokens.json`
  (validated by `src/design_agent/brand/schema.py`), and CSS variables resolve through the
  `tokens.css` beside it. No tool names a brand color or family.
- Browser and image tools load `puppeteer-core` and `sharp` from the sandbox's pinned render
  toolchain (`/opt/design-agent/render`, from `sandbox/render/`), never from a copy in the
  workspace, and launch the one Chrome Headless Shell the recipe installs. Override with
  `DESIGN_AGENT_RENDER_DIR` and `DESIGN_AGENT_BROWSER`. `toolchain.mjs` holds this, the shared
  Chromium flags, flag parsing and confinement.

## Renderers

**`html2png.mjs`** — the stills renderer.

```bash
node /workspace/tools/html2png.mjs page.html --out out --name post \
  --size 1080x1350 --size 1080x1080 --size 1600x900 [--format png|jpeg|webp] [--quality 90] \
  [--scale 1] [--require-font "Geist" ...] [--brand-fonts [--tokens <tokens.json>]]
```

Writes `out/post-<W>x<H>.<ext>` per size and prints one JSON line:
`{"ok":true,"outputs":[{"path","width","height","bytes"}],"fonts":{"Geist":true}}`. Each size is a
fresh load at that viewport, so the layout recomposes (media queries, `vw`/`vh`); it is never a scaled
copy. `--scale 2` doubles the pixel size. A browser never fails on a missing font, it falls back, so
every `--require-font` family (and with `--brand-fonts`, the lead face of each brand font stack) must
actually paint: `document.fonts.check()` must pass *and* CDP must attribute a probe glyph run to that
platform font (`check()` alone answers true for any undeclared family). A missing font, a page error
or a failed asset request writes nothing and exits `1`.

**`html2pdf.mjs`** — the one HTML to PDF path (static decks, one-pagers).
`node /workspace/tools/html2pdf.mjs --html deck.html --out out/deck.pdf --size 8.5x11in [--zoom N] [--require-font F] [--brand-fonts]`.
Same font check, then the PDF's glyph advances are audited (`text-fidelity`) before it is written; a
quantized export exits `1` and writes nothing. `--zoom` is an opt-in fallback for a Chromium that
ignores the subpixel flag; it reflows anything sized in `vw`/`vh`.

**`review-thumb.mjs`** — a review-safe copy of renders (long edge 1600 px) so the agent can look at
them without tripping per-image size caps. `--sheet` tiles several into one contact sheet; read the
sheet, not the raw renders.

## Gates

**`brand-lint.mjs`** — the composition or copy against the brand pack.

```bash
node /workspace/tools/brand-lint.mjs page.html [--tokens <tokens.json>] [--json]
node /workspace/tools/brand-lint.mjs --copy post.txt [--tokens <tokens.json>] [--json]
```

Design mode reads an HTML or CSS file plus the local stylesheets it links (a link leaving the
workspace is reported, never read). `--json` prints
`{"ok","errors","warnings","findings":[{"severity","line","message","rule","file"}]}`. Rules, all
parameterized by `tokens.json`:

| Rule | Severity | Source in tokens.json |
| --- | --- | --- |
| `color.off-palette`, `color.banned` (with the replacement token), `color.extended` (WARN) | ERROR | `allowedColors`, `extendedPalette`, `officialAssetColors`, `bannedColors`, `replacementColors` |
| `font.off-brand`, `font.lead`, `font.mono-lead`, `font.unrecognized` (WARN) | ERROR | `knownOffBrandFonts`, `allowedFontTokens`, `fontStacks` (stacks lead with their first face or use `var(--brand-font-*)`) |
| `font.mono-spacing`, `font.mono-uppercase` | ERROR | `creativeTypography.monoLetterSpacing`, `allowMonoUppercaseTransform` |
| `radius.max`, `radius.pill` (WARN, 100 px and up) | ERROR | `maxRectRadiusPx` |
| `type.decorative-bullet`, `type.decorative-marker`, `motif.generic` | ERROR | `creativeTypography` |
| `case.all-caps`, `case.all-lowercase`, `case.lowercase-transform` | ERROR | `copy.casingRules.headlines` (`"any"` turns these off), `allowedAllCapsTerms` |
| `case.canonical` | ERROR | `copy.casingRules.canonical`, `creativeTypography.canonicalCasing` |
| `copy.banned-phrase`, `copy.banned-char`, `copy.warn-phrase` (WARN), `copy.hashtags` (copy mode) | ERROR | `copy.*`; words on a graphic follow the same rules as a post |
| `contrast.wcag` | ERROR | WCAG 2.1 text contrast (4.5:1, 3:1 for large text), resolving `var()` through the tokens |
| `grid.fractional`, `grid.line-height` (WARN) | ERROR | fractional box lengths snap unevenly to device pixels |
| `diagram.*` | ERROR | `diagramConstruction`: connector stroke bound to the token, one shared arrowhead in `<defs>`, connectors drawn as one path |

It refuses raster and binary targets (exit `2`): a text scan of compressed bytes reads coincidences as
colors. Lint the composition that produced the file and look at the pixels yourself.

**`video-gate.mjs`** — the cheap pre-render scan of a HyperFrames composition (or a build/probe
script) for patterns that break a seek-driven render: `Math.random`, `Date.now`, `new Date()`,
`Date()`, `performance.now`, crypto randomness, timers, `requestAnimationFrame`, a timeline not created
`{ paused: true }`, standalone `gsap.to/from`, zero-position `tl.set`, `offset-path`, remote assets
(the render is offline), `toFixed()` on a time and unguarded ffprobe CSV frame indexes. Warnings:
callbacks that re-fire on every seek, CSS transitions/animations, `left`/`top` tweens, network calls,
`inset: 0`, missing `text-rendering: geometricPrecision`. Brand is not its concern. `--json` supported.

**`film-probe.mjs`** — loads the composition in the sandbox Chrome, seeks the paused timeline the way
the renderer does, and writes a JSON film model: per-sample visibility, change, downsampled frame ink,
and pixel-confirmed collisions. Exit `2` if there is no timeline, browser or page.

**`film-analysis.mjs`** — pure analysis of a film model (no I/O): blank and thin frames, cuts that
carry nothing, shots that never develop or never rest, frozen motion, silent crops, collisions, type
hierarchy, load errors. Recorded models make durable regression fixtures.

**`video-score.mjs`** — the correctness gate: `video-gate` + `brand-lint` (`--tokens`, or
`--no-brand`) + probe + analysis. It fails on a failed hard gate or any artifact ERROR. The six axis
numbers it prints are a diagnostic, never a target; nothing gates on their sum.

**`artifact-contract.mjs`** — outputs exist and are what was asked for.

```bash
node /workspace/tools/artifact-contract.mjs --expect out/post-1080x1350.png:1080x1350 \
  --expect out/film.mp4:1920x1080@12 [--allow-blank-ends] [--json]
node /workspace/tools/artifact-contract.mjs --contract projects/<slug>/artifact-contract.json --phase plan|final
node /workspace/tools/artifact-contract.mjs --layers projects/<slug>/layer-manifest.json
```

`--expect` checks each file exists, is non-empty, decodes as its extension's format at exactly W x H
(PNG, JPEG and WebP from header bytes, no image library), and for video (`@<seconds>`, via ffprobe)
runs that long within one frame with non-blank first and last frames. The contract mode validates the
intake ledger and, in `final`, requires every requirement satisfied, superseded or waived, and
measures `output.path` when the contract names one.

**`text-fidelity.mjs`** — the rendered text is the requested text, set as authored.
`node text-fidelity.mjs out/deck.pdf` audits a PDF's glyph advances (pure Node: fails a run placed on
a whole-unit grid). `node text-fidelity.mjs --html page.html --expect copy.txt` loads the page and
fails any requested line that is missing from, or re-cased in, the text the page actually renders.

**`audio-lint.mjs`** — integrated loudness and true peak (EBU R128 via ffmpeg) against the master
target (default -14 ±1 LUFS, ≤ -1 dBTP), and `--expect-duration` within `--duration-tolerance`. A
file with no audio stream is a finding (`1`); a missing ffmpeg is a tooling failure (`2`).

## Fetching

**`fetch-asset.mjs`** — the one network tool: downloads public assets into the workspace so
compositions render offline. URLs are untrusted, so it allows only http(s), refuses credentials in
URLs, checks literal IPs before connecting and hostnames inside the connection's own DNS lookup (the
checked address is the dialled address), refuses private, loopback, link-local and metadata, CGNAT,
multicast, reserved and documentation ranges (and IPv6 forms that embed them), re-checks every
redirect hop, caps size and time, checks content type, and decodes images with `sharp`. It connects
directly and does not use an HTTP proxy from the environment.
`node /workspace/tools/fetch-asset.mjs <url> ... --out projects/<slug>/assets [--kind image|any] [--max-mb 25]`.
Prints `__FETCH_OK__` and one JSON line per saved asset, `__FETCH_ERR__ <url> <reason>` per failure;
exits `1` if any URL failed.
