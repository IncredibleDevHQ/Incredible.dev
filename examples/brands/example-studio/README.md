# Example Studio (sample brand)

A fictional design studio made for this repository, so every example, fixture, test and gallery
output has an original, permissively licensed brand to render. Released under CC0-1.0 (see
[LICENSE](LICENSE)); the fonts it uses are OFL-1.1 and live in [`fonts/`](../../../fonts/).

| File | What it holds |
| --- | --- |
| `brand.toml` | name, voice summary, formats, logo usage |
| `tokens.json` | palette, fonts, radii, typography and copy rules; validated on load |
| `fonts.toml` | the families the brand renders with, with checksums |
| `logos/` | lockup and mark, for light and dark grounds (outlined SVG) |
| `voice.md` | tone and copy rules |
| `graphic-language.md` | what graphics mean and how they are built |

To use your own brand, copy this folder to `workspace/brand/` (Git-ignored), edit it, and run
`uv run design-agent brand validate`. The brand-onboarding coding-agent skill
(`.agents/skills/brand-onboarding/`) can draft it from a guide, a website or a Paper file.
