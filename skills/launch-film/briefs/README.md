# Briefs

Fill-in briefs, one per job. The brief is the role: every helper is the same worker, and the brief
makes it a builder, a critic, an analyst or a sound designer. Start one with
`start_task(description=<the filled brief>, effort=...)`; it runs in the background. The
`launch_film` pipeline sends its steps with pointers to these same files, so a brief here is read
by its sandbox path (`/skills/launch-film/briefs/<file>`) as often as it is pasted.

A helper sees only its brief and the files the brief names, and cannot be messaged while it runs. So
every brief states everything: the role, why the work matters, the quality bar, the inputs, the
contract, the deliverables, the method, how to verify, the constraints, the budget, how to resume,
and the report.

| Brief | `effort` | When |
| --- | --- | --- |
| [concept.md](concept.md) | `max` for a long film, `xhigh` otherwise | Phase 2: directions, the recommended concept, a board draft |
| [analyst.md](analyst.md) | `xhigh` | A reference to recreate or learn from; a supplied track or voiceover |
| [act-builder.md](act-builder.md) | `max` or `xhigh` | The lead act and every act; re-layouts; polish passes |
| [sound.md](sound.md) | `xhigh` | The score and effects, when you don't make them yourself |
| [critic.md](critic.md) | `xhigh` (`max` for a launch film's final review) | Every gate |
| [helper.md](helper.md) | `low` | Integration previews, the final render, variants, share encodes |
| [resume.md](resume.md) | the same effort as the original | A failed or interrupted task; change notices between waves |

Fill every `{{…}}`, delete the blocks that don't apply (`[recreation]` or `[original]`), and keep a
filled brief under about 2,000 words: point to files for anything longer. Check every fact you put
in a brief, or mark it "unverified, check". A brief that says "music only" for a film that turns out
to be cut to a voiceover sends every helper the wrong way.

Every helper keeps its progress file current and tells the lead how it is going with
`report_progress` (when a section is done, when something blocks it or moves its ETA, before it stops
early). Helpers never upload, post or publish; the lead delivers.
