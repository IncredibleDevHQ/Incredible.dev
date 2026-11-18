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
