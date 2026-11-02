# BRIEF.md template and question bank

## The template

Copy this into `/workspace/projects/<slug>/BRIEF.md` and fill it in your own words. Leave a field
out rather than writing "n/a"; mark anything you inferred rather than were told with "(inferred)".

```markdown
# <working title>

Asked by <who, in the thread's words> on <date>. Needed by <date or "no date">.

## The piece
- Goal: <what someone should do or believe after seeing it>
- Audience and place: <who sees it first, and where it plays>
- One message: <one sentence a stranger could repeat>
- Proof: <what on screen makes the message true, and where it comes from>

## Deliverables
| File | Size | Format | Notes |
| --- | --- | --- | --- |
| <name> | <W×H or length> | <png, pdf, mp4> | <channel, cut-down of, variant of> |

## Must include
- Copy that ships verbatim: "<exact text>"
- Marks and assets: <which logo, which supplied files>
- Avoid: <anything the ask rules out>

## Look
- Ground and mood: <from the brand pack, or the reference>
- Reference: <path, and whether it is preserved (a restyle) or a direction (an inspiration)>

## Sound (motion only)
- <voiceover script | music | both | none>; cut to <the voiceover | the music>

## Claims ledger
| Claim on screen | Source | Status |
| --- | --- | --- |
| "<the number or product claim>" | <where it comes from> | verified / measured / illustrative / unconfirmed |

## Decisions
- <each call you made that a person might not expect, with one line of why>

## Open
- <anything still missing, and what you did instead>
```

## Question bank

Pick the one or two highest-leverage unknowns. Each question here carries the reason you would give.

| Unknown | Ask | Why it changes the work |
| --- | --- | --- |
| Goal | "What should someone be able to do or believe after seeing this?" | It decides the message, the proof and the format |
| Proof | "What is the most concrete thing we can show: a number, a screen, a before and after?" | A piece with real proof leads with it; without, it leads with the product surface |
| Place | "Where does it go first: the feed, the docs, a talk?" | It decides the size, the mode and how much copy the frame holds |
| Audience depth | "Is this for people new to it, or people who already use it?" | It decides how much the frame explains and what it can assume |
| Must-includes | "Is there copy or an asset that has to appear exactly?" | Verbatim copy and required marks become contract requirements |
| Reference | "Should this match the attached file, or is it a direction?" | A restyle preserves every element; a direction only lends the look |
| Sound | "Voiceover, music, or silent?" | A voiceover sets the film's timing; music sets its tempo |
| Date | "Does it ride a date or an event?" | A dated piece front-loads the news and may need the date on the frame |

## Shapes a brief usually takes

| The goal, given the proof available | Usually becomes |
| --- | --- |
| Show a new capability, with a real screen | A product-surface still set, or a short film around the screen |
| Show a result, with a real number | A stat card or an annotated chart (`data-viz`), plus a post card |
| Explain how something works | A diagram (`data-viz`), a carousel, or an explainer film |
| Announce a date (an event, a release) | A card set with the date in its slot; an unknown date reads "Date to be confirmed" and you ask for it |
| Anything, with no proof yet | The product surface, real copy and type; the claim waits for its source |

An unknown date, price or name is never filled with a plausible one: the frame shows the empty slot
labelled as such, and the reply asks for it. When a weekday goes next to a date, compute it
(`date -d 2026-10-14 +%A`) rather than writing it from memory.
