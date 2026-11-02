# Evals

Two kinds, both in `tests/eval/tasks.json` and both graded without a model judging taste:

- **The design set** (SPEC §20.5): 19 tasks on the sample brand — an ad set in four sizes, a
  LinkedIn card, a restyle of a supplied layout, a carousel, a one-pager, a 10-slide deck, two
  diagrams, a chart and a stat card, thumbnails, a storyboard, a teaser, a logo sting, a stat motion
  graphic, a 45-second launch film with voiceover, a GIF, a generated plate, a crop.
- **Behaviors** (SPEC §20.4), source-blind: a vague ask (at most two questions, otherwise decide),
  exact copy and fewest words, no invented logo when the brand has none, no claimed attachment
  without an upload, reporting a blocked artifact, Paper unavailable said once, quiet check-ins.
  Storyboard-first, gates-before-render and `look` over hoarded frames are checked on the film and
  restyle tasks.

```bash
uv run design-agent eval list
uv run design-agent eval run --task exact-copy --task flywheel            # a quick pair
uv run design-agent eval run --model anthropic:claude-opus-5-5 \
  --model openai:gpt-6.1-sol --model google_genai:gemini-3.6-flash --out docs/gallery/2026-10-run
```

`run` prints the budget (each task carries its own cap in minutes and dollars; the whole set is
about $120 per model) and asks before spending. It needs Docker and the sandbox image, and the keys
the tasks name. A task stops at 1.5x its time budget; going over its dollar budget fails it.

## Graders

| Check | How |
| --- | --- |
| Outputs | each expected file was delivered (`upload_files`), with the right size; videos measured by `artifact-contract` in the sandbox (duration within a frame, non-blank first and last frames) |
| Copy | each supplied line appears exactly in what was composed |
| Questions | sentences ending in `?` in the first reply, against the task's limit |
| Behaviors | the order and results of tool calls (`tests/unit/test_evals.py` shows each one on a synthetic trace) |
| Cost, time, precision | the run's metered spend, wall time, failed and repeated tool calls |

## Reports and the gallery

A run writes `report.json`, `README.md` (summary per model, failed checks per task) and a human
review checklist, plus `files/<task>/` and `traces/<task>.json`. A published run goes under
`docs/gallery/<run>/` with its human review notes; the reviewer and date are recorded with the
notes, not as people's names in code.
