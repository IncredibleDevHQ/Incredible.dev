# The plan's three hands

Three hands make a plan. Nobody writes in another's.

| Whose | What it holds |
| --- | --- |
| The writer (you) | `plan.json`: words and intent. Nothing else ever rewrites it. |
| The classifier, and a person's picks | Every label, with how sure the classifier was, tied to the words it was read from. A line you change is unlabelled until it is read again. |
| Code | Every number and time: seconds, starts, when each cue lands, the marks, the totals, the layout of every frame. |

You see the second and third only through the report each turn opens with.

## plan.json: what you write

```jsonc
{
  "brief": {
    "idea": "...",                    // the one sentence a viewer leaves with
    "gap": "...",                     // what they lack before watching
    "for": "...",
    "seconds": 360,                   // from the person
    "presenter": "on",                // "on" | "off", from the person
    "theme": "corner-window",         // a theme id from types.md, from the person
    "series": "none",                 // "none", or the series and this video's place in it
    "case": {"text": "...", "from": "made up"},        // "notes" | "made up"
    "voice": {"sentence_words": 12, "person": "you"},
    "presenter_is": "..."             // optional: who the presenter is, when the script needs it
  },
  "material": [
    {"id": "m1", "text": "..."}       // one item of the notes, in your own short words
  ],
  "chapters": [
    {
      "id": "c1",
      "question": "...",              // the one question the chapter answers
      "wants": "introduction",        // the chapter type you meant
      "beats": [
        {
          "id": "c1.b1",
          "wants": "promise",         // the job you meant, a subtype id
          "says": "...",              // the narration, as spoken
          "uses": ["m1", "m4"],       // material it rests on; [] for a beat that frames or turns
          "made_up": false,           // true for the invented case and for analogies
          "frames": [                 // only when the beat's frame is cut, held or designed
            {
              "id": "c1.b1.f1",
              "vo": "...",            // only when the beat has more than one frame; the pieces joined are `says`
              "wants": "person",      // optional: who you meant to have the frame (person | both | content)
              "hold": false,          // true: keeps the picture of the frame before, and may add to it
              "shows": "...",         // what the viewer sees when the frame has finished
              "focal": "o1",          // the one object the eye follows
              "objects": [{"id": "o1", "what": "a box for the agent", "words": "Agent", "state": "active"}],
              "cues": [{"at": "agent", "object": "o1", "does": "draws its outline and fills"}]
            }
          ]
        }
      ]
    }
  ],
  "waived": {"turns": "the demo chapter runs on its own steps"}   // a `look` you keep, with the reason
}
```

## What the classifier adds

| On | It reads |
| --- | --- |
| The brief | the route, the hook, the landing |
| A material item | its kind |
| A chapter | its type and part, its top three readings, whether it answers its one question |
| A beat | its subtype and type, its top three readings, and whether your intent stood |
| A frame | how strongly the line reads as the person's or as needing something shown, the picture, its arrangement, how it follows the frame before |
| An object | its type |
| A cue | its move |

## What code adds

| On | It works out |
| --- | --- |
| A frame | who has it, its layout, the theme's layouts ranked for it, whether the line holds the picture before, its transition, a person's pick |
| Chapters, beats, frames | start, seconds, words |
| A cue | the second it lands |
| The plan | the marks (title sting, chapter cards, end card) and the totals |

## When a person changes who has the frame

A layout is never the one right answer. The plan keeps the ranked options for every frame so
that a person can pick another: for one frame, a chapter, or the whole film ("no speaker").
Their pick is kept beside the plan and applied every time the plan is read, so it survives your
edits. A pick changes more than the frame:

| The pick | What it breaks | What you redo |
| --- | --- | --- |
| Person to content, or to both | The line was said to camera; now something must be shown | `shows`, objects and cues for that frame, or `hold` on the picture before |
| Content or both to person | The picture is gone | Keep at most one term as an overlay; move what must be seen to a neighbouring frame |
| Both to content | The person leaves the frame | Nothing, unless `shows` or an object names the presenter |
| Presenter off | Nobody is on screen | A greeting by name, a claim to authority, banter, the goodbye and the ask are rewritten or cut |

Redo only what the turn names. Never undo a person's pick.
