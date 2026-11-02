# Looking at a generated image

The check before a generated image advances: on the cheap exploration pass, to kill weak variants;
on the final, before hand-off. `brand-lint` reads composed HTML; generated pixels need your eyes. Look
at a review copy (`node /workspace/tools/review-thumb.mjs <img>`, `--sheet` for a set).

A blocking defect (✗) means regenerate; anything else is a polish note, not a reason to loop. Two
rounds at most: if the second still blocks, stop and report it.

| Axis | Looking for | Blocking (✗) |
| --- | --- | --- |
| 1. Brand palette and mood | Reads as the brand: grounds and accents from `/workspace/brand/tokens.json` (or the campaign's agreed palette), at most one accent, the mood `graphic-language.md` and `voice.md` describe. | A second loud accent; colours far from the palette; a mood the voice rules out (hype, menace, generic sci-fi). |
| 2. Concept | The idea lands in three glances: subject, the visual idea, its tie to what is being said. | No discernible idea; generic "technology" wallpaper; abstract nodes, dots or networks standing in for a concept. |
| 3. Craft | Clean rendering, correct anatomy and perspective, deliberate composition and negative space, a clear focal point. | Garbled hands or faces, melted geometry, visible artefacts, cramped or no focal point. |
| 4. No fake marks or text | Generated without text and logos; those are composited for real later. | Any rendered letterforms, a fake wordmark, gibberish text, a watermark. |
| 5. Truth | Nothing that claims to be real: no invented product UI, people's likenesses, numbers or quotes. | A fabricated screen, person or figure presented as real. |
| 6. Cut-outs | The tool's receipt says the alpha is real; edges clean at a zoomed crop. | An opaque plate, a halo or a fringe around the subject. |

Discipline:

- Notes compound: per variant, what works, what fails, the fix, fed into the next prompt.
- The final is strong on concept and craft, not merely free of blocking defects. Mediocre and safe
  is still a reject.
- Axis 4 is absolute: a beautiful image with a fake logo is regenerated clean, and the real mark is
  composited in the layout step.
