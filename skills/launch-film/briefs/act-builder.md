# Act-builder brief (`effort`: `max` or `xhigh`)

The brief for one builder on one act of a film made by several in parallel. Fill every `{{…}}`,
delete the `[recreation]` or `[original]` blocks that don't apply, and keep the filled brief under
about 2,000 words. The `launch_film` pipeline's planner fills Part 1 once per act into
`briefs/act-<N>.md` in the project.

## Part 0: your checklist before sending (do not send)

- [ ] **The spec exists.** `[original]` An approved board and animatic, with `timeline.js` frozen.
      `[recreation]` `SHOTLIST.md` plus the analysis sections for this act, and `timeline.js` with
      cuts as frames, voiceover words and hits.
- [ ] **Boundaries sit on hard cuts.** If one is a continuous move, one act owns the whole transition
      and the boundary table below gives the state at t−1, t and t+1.
- [ ] **The shared rig is proven** in at least one finished act and frozen. `API.md` comes from the
      real exports (`grep -n "^export" rig/*.js timeline.js`), not from memory, and gives the exact
      line an act uses to load them.
- [ ] **The cross-act tables are set**, with this act's slots: which moves blur and how, post effects,
      the frame rate, the cut convention.
- [ ] **The act renders alone** (`hyperframes render --composition acts/act-{{N}}.html --quality draft`
      or `hyperframes snapshot --composition act-{{N}}`), and a smoke still comes out.
- [ ] **The act has its own scratch folder**, `scratch/act{{N}}/`.
- [ ] **The effort matches the act**: `max` for 3D, camera fits, organic motion, fidelity to a
      reference, the hero act and the lead; `xhigh` for type, UI, dashboards, diagrams, re-layouts and
      polish passes.
- [ ] **A review is planned** for when this act lands (the critic brief at `xhigh`).

## Part 1: the brief (send this)

