---
name: thumbnails
description: Video thumbnails and A/B thumbnail sets, including refreshes of an older video's thumbnail, with small-size legibility checks. A thumbnail is a still; banners and social images go to stills.
---

# Thumbnails

A thumbnail has one job: make the right viewer pick this video over the ones around it, and promise
something the video then delivers. Platforms reward the promise being kept: YouTube's Test & Compare
picks a winner by watch-time share, not clicks, so a thumbnail that over-promises wins the click and
loses the test. Good here means clear in under a second, true to the video, distinct in the feed, and
made without visible seams.

## What holds

- **The idea beats the template.** No single design feature (face size, palette, word count, logo
  size) reliably wins across channels; what the thumbnail promises, and how literally it shows it,
  does. Spend the effort on the concept. Evidence and its strength: [references/evidence.md](references/evidence.md).
- **Real beats generic.** Real product UI, real code or a diagram, the people who are in the video,
  and a line that states the payoff do better than a branded title card.
- **Nobody predicts the winner**, people or models, so the test decides. Arms must be genuinely
  different bets, not tweaks of one design.
- **Legibility is physics.** The smallest desktop render is about 215 px wide and a phone shows about
  375 px; light type on a dark ground reads slower at those sizes, where size and weight carry it.

## Fixed facts

- **Platform.** 16:9, at least 1280×720, ideally 3840×2160, under 50 MB (2 MB from a phone). One A/B
  arm under 1280×720 drops every arm to 480p. The duration badge covers the bottom-right corner.
  Hover and autoplay replace the thumbnail with the video's first seconds, so the opening should pay
  it off.
- **Truth.** Show only what the video contains: its real UI, code, numbers and people as they look.
  Quote people word for word. Never generate a person's likeness, a product screen, a logo or a number.
- **Identity.** The real mark from `/workspace/brand/logos/` and the brand's type
  (`/workspace/brand/tokens.css`). Everything else (imagery, illustration, colour, composition) is
  chosen for the idea; the palette is home base, not a fence.
- **People.** Text the requester supplies ships as written, in their casing; their explicit edit
  outranks anything in this skill.

## How to work

A small edit to a delivered thumbnail is: change it, re-render, run the gate, look, deliver. A new
thumbnail, or a refresh of an older one, is a loop:

1. **Understand the video.** From the transcript (`transcribe_audio` if you only have the file) name
   the one thing a viewer walks away with, who it is for, who appears, and which real artifacts exist:
   a product screen, a diagram, a code moment, a good frame of the speaker. Ask for what you cannot
   get (a screenshot, a headshot), at most two questions.
2. **Diverge before you draw.** Write six to ten one-line concepts, each a different bet: the product
   doing the thing, the person, the verdict or claim, the diagram, the before and after, the number
   that is the finding. Drop the dishonest and the generic; render the best four to six quickly.
3. **Build the strongest well.** An HTML page authored at 1280×720 CSS px, words and the real mark set
   in HTML on top of whatever visual the idea needs: a frame from the footage, a real screen, a
   diagram (`data-viz`), a generated scene or object without text (`image-generation`). Mark the title
   `data-thumb-role="hero"` with px `top/left/width/height` so its contrast is measured.
4. **See it as a viewer.** Render, gate, and look at the small-size sheet, not the 4K file. Then give
   a fresh helper only the brief, a transcript summary and the sheets, and ask it to find defects and
   say whether each arm promises what the video delivers. A model's preference between arms is one
   opinion, not a prediction. Keep every version: a middle one is sometimes the best.
5. **Deliver the set.** Up to three arms, each a different bet, with one line on what each tests,
   safest honest arm first (an inconclusive test keeps the first). Lead with the small-size sheets,
   then the full-size files, in one `upload_files` call.
6. **Learn from the result.** When an approver states a standing preference or a test ends, record
   the arms, the bet each made and the winner's share where the project keeps its notes; your own
   results outrank everything in this skill.

## Instruments

```bash
node /workspace/tools/html2png.mjs projects/<slug>/thumbnail/a.html --out projects/<slug>/renders \
  --name thumb-a --size 1280x720 --scale 3 --brand-fonts            # a 3840x2160 master
node /workspace/skills/thumbnails/scripts/thumb-gate.mjs projects/<slug>/renders/thumb-a-1280x720.png \
  --comp projects/<slug>/thumbnail/a.html
node /workspace/skills/thumbnails/scripts/small-size-gate.mjs projects/<slug>/renders/thumb-a-1280x720.png
node /workspace/tools/brand-lint.mjs projects/<slug>/thumbnail/a.html
```

- `thumb-gate` fails (exit 1) only on what the platform rejects or degrades: not 16:9, under 1280 px
  wide, over 50 MB. Everything else prints as a measurement for your judgment (resolution, phone
  upload size, drawn content under the duration badge, the hero's words, size and measured contrast,
  rasters drawn wider than their pixels). Exit 2 means it could not look; report it.
- `small-size-gate` writes one sheet: the frame with player chrome, the phone size on a light feed,
  the smallest rail size on a dark feed, and grayscale. Look at it; it decides nothing.

Cutting out and grading a person, product screenshots, alignment, type size, quotes and generated
imagery: [references/craft.md](references/craft.md).
