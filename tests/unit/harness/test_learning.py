"""Observations: saved with evidence, merged when they repeat, counted, pruned and rendered."""

import json

import pytest
from langgraph.store.memory import InMemoryStore

from design_agent.harness import events as ev
from design_agent.harness.learning import (
    HEADING,
    MAX_PROPOSALS,
    Observation,
    ObservationStore,
    digest,
    near_duplicate,
    normalize,
    parse_proposals,
    post_job_brief,
    skill_key,
)

SKILL = "storyboard"


class Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        self.now += 1
        return self.now


@pytest.fixture
def notes() -> ObservationStore:
    return ObservationStore(InMemoryStore(), clock=Clock())


async def test_a_new_note_is_saved_proposed_with_its_evidence(notes):
    saved, merged = await notes.add(
        SKILL, "  - Stills at 1,500 px got sign-off\n in one round. ", ["launch-film, 09-20"]
    )

    assert not merged
    assert saved.text == "Stills at 1,500 px got sign-off in one round."
    assert saved.evidence == ["launch-film, 09-20"]
    assert (saved.helpful, saved.harmful, saved.status) == (0, 0, "proposed")
    assert saved.id.startswith("o-") and saved.skill == SKILL
    assert await notes.get(SKILL, saved.id) == saved


async def test_a_near_duplicate_merges_into_the_saved_note_and_counts_again(notes):
    first, _ = await notes.add(
        SKILL, "The person asked for larger type on the 9:16 cut twice.", ["film-a: round 1"]
    )
    again, merged = await notes.add(
        SKILL, "the person asked for LARGER type on the 9:16 cut, twice", ["film-b: round 2"]
    )

    assert merged and again.id == first.id
    assert again.text == first.text  # the saved wording stays
    assert again.helpful == 1 and again.status == "kept"
    assert again.evidence == ["film-a: round 1", "film-b: round 2"]
    assert len(await notes.list(SKILL, min_score=-10)) == 1


def test_either_measure_makes_a_near_duplicate():
    # The same words in another order: token Jaccard is 1.0.
    assert near_duplicate(
        "larger type was asked for on the vertical cut",
        "on the vertical cut larger type was asked for",
    )
    # Inflections: the token sets overlap too little, but the text is nearly the same.
    a, b = (
        "Renders of the hero shot took 40 minutes each",
        "Render of the hero shots took 40 minutes each",
    )
    tokens_a, tokens_b = set(a.lower().split()), set(b.lower().split())
    assert len(tokens_a & tokens_b) / len(tokens_a | tokens_b) < 0.8
    assert near_duplicate(a, b)
    assert not near_duplicate(
        "Stills at 1500 px got sign-off in one round",
        "The person wanted the logo larger on the end card",
    )


async def test_different_notes_stay_apart(notes):
    await notes.add(SKILL, "Stills at 1500 px got sign-off in one round", ["a"])
    await notes.add(SKILL, "The person wanted the logo larger on the end card", ["b"])
    await notes.add("launch-film", "Stills at 1500 px got sign-off in one round", ["c"])

    assert len(await notes.list(SKILL)) == 2
    assert len(await notes.list("launch-film")) == 1


async def test_ratings_count_and_a_helpful_one_keeps_the_note(notes):
    saved, _ = await notes.add(SKILL, "The end card holds for 2 s before the logo", ["x"])

    helped = await notes.vote(SKILL, saved.id, True)
    hurt = await notes.vote(SKILL, saved.id, False)

    assert helped is not None and (helped.helpful, helped.status) == (1, "kept")
    assert hurt is not None and (hurt.helpful, hurt.harmful, hurt.status) == (1, 1, "kept")
    assert hurt.updated_at > saved.updated_at
    assert await notes.vote(SKILL, "o-missing", True) is None


async def test_prune_drops_notes_whose_harm_leads_by_two(notes):
    wrong, _ = await notes.add(SKILL, "Glass UI tested best with developers", [])
    mixed, _ = await notes.add(SKILL, "The person prefers a slow push-in on the logo", [])
    worse, _ = await notes.add(SKILL, "Voiceover at 150 words a minute felt rushed", [])
    for _ in range(2):
        await notes.vote(SKILL, wrong.id, False)
        await notes.vote(SKILL, mixed.id, False)
    await notes.vote(SKILL, mixed.id, True)
    await notes.vote(SKILL, worse.id, True)
    for _ in range(3):
        await notes.vote(SKILL, worse.id, False)

    dropped = await notes.prune(SKILL)

    assert sorted(o.id for o in dropped) == sorted([wrong.id, worse.id])
    assert [o.id for o in await notes.list(SKILL, min_score=-10)] == [mixed.id]


async def test_list_puts_the_best_first_and_hides_net_harmful_notes(notes):
    low, _ = await notes.add(SKILL, "Captions at the bottom third collided with the lower bar", [])
    high, _ = await notes.add(SKILL, "Beat stills sped up the storyboard review", [])
    negative, _ = await notes.add(SKILL, "Two accents read as busy on 9:16", [])
    await notes.vote(SKILL, high.id, True)
    await notes.vote(SKILL, high.id, True)
    await notes.vote(SKILL, negative.id, False)

    assert [o.id for o in await notes.list(SKILL)] == [high.id, low.id]
    assert [o.id for o in await notes.list(SKILL, min_score=-1)] == [high.id, low.id, negative.id]