```text
1. ROLE AND GOAL
You are one of {{K}} parallel act builders on "{{project}}": {{one line: what the film is, its length, where it ships}}.
You own ONE act: act {{N}}, {{T0}} s to {{T1}} s, from {{what the first frame shows}} to {{the cut or state at T1}}.
[recreation] The reference is the spec. Where the brand rules and the reference disagree on anything but identity
(marks, faces), match the reference and log it.
[original] The approved storyboard, animatic and STYLE.md are the spec. Where the spec and the brand pack disagree,
follow the brand pack and log it.

2. BUDGET AND STOP RULE
- Read `date` now. Stop and report {{45}} minutes from your start; check `date` at every render.
  - By {{15}} min: every section renders, placeholders allowed.
  - By {{30}} min: every shot scores at least 3 (see 6).
  - The last {{8}} minutes are for the checks in 7.5-7.8 and the report only.
- Stop earlier when every shot meets the bar in 6. Don't polish a shot at 4 while another is at 3.
- If time runs out, finish the current shot, write the progress file, and report what is left. You may be
  resumed from your progress file.
- Images: at most {{60}} image reads. Crop to what you are fixing; keep sheets at 1,500 px or less; when a script
  can give you a number, run the script instead of looking again. Keep every tool output under about 2 KB.
- The lead cannot message you while you run. Everything you need is in this brief and the files it names.
- Send `report_progress` when a section is done, when something blocks you or moves your stop time.

3. PATHS AND ENVIRONMENT
- Work dir (WD): /workspace/projects/{{slug}}/. Every file you create lives here. Run the hyperframes CLI from WD;
  the gates in /workspace/tools take paths relative to /workspace (projects/{{slug}}/...).
- How to build: /skills/motion-direction/SKILL.md and its references (craft.md, techniques.md,
  brand-in-motion.md); the HyperFrames contract in /skills/hyperframes-core/SKILL.md (sub-compositions: styles and
  scripts inside the <template>); the CLI in /skills/hyperframes-cli/SKILL.md.
- The film contract: one paused timeline per composition, seek-driven; no Math.random (use a seeded hash), no
  clock, no timers, no CSS animation; callbacks write state derived from their time. `video-gate` checks it.
- Offline: GSAP, fonts and every asset are local files in WD (see /skills/media-production/SKILL.md for GSAP).
- Rendering: {{K}} builders share this computer. Use `hyperframes snapshot` for stills and
  `hyperframes render --quality draft --workers 2` for short ranges of your act. Never render the whole film at full
  quality; a helper does that behind the render lock.
- [recreation] The reference is {{path}} ({{codec}}, {{WxH}}, {{fps}}, {{dur}} s). Read it in place, never copy it,
  and never composite its pixels, frames or crops into the film.
- Marks: only the real files in /workspace/brand/logos/. A missing official asset gets a labelled stand-in, logged
  ({{list}}).

4. YOUR CONTRACT
4.1 Range: acts/act-{{N}}.html covers exactly [{{start cut}}, {{end cut}}) of timeline.js, with no gaps and no
    overlaps. It renders alone (`hyperframes render --composition acts/act-{{N}}.html`) and inside index.html.
    Read every time from timeline.js; never type one. The act's timeline is local: its time 0 is {{T0}} s in the
    film, so subtract the act's start from every film time you read. Its root data-composition-id, the host slot's
    data-composition-id in index.html and its window.__timelines key are all "act-{{N}}"; ids inside it are prefixed
    "act{{N}}-" so they stay unique in the assembled film.
4.2 You may create or edit only:
    - acts/act-{{N}}.html and rig/act-{{N}}-*.js;
    - analysis/progress-act{{N}}.md, analysis/limits-act{{N}}.md, analysis/requests/act{{N}}-*.md,
      analysis/done-act{{N}}.json;
    - scratch/act{{N}}/**.
4.3 Read-only shared files. Read the worked example first: {{the act that shows the rig in use}}.
    {{paste API.md here, or point to API.md in WD: module, then one-line signatures, and the load line}}
    When a shared file is wrong or missing something:
    (a) work around it in rig/act-{{N}}-*.js, with a comment `FORK of <module>.<fn>: <what was missing>`;
    (b) propose the smallest change in analysis/requests/act{{N}}-<module>.md (what, why, a diff sketch); the lead
        merges requests between waves;
    (c) never import another act's private code.
4.4 Boundaries:
    | Boundary | Time (frame) | Type | Outgoing shows | Incoming shows | State to match | Owner |
    | Entry | {{T0}} ({{n0}}) | {{hard cut / continuous}} | {{…}} | {{…}} | {{none / state vector}} | {{act}} |
    | Exit  | {{T1}} ({{n1}}) | {{…}} | {{…}} | {{…}} | {{…}} | {{act}} |
    A state vector gives the camera, the grounds, each shared object's position, size, rotation and colour,
    anything moving with its velocity, and the copy on screen. Match it at t−1, t and t+1.
4.5 The grid: {{fps}} fps. Cuts land on the spec's frames. {{BPM}} BPM from {{GRID0}} s, or voiceover-led: copy lands
    on or just before its word (timeline.js VO). Hits in your range: {{…}}. Words in your range: {{…}}.
4.6 Cross-act mechanisms. Use these; don't reinvent them.
    - Motion blur: {{which moves blur, the component or render option, its settings}}; whips that carry copy stay
      sharp. Entries already in the film: {{…}}.
    - Post effects: {{policy}}. Don't add your own.
    - Glow: {{the film's glow rule, if the brand allows it}}; the halo goes under the body so labels stay readable.
    - Type: the brand's faces through local @font-face; size copy to its measured width, after fonts load.
    - Easing: the film's family ({{silk | snap | …}}) from rig/motion-presets.js.

5. WHAT TO BUILD
Specs: shots {{ids}} in SHOTLIST.md, {{analysis sections | board frames}}, {{the transcript}}.
| Shot | In-out (s) | Copy (verbatim) | Layout (px) | Camera and motion | Transition out | Lands on | Notes: hard parts, reuse, stand-ins |
{{rows}}
Look for this act: grounds {{…}} (tokens); accent {{…}}; light and depth {{…}}; marks {{…}}.

6. QUALITY BAR
Score each shot 1-5:
- 5: indistinguishable from the spec in stills and in motion;
- 4: layout, copy and timing within tolerance; only material or lighting differs;
- 3: composition and timing right, some elements approximated;
- 2: recognisable, but layout or timing wrong;
- 1: placeholder.
Tolerances (defaults; the lead may tighten them):
- cuts on the spec's frame exactly;
- copy verbatim, its box within ±8 px, its onset within ±2 frames;
- key poses within ±2 frames, positions ±10 px, sizes ±3%;
- grounds within ±8 per channel of the sampled colour (recreation) or the exact token (original);
- per-second motion energy over your range close to the spec's (correlation r ≥ 0.95, no second outside 0.7-1.4×
  without a reason).
Done means every shot scores 4 or more, or the time is spent and every remaining gap is named.

7. VERIFICATION LOOP (required)
7.1 Study for {{12}} minutes or less. Use /workspace/skills/film-breakdown/scripts/ (grab.mjs --sheet) for sheets of
    your range of the spec video and full-resolution stills at key poses. Measure positions, sizes and colours with
    scripts. Write the numbers into your progress file as you go.
7.2 Build section by section. After every change: `hyperframes snapshot --at <your BOARD times>` on your act, grab.mjs
    on the spec video at the same times, and one sheet of both (`node /workspace/tools/review-thumb.mjs --sheet ...`).
    The spec video is [recreation] the reference; [original] the approved animatic (build/animatic.mp4).
7.3 Measure each mismatch with a script (a box, a profile, a colour), not by eye. Log before and after.
7.4 Motion: once, cut the spec to your range on the same clock as your act
    (`ffmpeg -ss {{T0}} -i {{spec video}} -t {{T1 − T0}} -c:v libx264 -crf 12 -an scratch/act{{N}}/ref.mp4`). Then
    render your act as a draft (`hyperframes render --composition acts/act-{{N}}.html --quality draft --workers 2
    --output scratch/act{{N}}/draft-NN.mp4`) and compare:
    `node /workspace/skills/film-breakdown/scripts/compare.mjs --ref scratch/act{{N}}/ref.mp4 --mine
    scratch/act{{N}}/draft-NN.mp4 --out scratch/act{{N}}/cmp-NN --no-video`. Do it after every change to speed or
    amplitude: a fix for one second can break the next. Use a new --out for every round.
7.5 Blur: check your fast moments in the draft render at their midpoints.
7.6 Boundaries: frames T0−1, T0, T0+1, T1−1 and T1 through index.html (`hyperframes snapshot --at ...`).
7.7 Gates: `node /workspace/tools/video-gate.mjs projects/{{slug}}/acts/act-{{N}}.html` at 0 errors,
    `node /workspace/tools/brand-lint.mjs projects/{{slug}}/acts/act-{{N}}.html`, `hyperframes lint`. Exit 2 means the gate did not run:
    report it.
7.8 Final grid: about 12 key times, at least one per shot, in scratch/act{{N}}/final/grid.jpg.
Hygiene:
- edit with the edit tool or guarded replacements (assert the old text exists);
- `node --check` every JS file you touched, then snapshot;
- a render that prints an error or produces no frames is a failure: stop and fix it;
- grep your files for Math.random, Date, timers and module-level state.

8. LIMITS LOG (analysis/limits-act{{N}}.md)
Add an entry the moment a limit costs you time:
## L{{N}}-01 <name>
- Needed: <what the shot needs> (shot, time)
- Blocked by: <HyperFrames, brand or shared-rig behaviour> (file:function)
- Workaround: <what you did> (file:function); cost <min>; fidelity impact <none | minor | visible>
- Smallest fix: <the change and its API>

9. RESUME
Update analysis/progress-act{{N}}.md every 10 minutes with: the sections done; the measurements taken; your blur
settings; open problems; the next step. If that file exists when you start, you are resuming: read it first, carry
on from "next step", and don't redo recorded measurements.

10. REPORT
Write analysis/done-act{{N}}.json:
{"act": {{N}}, "range": [{{T0}}, {{T1}}], "files": [...], "grid": "scratch/act{{N}}/final/grid.jpg",
 "shots": [{"id": 0, "score": 4, "reason": "", "open": ""}], "motion": {"r": 0.0, "outliers": []},
 "blur": [], "forks": [], "requests": [], "limits": [], "minutes": 0, "images_viewed": 0}
Then reply in 250 words or fewer: the grid path; each shot's score with a one-line reason; what doesn't match, and
why; forks and requests; limit ids; time spent. Nothing else. A critic will check your scores against fresh evidence.
```

