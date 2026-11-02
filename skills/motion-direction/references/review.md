# Review

The critic's rubric for a film: how to score it, what each gate asks, how to look, and the failures
that keep coming back. The critic's brief (inputs, deliverable, constraints) is
[launch-film/briefs/critic.md](../../launch-film/briefs/critic.md); the still-frame rubric (accuracy,
hierarchy, copy, craft, brand, fit) is [design-wiki's review rubric](../../design-wiki/references/review-rubric.md),
and a film critic uses both. Thresholds are defaults to weigh; the verdict rule is a convention.

**Regenerate the evidence yourself.** Never score from the maker's sheets or self-score: render or
grab your own frames at times you choose, including the hardest moments (transitions, fast camera
moves, text). A maker's self-review is the trap this exists to avoid.

## Six areas

Score each 1-5; 4 and 2 sit between the anchors. Cite the timestamp and the image or number for
every score.

| Area | 5 | 3 | 1 |
| --- | --- | --- | --- |
| **Idea** | One sentence a stranger repeats; set up on frame 0, paid off on the last frame; survives the kill test | A real line or motif that arrives late or never resolves | Techniques or features named on screen; no sentence |
| **Story and pacing** | Hook complete within a second; passages that alternate expressive and quiet; holds that match reading time; the motion curve tracks the animatic or reference | A soft spot: a slow second, a beat that does not develop | Poster holds: animate into a pose and stop; one shot length throughout |
| **Craft** | Eases by role, log-space zooms, visible causes, carriers or named handoffs at cuts, fast moves built to blur | Correct but stock: one ease everywhere, heroes on the small side | Linear drift, beats opening on empty frames, clipped type |
| **Sound** | A designed sound on every event the eye follows; onsets on their hits; balanced; on loudness; the drop louder than the build | A bed with generic hits; some events silent; balance unmeasured | Silent, or a score that ignores the picture |
| **Brand** | Identity intact; one accent; every departure from a default declared in `STYLE.md` | A slip: a small logo under a huge headline, a radius past the cap with no reason | An invented colour, a redrawn or composed lockup, furniture on the poster frame |
| **Finish** | Blur checked at every fast move, no ghost at any cut, first and last frames proofread, every gate passes | One smear, one stray frame | A typo or counter on screen, a grey frame at a cut, a clipped name |

**Verdict** (convention): **ship** when every area scores 4 or more; **fix, then ship** when none is
below 3 and every must-fix is concrete; **rework** when Idea scores 2 or less or any area scores 1.
A film that clears every threshold and still reads as generic scores Idea 2: a weak pass is a reject.

## The gates

| Gate | Passes when |
| --- | --- |
| Concept | One repeatable sentence surviving the kill test; the beat list on the grid (music-led) or the script with its words (voiceover-led); a hook inside a second; one motif that resolves; a calm final frame |
| Storyboard | The concept gate, plus proof on screen, at most two attention demands a frame, a carrier or a named handoff at every cut, and every claim sourced in the ledger |
| Animatic | Every cut on the grid or its word; each copy onset within two frames of its word; each hit's audio onset on its time; holds declared in `AUDIT` with reasons |
| Act or scene | Every shot meets its bar (the spec's tolerances for a recreation, the craft rules for an original); clean frames at t−1, t and t+1 on both boundaries; `video-gate` at zero errors; the motion curve over its range close to the spec's |
| Integration | Clean frames at every boundary; the per-second motion curve tracks the animatic or reference with no outlier second unexplained; `video-score` passes, each finding inside a declared hold named; loudness on target |
| Final | The file matches the spec (`artifact-contract.mjs --expect <file>:<W>x<H>@<seconds>`); `audio-lint` passes; no empty, flickering or clipped frame; first and last frames proofread at full resolution |

Two blocking rounds on the same act or scene: stop and report it blocked, with the top note.

## How to look

| Look | What it catches |
| --- | --- |
| One still per beat (`hyperframes snapshot --at <beat times>`), tiled on one sheet | Empty or cramped beats, small heroes, off-grid moves |
| Strips through every transition, at least boundary −0.06, +0.10 and +0.28 s | Empty frames, double exposures, dips to grey, broken handoffs; a settled-frame sheet hides them all |
| Three frames either side of every cut (`film-breakdown/scripts/grab.mjs --sheet`) | A ghost across the cut, a stopped subject, a motif that jumps |
| The first frames and the last frame at full size | Grey blend frames, unlisted flashes, typos, counters |
| Full-resolution crops of type (`hyperframes snapshot --zoom "<selector>"`) | Spacing, clipping, legibility |
| Blurred moments at their midpoint, in the render | Missing blur, or blur smearing text |
| The per-second motion curve against the animatic or reference (`compare.mjs`) | Moves too big, too small or too fast; a fix in one second breaking the next. Re-run it after every change to speed or amplitude |
| `video-score` findings | Blank or thin frames, cuts that carry nothing, shots that never develop or never rest, collisions, crops, flat hierarchy |
| Sound numbers ([sound](sound.md)) | Sync, balance, loudness |

- **Judge stillness at the delivery frame rate**: a lower-rate preview reads less still than the final.
- **Counting tweens is not measuring motion**: measure pixels changing on rendered frames.
- **Confirm an anomaly with your eyes, then suspect the measurement**: a tool reporting motion on a
  frame an image diff shows unchanged is a parsing problem, not a film problem.
- **Looking costs context.** Keep sheets under about 1,500 px, crop to the region under test, and
  measure with a script instead of looking again (`look` keeps images out of the lead's context).

## Recreation fidelity, 1-5

| Score | Means |
| --- | --- |
| 5 | Indistinguishable from the spec in stills and in motion |
| 4 | Layout, copy and timing within tolerance; only material or lighting differs |
| 3 | Composition and timing right; some elements approximated |
| 2 | Recognisable, but layout or timing visibly off, or elements missing |
| 1 | Placeholder |

`film-breakdown` has the measured tolerances behind each score and the compare loop.

## Failure patterns

| Pattern | Looks like | Fix |
| --- | --- | --- |
| Poster holds | Animate into a pose, then hold it | A slow push or a beat punch; overlap the next entrance; the focal object keeps developing |
| Flat hierarchy | Everything at one weight; labels as headlines | One element at full contrast; support stepped down hard |
| Silence | No score, or sounds on nothing | A designed sound for every event the eye follows |
| Blank frames at cuts | A beat opening empty; a dissolve going grey | Entrances start partway in; flashes are listed cuts; a hard cut has no content lead |
| Over-full frames | Three or more things to read | Count the demands and split the shot |
| Furniture | HUDs, counters, crop marks, chips | Delete it; real product UI is proof, not furniture |
| Unreadable proof | Small, soft or brief | Larger, full contrast, held for its reading time |
| Dead air | A small thing alone on an empty ground | Scale it, push in, or bring the next idea on |
| Drift | A camera that floats | Real moves in log space: push, whip, orbit, rush |
| Self-review | The maker grades its own work | An independent critic, fresh evidence, pixels over time |

## The deliverable

`review/REVIEW-<gate>.md`: the verdict; a score per area (or per shot for an act) with its evidence;
at most twelve notes ranked by impact, each with the timestamp, what is wrong, why it matters to the
viewer and the concrete fix, marked MUST-FIX or NICE-TO-HAVE; and the strengths the next pass must
protect. A reviewer is read-only on everything but `review/`.
