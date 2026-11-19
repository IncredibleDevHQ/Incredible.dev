from design_agent.episode.connections import resolve


def test_edges_use_cued_direction_across_held_lines_and_leave_ambiguous_arrows_out():
    first = {
        "id": "a",
        "objects": [
            {"id": "a1", "type": "node", "words": "Shop"},
            {"id": "a2", "type": "node", "words": "Bank"},
        ],
    }
    held = {
        "id": "b",
        "objects": [{"id": "m", "type": "connector", "words": "Authorized"}],
        "cues": [{"object": "m", "does": "travels from the bank to the shop"}],
    }
    edges = resolve([first, held])
    assert [(e["from"], e["to"], e["cue"], e["label"]) for e in edges] == [
        ("a2", "a1", "b/0", "Authorized")
    ]
    held["cues"][0]["does"] = "an arrow appears"
    assert not resolve([first, held])


def test_explicit_edge_wins_and_blocked_path_preserves_negation():
    nodes = [
        {"id": "s", "words": "Store", "type": "node"},
        {"id": "c", "words": "Client", "type": "node"},
    ]
    blocked = {
        "id": "x",
        "type": "cross",
        "words": "no request",
        "what": "a cross on the line from client to store",
    }
    frame = {
        "id": "f",
        "objects": [*nodes, blocked],
        "cues": [{"object": "x", "does": "appears on the line"}],
    }
    (edge,) = resolve([frame])
    assert (edge["from"], edge["to"], edge["blocked"]) == ("c", "s", True)
    blocked.update({"from": "s", "to": "c"})
    (edge,) = resolve([frame])
    assert (edge["from"], edge["to"]) == ("s", "c")


def test_direction_in_scene_prose_needs_named_endpoints():
    nodes = [
        {"id": "a", "words": "Shop", "type": "node"},
        {"id": "b", "words": "Bank", "type": "node"},
    ]
    frame = {"id": "f", "objects": nodes, "shows": "The Shop sends a request to the Bank."}
    (edge,) = resolve([frame])
    assert (edge["from"], edge["to"]) == ("a", "b")
    frame["shows"] = "The Shop is to the left of the Bank."
    assert resolve([frame]) == []
    frame["shows"] = "A line goes from the Bank to the Shop."
    (edge,) = resolve([frame])
    assert (edge["from"], edge["to"]) == ("b", "a")


def test_repeated_messages_between_same_participants_keep_distinct_cues():
    frame = {
        "id": "f",
        "objects": [
            {"id": "client", "type": "node", "words": "Client"},
            {"id": "server", "type": "node", "words": "Server"},
            {"id": "r1", "from": "client", "to": "server", "words": "Retry"},
            {"id": "r2", "from": "client", "to": "server", "words": "Retry"},
        ],
        "cues": [{"object": "r1", "does": "appears"}, {"object": "r2", "does": "appears"}],
    }
    assert [e["cue"] for e in resolve([frame])] == ["f/0", "f/1"]
