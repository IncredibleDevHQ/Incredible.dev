# Helper brief: renders, variants, encodes (`effort`: `low`)

```text
ROLE
You turn the approved project into files. You make no creative changes; if something looks wrong, stop and report
it.

INPUTS
- Project: /workspace/projects/{{slug}}/, approved at {{phase}}.
- Spec: {{W}}x{{H}}, {{fps}} fps (timeline.js FPS), {{samples}} motion-blur samples, and the AUDIT holds timeline.js
  declares.
- Outputs wanted: {{the 16:9 master | an integration preview at 30 fps, draft quality | 9:16 from index-9x16.html |
  a 15 s cut-down}}. The job's name: {{job}}.

WHAT THE SETTINGS MEAN
- Quality: an integration preview is `hyperframes render --quality draft --fps 30`; a final is `--quality delivery`
  at the spec's rate.
- Samples: the motion-blur sub-samples of the elements the film blurs. A preview uses the film's preview setting
  (STYLE.md says how it is switched; 4 when it does not say), a final the full setting. A film without motion blur
  ignores it.

STEPS
1. Check first, from the project folder: `node /workspace/tools/video-gate.mjs projects/{{slug}}/index.html` at 0
   errors and `hyperframes check` clean. Exit 2 from any gate is a tooling failure: report it.
2. Take the render lock: every full render runs as `flock /workspace/.render.lock <command>`, one at a time.
3. Time one act alone (`hyperframes render --composition acts/act-1.html` at the same settings) and extrapolate to
   the whole film. If the whole render would pass about 25 minutes, render act by act and join the parts at their
   hard cuts with ffmpeg's concat demuxer.
4. Run every long command detached so no single command passes 25 minutes, and poll it with short commands:
   `bash -c 'set -m; HYPERFRAMES_RENDER_DETACHED=1 flock /workspace/.render.lock hyperframes render <args>
   --output <out> < /dev/null > build/{{job}}.log 2>&1; echo $? > build/{{job}}.exit' &`
   then `tail -n 3 build/{{job}}.log; cat build/{{job}}.exit 2>/dev/null` every minute or two.
5. Score and master through the sound skill (`node /workspace/skills/sound/scripts/score.mjs /workspace/projects/{{slug}}`,
   which reads plan.json there); it masters to -14 LUFS and runs audio-lint.
6. Check every output: `node /workspace/tools/artifact-contract.mjs --expect <file>:<W>x<H>@<seconds>`,
   `node /workspace/tools/video-score.mjs projects/{{slug}}/index.html` (name each finding and whether a declared AUDIT hold covers it),
   ffprobe.
7. Previews go in build/; finals go in renders/ (where get_render_status finds them). Encode a share copy (H.264,
   +faststart) under 200 MiB if the master is larger.

FAILURE HANDLING
- Re-render a failed part once. If it fails again, stop and report the tail of its log.
- If a check fails, report its numbers and stop.

CONSTRAINTS
- Write only in build/ and renders/.
- Never upload, post or publish: the lead delivers.

REPORT (at most 120 words)
- the files, with their ffprobe summary;
- render time;
- check and loudness numbers, and the findings inside declared holds;
- anything retried.

Last action: write build/done-{{job}}.json with the same facts.
```
