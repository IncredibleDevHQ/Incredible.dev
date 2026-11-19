"""Illustrations share measured placement, reusable assets and the narration's GSAP clock."""

from design_agent.episode import catalog, illustrations, picture, sketch


def test_illustration_beats_use_the_reusable_scene_by_default() -> None:
    selected = catalog.select({}, [], {}, "illustration", 1920)
    assert selected["component"] == "illustration"
    assert selected["variant"] == "balanced"


def test_assets_are_named_safe_choices_and_the_library_is_bundled() -> None:
    assert {"phone", "satellite", "browser", "server", "person"} <= illustrations.ASSETS.keys()
    assert illustrations.asset_for({"asset": "<script>", "what": "a phone"}) == "phone"
    assert illustrations.asset_for({"asset": "satellite", "what": "anything"}) == "satellite"
    assert illustrations.asset_for({"what": "an unfamiliar object"}) == "object"
    source = sketch.built(
        {
            "composition_id": "pic-test",
            "canvas": {"width": 800, "height": 450},
            "keep_clear": None,
            "look": picture.Look().tokens(),
            "visual": {"component": "illustration", "variant": "balanced"},
            "lines": [
                {
                    "frame": "f",
                    "focal": "a",
                    "camera": "focus",
                    "visible": ["a"],
                    "objects": [{"id": "a", "asset": "phone", "words": "Receiver"}],
                    "cues": [{"key": "f/0", "object": "a", "move": "reveal", "does": "appears"}],
                }
            ],
        }
    )
    assert "@svgdotjs/svg.js v3.2.8" in illustrations.library() and "data-illustration" in source
    assert 'src="http' not in source
    assert 'window.__timelines["pic-test"]' in source


def test_illustration_direction_is_in_the_picture_brief() -> None:
    unit = {
        "id": "f",
        "frames": ["f"],
        "layout": "corner-window",
        "canvas": [1920, 1080],
        "picture": "illustration",
        "visual": {"component": "illustration", "variant": "balanced"},
    }
    full = {
        "chapters": [
            {
                "beats": [
                    {
                        "frames": [
                            {
                                "id": "f",
                                "focal": "a",
                                "camera": "focus",
                                "visible": ["a"],
                                "objects": [{"id": "a", "asset": "phone", "what": "receiver"}],
                            },
                        ]
                    }
                ]
            }
        ]
    }
    brief = picture.brief(unit, full)
    assert brief["lines"][0]["camera"] == "focus"
    assert brief["lines"][0]["visible"] == ["a"]
    assert brief["lines"][0]["objects"][0]["asset"] == "phone"
    assert brief["illustrations"]["assets"]["phone"]


def test_everyday_objects_use_distinct_assets_even_with_a_generic_hint() -> None:
    assert illustrations.asset_for({"asset": "object", "what": "a metal spoon"}) == "metal-spoon"
    assert illustrations.asset_for({"asset": "object", "what": "a wooden spoon"}) == "wooden-spoon"
    assert illustrations.asset_for({"what": "a warm hand touching the metal spoon"}) == "hand"
    assert illustrations.asset_for({"what": "a thermometer on the wooden spoon"}) == "thermometer"
    assert illustrations.asset_for({"what": "a ceramic mug filled with hot tea"}) == "cup"
    assert (
        illustrations.asset_for({"what": "a line carrying heat into a spoon", "type": "connector"})
        == "object"
    )