## Part 2: the lead act (add to Part 1 when this builder is the lead)

```text
LEAD
You also build the shared rig: {{the recurring systems}}. Prove it inside your finished act, then:
- put the shared modules and styles in rig/ (copy /skills/motion-direction/scripts/motion-presets.js there too);
- write API.md in WD from the real exports (`grep -n "^export" rig/*.js timeline.js`), one-line signatures, plus the
  exact line an act uses to load each module, proven by a snapshot of your act alone and inside index.html;
- write index.html so it mounts every act on its range from timeline.js, with placeholders for acts not built yet;
- leave rig/ frozen when you report: every other builder starts from it, in parallel.
```

## Why each rule is here

| Rule | What goes wrong without it |
| --- | --- |
| A stop time and `done-act<N>.json` | Builders stop whenever they like and the lead polls file times |
| An image budget, crops, measuring by script | Re-reading images dominates a helper's cost and fills its context |
| A progress file and the resume rule | A dropped connection loses every measurement made so far |
| Owned files and a scratch folder | Builders write into stray folders and each other's files |
| Forks and a requests channel | The same component is rebuilt in several acts |
| Cross-act mechanisms stated up front | A shared setting added mid-wave is never announced, and the final carries the defect |
| A motion re-check after speed changes | A fix in one second silently breaks the next |
| Guarded edits and a render after each edit | A bad splice deletes code and the next comparison hides the error |
| An independent critic | Self-scores go unchecked |
