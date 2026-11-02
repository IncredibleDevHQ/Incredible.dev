"""Every step reads as studio work, in both tenses, and never as its raw arguments."""

from __future__ import annotations

import pytest

from design_agent.surfaces.slack.phrasebook import phrase, services, todo_status

SERVERS = services(["paper", "exa", "docs", "acmestudio"])


@pytest.mark.parametrize(
    ("path", "doing", "done"),
    [
        (
            "/skills/storyboard/SKILL.md",
            "Opening the storyboard playbook",
            "Opened the storyboard playbook",
        ),
        (
            "/workspace/skills/data-viz/references/patterns.md",
            "Opening the data viz playbook",
            "Opened the data viz playbook",
        ),
        ("/workspace/brand/tokens.json", "Studying the brand book", "Studied the brand book"),
        ("brand/voice.md", "Studying the brand book", "Studied the brand book"),
        (
            "/workspace/references/film-a/teardown.md",
            "Studying the reference shelf",
            "Studied the reference shelf",
        ),
        ("/memories/user/AGENTS.md", "Checking your preferences", "Checked your preferences"),
        ("/memories/agent/notes.md", "Checking the studio's notes", "Checked the studio's notes"),
        ("/workspace/attachments/F0TEST0001__brief.pdf", "Reading your file", "Read your file"),
        (
            "/workspace/projects/launch/scene.html",
            "Reading the composition",
            "Read the composition",
        ),
        ("/workspace/projects/launch/out/hero.png", "Reading an image", "Read an image"),
        ("/workspace/projects/launch/notes", "Reading the project", "Read the project"),
        ("/workspace/.renders/r-1.log", "Reading the render log", "Read the render log"),
        ("/tmp/whatever", "Reading a file", "Read a file"),
    ],
)
def test_a_read_is_named_for_the_place_it_reads(path: str, doing: str, done: str) -> None:
    assert phrase("read_file", {"file_path": path}) == (doing, done)


def test_writes_and_edits_name_the_kind_of_thing_made() -> None:
    assert phrase("write_file", {"file_path": "/workspace/projects/x/scene.html"}) == (
        "Drafting the composition",
        "Drafted the composition",
    )
    assert phrase("edit_file", {"file_path": "/workspace/projects/x/make.mjs"}) == (
        "Reworking a script",
        "Reworked a script",
    )
    assert phrase("edit_file", {"file_path": "/memories/user/AGENTS.md"}) == (
        "Updating your preferences",
        "Updated your preferences",
    )


@pytest.mark.parametrize(
    ("command", "doing"),
    [
        (
            "cd /workspace/projects/launch && npx hyperframes render --out out/cut.mp4",
            "Rolling the render",
        ),
        ("npx hyperframes lint", "Checking the work"),
        ("npx hyperframes snapshot --at 1.0", "Shooting stills"),
        ("ffmpeg -i in.mov -vf scale=1080:-2 out.mp4", "Cutting the footage"),
        ("node /workspace/tools/brand-lint.mjs scene.html", "Checking the work"),
        ("d2 flywheel.d2 flywheel.svg", "Drawing the diagram"),
        ("fc-match 'Example Sans'", "Checking the fonts"),
        ("python3 make_chart.py", "Running a script"),
        ("some-private-binary --token s3cr3t", "Working in the sandbox"),
    ],
)
def test_a_command_reads_as_what_the_studio_is_doing(command: str, doing: str) -> None:
    assert phrase("execute", {"command": command})[0] == doing