def test_physical_comparison_builds_artwork_and_keeps_relationship_cues() -> None:
    brief = {
        "composition_id": "pic-test",
        "canvas": {"width": 1920, "height": 1080},
        "keep_clear": None,
        "look": picture.Look().tokens(),
        "visual": {"component": "comparison", "variant": "side-by-side"},
        "connections": [{"from": "cup", "to": "spoon", "object": "heat", "cue": "f/0"}],
        "lines": [
            {
                "frame": "f",
                "objects": [
                    {"id": "cup", "what": "a ceramic cup", "type": "illustration"},
                    {"id": "spoon", "what": "a silver metal spoon", "type": "hero-object"},
                    {"id": "heat", "what": "heat flowing to the spoon", "type": "connector"},
                ],
                "cues": [{"key": "f/0", "object": "heat", "move": "draw", "does": "heat travels"}],
            }
        ],
    }

    source = sketch.built(brief)

    assert "data-illustration" in source
    assert '"asset": "metal-spoon"' in source
    assert '"asset": "cup"' in source
    assert '"cue": "f/0"' in source
    assert "data-transfer" in source


def test_generic_abstract_comparisons_keep_the_table() -> None:
    assert not sketch.uses_illustration(
        "comparison",
        [{"what": "a storage policy card", "type": "card"}],
    )


def test_unknown_concrete_objects_are_identified_for_drawing() -> None:
    objects = [
        {"id": "unknown", "type": "illustration", "what": "a gyroscope held in a hand"},
        {"id": "known", "type": "illustration", "what": "a warm hand"},
        {"id": "abstract", "type": "card", "what": "a design constraint"},
    ]
    assert illustrations.custom_objects(objects) == ["unknown"]


def test_unfamiliar_illustration_requires_shapes_for_each_object() -> None:
    brief = {
        "visual": {"component": "illustration"},
        "lines": [{"objects": [{"id": "gyro", "type": "illustration", "what": "a gyroscope"}]}],
    }
    assert sketch.artwork_faults(
        '<template><g data-episode-object="gyro"><text>Gyroscope</text></g></template>', brief
    )
    assert sketch.artwork_faults(
        '<template><g data-episode-object="else"><path d="M1 1H4"/></g></template>', brief
    )
    assert sketch.artwork_faults(
        '<template></template><g data-episode-object="gyro"><ellipse rx="8" ry="4"/></g>', brief
    )
    assert not sketch.artwork_faults(
        '<template><g data-episode-object="gyro"><ellipse rx="8" ry="4"/></g></template>', brief
    )


def test_replacing_an_illustrated_starter_with_labels_fails_the_artwork_check() -> None:
    brief = {
        "visual": {"component": "comparison"},
        "lines": [{"objects": [{"id": "cup", "what": "a ceramic mug", "type": "illustration"}]}],
    }
    assert sketch.artwork_faults("<template><svg><text>Mug</text></svg></template>", brief)


def test_physical_comparison_keeps_explicit_transfer_endpoints() -> None:
    frame = {
        "id": "f",
        "picture": "diagram",
        "component": "comparison",
        "objects": [
            {"id": "cup", "what": "a ceramic mug", "type": "illustration"},
            {"id": "spoon", "what": "a metal spoon", "type": "hero-object"},
            {
                "id": "heat",
                "type": "connector",
                "from": "cup",
                "to": "spoon",
                "words": "Heat",
            },
        ],
        "cues": [{"at": "warms", "object": "heat"}],
    }
    selected = catalog.select(frame, [frame], {}, "diagram", 1920)
    assert selected["component"] == "comparison"
    assert [(edge["from"], edge["to"], edge["cue"]) for edge in selected["connections"]] == [
        ("cup", "spoon", "f/0")
    ]


def test_statement_does_not_print_undrawn_decorative_mark_descriptions() -> None:
    source = sketch.built(
        {
            "composition_id": "pic-end",
            "canvas": {"width": 800, "height": 450},
            "keep_clear": None,
            "look": picture.Look().tokens(),
            "visual": {"component": "statement", "variant": "centered"},
            "lines": [
                {
                    "frame": "end",
                    "objects": [
                        {"id": "title", "type": "headline", "words": "Heat transfer"},
                        {"id": "mark", "type": "logo", "what": "a decorative cup mark"},
                    ],
                    "cues": [],
                }
            ],
        }
    )
    assert "Heat transfer" in source and "a decorative cup mark" not in source