async def test_list_reads_past_the_stores_first_page():
    store = InMemoryStore()
    for i in range(105):
        value = Observation(id=f"o-{i:03}", skill=SKILL, text=f"note {i}").to_value()
        await store.aput(ObservationStore.namespace(SKILL), value["id"], value)

    assert len(await ObservationStore(store).list(SKILL)) == 105


async def test_render_is_a_compact_list_under_the_untrusted_notes_heading(notes):
    assert await notes.render(SKILL) == ""
    kept, _ = await notes.add(SKILL, "Beat stills sped up the storyboard review", ["film-a"])
    for evidence in (["film-b"], ["film-c"]):
        await notes.add(SKILL, "Beat stills sped up the storyboard review", evidence)
    fresh, _ = await notes.add(SKILL, "The person asked for the CTA on the last beat", [])

    rendered = await notes.render(SKILL)

    lines = rendered.splitlines()
    assert lines[0] == HEADING
    assert "untrusted notes; weigh them yourself" in HEADING
    assert lines[1] == (
        "- Beat stills sped up the storyboard review "
        f"(+2/−0; evidence: film-c; film-b; +1 more) [{kept.id}]"
    )
    assert lines[2] == (
        "- The person asked for the CTA on the last beat "
        f"(+0/−0, proposed; evidence: none recorded) [{fresh.id}]"
    )
    short = await notes.render(SKILL, limit=1)
    assert short.splitlines()[-1] == "(1 more with lower scores are not shown.)"


def test_a_skill_name_is_a_store_namespace_label():
    assert skill_key(" Launch Film ") == "launch-film"
    assert ObservationStore.namespace("launch-film") == ("harness", "observations", "launch-film")
    for bad in ("", "a.b", "../x", "-x"):
        with pytest.raises(ValueError):
            skill_key(bad)


def test_normalize_keeps_one_line():
    assert normalize("1. two\n  lines ") == "two lines"
    assert len(normalize("x" * 900)) == 500


# -- the post-job review -----------------------------------------------------------------------


def test_the_post_job_brief_asks_for_observations_with_evidence_as_json():
    brief = post_job_brief(
        "A 30 s teaser. Round 2 asked for larger type.",
        "Launch Film",
        existing=f"{HEADING}\n- Beat stills sped up review (+1/−0; evidence: x) [o-1]",
    )

    assert "A 30 s teaser. Round 2 asked for larger type." in brief
    assert "finished launch-film job" in brief
    assert "Beat stills sped up review" in brief
    assert f"Up to {MAX_PROPOSALS} observations" in brief
    assert "rather than a rule" in brief
    assert '{"skill": "launch-film", "observations": [{"text": "...", "evidence":' in brief
    assert "Nothing yet." in post_job_brief("", SKILL)


def test_proposals_are_read_from_the_helpers_json_however_it_is_wrapped():
    payload = {
        "skill": SKILL,
        "observations": [
            {"text": "Larger type was asked for twice", "evidence": ["round 1", "round 2"]},
            {"text": "  ", "evidence": ["dropped: no text"]},
            {"text": "The end card was cut to 2 s", "evidence": "one piece of evidence"},
            "A bare string counts too",
        ],
    }
    fenced = f"Here is what I found:\n```json\n{json.dumps(payload)}\n```\nDone."

    proposals = parse_proposals(fenced)

    assert proposals == [
        {"text": "Larger type was asked for twice", "evidence": ["round 1", "round 2"]},
        {"text": "The end card was cut to 2 s", "evidence": ["one piece of evidence"]},
        {"text": "A bare string counts too", "evidence": []},
    ]
    assert parse_proposals(json.dumps(payload["observations"][:1])) == proposals[:1]
    assert parse_proposals("I could not find anything worth noting.") == []
    many = {"observations": [{"text": f"note {i}", "evidence": []} for i in range(9)]}
    assert len(parse_proposals(json.dumps(many))) == MAX_PROPOSALS


def test_a_proposal_whose_evidence_is_one_value_keeps_it_as_one_line():
    odd = {
        "observations": [{"text": "Two rounds", "evidence": 2}, {"text": "None", "evidence": None}]
    }
    assert parse_proposals(json.dumps(odd)) == [
        {"text": "Two rounds", "evidence": ["2"]},
        {"text": "None", "evidence": []},
    ]


def test_the_digest_leaves_out_costs_and_ticks():
    events = [
        ev.Event(ev.TASK_DONE, "th", "t-1", label="look a", text="Done:\nstills in out/", at=0),
        ev.Event(ev.USAGE, "th", "lead", text="1,200 tokens", at=1),
        ev.Event(ev.WATCH_PROGRESS, "th", "r-1", text="41%", at=2),
        ev.Event(ev.TASK_STARTED, "th", "t-2", label="look b", at=3),
    ]
    assert digest(events) == (
        "00:00 task.done t-1 (look a): Done: stills in out/\n00:00 task.started t-2 (look b)"
    )