@pytest.mark.parametrize(
    ("name", "doing", "done"),
    [
        ("paper_write_html", "Writing HTML in Paper", "Wrote HTML in Paper"),
        ("paper_set_text_content", "Setting text content in Paper", "Set text content in Paper"),
        ("paper_get_screenshot", "Reading screenshot in Paper", "Read screenshot in Paper"),
        ("paper_export", "Exporting in Paper", "Exported in Paper"),
        ("exa_web_search_exa", "Searching the web", "Searched the web"),
        ("docs_search", "Searching Docs", "Searched Docs"),
        ("docs_SearchPages", "Searching pages in Docs", "Searched pages in Docs"),
        ("docs_wait-session", "Waiting for session in Docs", "Waited for session in Docs"),
        (
            "acmestudio_models_explore",
            "Exploring models in Acmestudio",
            "Explored models in Acmestudio",
        ),
        ("acmestudio_balance", "Checking balance in Acmestudio", "Checked balance in Acmestudio"),
        (
            "acmestudio_tiktok_publish_status",
            "Checking TikTok publish status in Acmestudio",
            "Checked TikTok publish status in Acmestudio",
        ),
    ],
)
def test_an_mcp_tool_reads_as_its_own_name(name: str, doing: str, done: str) -> None:
    """The step is the tool's real name read aloud: its verb, what it acts on, and the service.
    A server that adds a tool needs no entry: the parser reads snake, kebab and CamelCase."""
    assert phrase(name, servers=SERVERS) == (doing, done)


def test_a_tool_of_an_undeclared_server_is_not_read_as_remote() -> None:
    assert phrase("paper_write_html") == ("Writing HTML", "Wrote HTML")
    assert services({"docs": "the handbook"}) == {"docs": "the handbook"}


def test_this_repos_host_tools_read_as_studio_work() -> None:
    assert phrase("start_task") == ("Putting a helper on it", "Put a helper on it")
    assert phrase("task") == ("Bringing in a helper", "Brought in a helper")
    assert phrase("steer_task")[1] == "Passed your notes on"
    assert phrase("start_render_job")[0] == "Starting the render"
    assert phrase("upload_files", {"paths": ["a.png", "b.png"]})[0] == "Sending the files over"
    assert phrase("upload_files", {"paths": ["a.png"]})[0] == "Sending it over"
    assert (
        phrase("look", {"paths": ["a.png", "b.png"], "question": "x"})[0]
        == "Looking over the frames"
    )
    assert phrase("ls", {"path": "/workspace/attachments"}) == (
        "Browsing your files",
        "Browsed your files",
    )


def test_tools_without_an_entry_read_as_their_own_name() -> None:
    assert phrase("generate_sound_effect") == ("Generating sound effect", "Generated sound effect")
    assert phrase("generate_music") == ("Generating music", "Generated music")
    assert phrase("some_new_thing") == ("Some new thing", "Some new thing")
    assert phrase("", None) == ("Working", "Working")


def test_no_phrase_carries_argument_text() -> None:
    """A card is posted before anyone reviews it: nothing a person or the model typed is in it."""
    secret = "quarterly-salary-review"
    calls = [
        ("read_file", {"file_path": f"/workspace/projects/{secret}/{secret}.png"}),
        ("write_file", {"file_path": f"/workspace/{secret}"}),
        ("grep", {"pattern": secret, "path": f"/workspace/{secret}"}),
        ("ls", {"path": f"/workspace/projects/{secret}"}),
        ("execute", {"command": f"python3 {secret}.py --note {secret}"}),
        ("paper_write_html", {"html": secret, "fileId": secret}),
        ("docs_search", {"query": secret}),
        ("steer_task", {"task_id": "t-1", "note": secret}),
    ]
    for name, args in calls:
        doing, done = phrase(name, args, servers=SERVERS)
        assert secret not in doing.lower().replace(" ", "-"), (name, doing)
        assert secret not in done.lower().replace(" ", "-"), (name, done)


def test_bad_arguments_never_break_a_card() -> None:
    assert phrase("read_file", {"file_path": None}) == (
        "Reading the workspace",
        "Read the workspace",
    )
    assert phrase("execute", "not a mapping") == ("Working in the sandbox", "Worked in the sandbox")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("status", "card"),
    [
        ("completed", "complete"),
        ("in_progress", "in_progress"),
        ("pending", "pending"),
        ("failed", "error"),
        (None, "pending"),
    ],
)
def test_todo_status_maps_to_card_status(status: str | None, card: str) -> None:
    assert todo_status(status) == card
