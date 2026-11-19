"""The page a writer reads about the closed lists, written from the lists themselves, so what a
writer is told and what the classifier is asked cannot drift apart."""

from __future__ import annotations

from design_agent.episode import questions as Q


def types_markdown() -> str:
    """`skills/episode/references/types.md`, from `types.json`."""
    T = Q.TYPES
    L: list[str] = []
    A = L.append
    A("# The closed lists of a concept explainer\n")
    A(
        "Generated from the lists the classifier is asked (`design_agent.episode.doc`); a test keeps the two the same. Every label in a plan comes from one of these lists, and the classifier assigns it. Never type a label into a plan: write the words and let them be read. The id in backticks is what `wants` takes.\n"
    )
    A("## Parts\n")
    A("| Part | Its job | Share of the words |")
    A("| --- | --- | --- |")
    for x in T["parts"]:
        A(f"| {x['name']} | {x['job']} | {x['words_share'][0]} to {x['words_share'][1]}% |")
    A("\n## Chapter types\n")
    A(
        "A chapter answers one question. Its type picks the recipe of beats, and its part gives the order.\n"
    )
    A("| Chapter type | Part | What it does | Beats inside, in order | Words | Beats |")
    A("| --- | --- | --- | --- | --- | --- |")
    pn = {x["id"]: x["name"] for x in T["parts"]}
    bn = {x["id"]: x["name"] for x in T["beat_subtypes"]}
    for x in T["chapter_types"]:
        A(
            f"| {x['name']} (`{x['id']}`) | {pn[x['part']]} | {x['reads_as']} | {', '.join(bn[r].lower() for r in x['recipe'])} | {x['words'][0]} to {x['words'][1]} | {x['beats'][0]} to {x['beats'][1]} |"
        )
    A("\n## Beat types and subtypes\n")
    A(
        "A beat is a run of one to three sentences doing one job. The type is the job; the subtype is the way."
    )
    for bt in T["beat_types"]:
        A(f"\n### {bt['name']}: {bt['job'].lower()}\n")
        A("| Subtype | Reads as |")
        A("| --- | --- |")
        for x in T["beat_subtypes"]:
            if x["type"] == bt["id"]:
                A(f"| {x['name']} (`{x['id']}`) | {x['reads_as']} |")

    def simple(title: str, key: str, intro: str) -> None:
        A(f"\n## {title}\n")
        if intro:
            A(intro + "\n")
        A("| Name | Reads as |")
        A("| --- | --- |")
        for x in T[key]:
            A(f"| {x['name']} (`{x['id']}`) | {x.get('reads_as', '')} |")

    simple("Material kinds", "material_kinds", "What an item of the notes is.")
    simple("Routes", "routes", "How the material is ordered.")
    simple(
        "Hooks",
        "hooks",
        "How the first lines earn the next ten seconds. Half of published explainers open with none.",
    )
    simple("Landings", "landings", "How the last content line brings the idea home.")
    simple(
        "Presence",
        "presence",
        "Who has the frame while a line is said. A person can switch between the three while recording.",
    )
    A("\n## Layouts\n")
    A("| Layout | Presence | Reads as | From |")
    A("| --- | --- | --- | --- |")
    for x in T["layouts"]:
        A(f"| {x['name']} (`{x['id']}`) | {x['presence']} | {x['reads_as']} | {x['from']} |")
    simple(
        "Overlays", "overlays", "Words the theme lays on a layout for a few seconds. Not a layout."
    )
    A("\n## Picture types\n")
    A("| Picture | Group | Reads as |")
    A("| --- | --- | --- |")
    for x in T["picture_types"]:
        A(f"| {x['name']} (`{x['id']}`) | {x['group']} | {x['reads_as']} |")
    simple(
        "Arrangements",
        "arrangements",
        "How the things inside a built picture sit. A storyboard draws a frame from this.",
    )
    A("\n## Object types\n")
    fam: dict[str, list[str]] = {}
    for x in T["object_types"]:
        fam.setdefault(x["family"], []).append(x["name"])
    for k, v in fam.items():
        A(f"- **{k.capitalize()}:** {', '.join(v)}.")
    A("\nAn object has a state: " + ", ".join(T["object_states"]) + ".")
    A("\n## Moves\n")
    A("What a cue does. Each is a kind of move HyperFrames can make.\n")
    A("| Move | Reads as | From |")
    A("| --- | --- | --- |")
    for x in T["moves"]:
        A(f"| {x['name']} (`{x['id']}`) | {x['reads_as']} | {x['from']} |")
    A("\n## How a frame follows the one before\n")
    A("| Relation | Reads as | Transition |")
    A("| --- | --- | --- |")
    for x in T["relations"]:
        A(f"| {x['name']} (`{x['id']}`) | {x['reads_as']} | {x['transition']} |")
    A("\n## Themes\n")
    A(
        "The shares are how a film on that theme splits its running time between the person, the person with content, and content alone.\n"
    )
    A("| Theme | Presenter | Stage | Layout kit | Person / both / content | Marks | Motion |")
    A("| --- | --- | --- | --- | --- | --- | --- |")
    ln = {x["id"]: x["name"] for x in T["layouts"]}
    for x in T["themes"]:
        sh = x["shares"]
        A(
            f"| {x['name']} (`{x['id']}`) | {x['presenter']} | {x['stage']} | {', '.join(ln[k].lower() for k in x['kit'])} | {round(100 * sh['person'])} / {round(100 * sh['both'])} / {round(100 * sh['content'])}% | {', '.join(x['marks'])} | {x['motion']} |"
        )
    return "\n".join(L) + "\n"
