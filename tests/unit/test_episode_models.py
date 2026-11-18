"""What each agent can be asked to run on: its models and the efforts each one takes."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from design_agent.config import Settings
from design_agent.surfaces.web import episode_models

KIMI_CONFIG = """
default_model = "kimi-code/k3.1-pro"

[providers."managed:kimi-code"]
type = "kimi"
api_key = "not-shown-anywhere"

[models."kimi-code/kimi-for-coding-highspeed"]
provider = "managed:kimi-code"
model = "kimi-for-coding-highspeed"
display_name = "K2.7 Code Highspeed"

[models."kimi-code/k3"]
provider = "managed:kimi-code"
model = "k3"
display_name = "K3"
support_efforts = ["low", "high", "max"]
default_effort = "max"

[models."kimi-code/k3.1-pro-highspeed"]
provider = "managed:kimi-code"
model = "k3.1-pro-highspeed"
display_name = "K3.1 Pro Highspeed"
support_efforts = ["low", "high", "max"]

[models."kimi-code/k3.1-pro"]
provider = "managed:kimi-code"
model = "k3.1-pro"
display_name = "K3.1 Pro"
support_efforts = ["max", "low", "high"]
default_effort = "high"

[thinking]
enabled = true
effort = "high"
"""


@pytest.fixture
def kimi_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "kimi-home"
    home.mkdir()
    (home / "config.toml").write_text(KIMI_CONFIG, encoding="utf8")
    monkeypatch.setattr(episode_models, "KIMI_HOME", home)
    return home


def settings() -> Settings:
    return Settings(_env_file=None)


def test_codex_names_its_configured_default_without_changing_the_pick(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(episode_models, "CODEX_HOME", tmp_path)
    path = tmp_path / "config.toml"
    path.write_text('model = "gpt-6.1-sol"\n', encoding="utf8")
    rows = episode_models.options(settings(), "codex")
    assert rows[0]["id"] == ""
    assert rows[0]["resolves"] == "gpt-6.1-sol"
    assert rows[0]["efforts"] == next(r["efforts"] for r in rows if r["id"] == "gpt-6.1-sol")
    assert episode_models.generation(settings(), "codex", {})["model"] == "gpt-6.1-sol"
    assert episode_models.generation(settings(), "codex", {"effort": "low"})["effort"] == "low"
    path.write_text('model = "gpt-6.2-sol"\n', encoding="utf8")
    assert episode_models.options(settings(), "codex")[0]["resolves"] == "gpt-6.2-sol"
    path.write_text("model = [broken", encoding="utf8")
    assert "resolves" not in episode_models.options(settings(), "codex")[0]


def test_kimi_offers_the_models_its_own_settings_list_newest_first(kimi_home: Path) -> None:
    rows = episode_models.options(settings(), "kimi")
    assert [r["name"] for r in rows] == [
        "CLI default",
        "K3.1 Pro",
        "K3.1 Pro Highspeed",
        "K3",
        "K2.7 Code Highspeed",
    ]
    by_id = {r["id"]: r for r in rows}
    # the alias its --model takes, and the efforts that model takes, in order of effort
    assert by_id["kimi-code/k3.1-pro"]["efforts"] == ["low", "high", "max"]
    assert by_id["kimi-code/kimi-for-coding-highspeed"]["efforts"] == []
    # Kimi's own effort where the model takes it; the first row says what the default is
    assert by_id["kimi-code/k3"]["default_effort"] == "high"
    assert by_id[""] == {
        "id": "",
        "name": "CLI default",
        "efforts": ["low", "high", "max"],
        "default_effort": "high",
        "resolves": "K3.1 Pro",
    }
    # nothing of the account is kept beside the names
    assert "not-shown-anywhere" not in repr(rows)
    assert all(set(r) <= {"id", "name", "efforts", "default_effort", "resolves"} for r in rows)


def test_a_picture_records_what_kimi_ran_on_and_refuses_what_it_does_not_offer(
    kimi_home: Path,
) -> None:
    s = settings()
    assert episode_models.generation(s, "kimi", {}) == {
        "provider": "Kimi Code",
        "model": "K3.1 Pro",
        "effort": "high",
    }
    assert episode_models.generation(s, "kimi", {"model": "kimi-code/k3", "effort": "low"}) == {
        "provider": "Kimi Code",
        "model": "K3",
        "effort": "low",
    }
    # a model that takes no effort says so by taking none
    fast = episode_models.generation(s, "kimi", {"model": "kimi-code/kimi-for-coding-highspeed"})
    assert fast["model"] == "K2.7 Code Highspeed" and fast["effort"] == "CLI default"
    for pick in (
        {"model": "kimi-code/k3", "effort": "medium"},
        {"model": "kimi-code/kimi-for-coding-highspeed", "effort": "low"},
        {"model": "kimi-code/k9"},
    ):
        with pytest.raises(ValueError, match="supported model and effort"):
            episode_models.generation(s, "kimi", pick)


def test_kimi_without_readable_settings_offers_its_default_alone(
    kimi_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    only_default = [{"id": "", "name": "CLI default", "efforts": []}]
    (kimi_home / "config.toml").write_text("default_model = [broken", encoding="utf8")
    assert episode_models.options(settings(), "kimi") == only_default
    (kimi_home / "config.toml").write_text('default_model = "x"\n', encoding="utf8")
    os.utime(kimi_home / "config.toml", ns=(1, 1))
    assert episode_models.options(settings(), "kimi") == only_default
    monkeypatch.setattr(episode_models, "KIMI_HOME", tmp_path / "nowhere")
    assert episode_models.options(settings(), "kimi") == only_default
    assert episode_models.generation(settings(), "kimi", {})["model"] == "CLI default"


def test_kimi_settings_changed_on_disk_are_read_again(kimi_home: Path) -> None:
    assert len(episode_models.options(settings(), "kimi")) == 5
    config = kimi_home / "config.toml"
    config.write_text(
        KIMI_CONFIG + '\n[models."kimi-code/k4"]\ndisplay_name = "K4"\n', encoding="utf8"
    )
    os.utime(config, ns=(2_000_000_000, 2_000_000_000))
    rows = episode_models.options(settings(), "kimi")
    assert [r["name"] for r in rows][:2] == ["CLI default", "K4"]
    # a caller's change to what it was handed never reaches the next caller
    rows[1]["name"] = "changed"
    assert episode_models.options(settings(), "kimi")[1]["name"] == "K4"


def test_claude_code_offers_its_models_by_name_with_the_efforts_its_cli_takes() -> None:
    rows = episode_models.options(settings(), "claude")
    assert [(r["id"], r["name"]) for r in rows] == [
        ("", "CLI default"),
        ("claude-fable-5-2", "Fable 5.2"),
        ("claude-opus-5-5", "Opus 5.5"),
        ("claude-sonnet-5-5", "Sonnet 5.5"),
        ("claude-haiku-5-5", "Haiku 5.5"),
    ]
    assert rows[0]["efforts"] == rows[1]["efforts"] == ["low", "medium", "high", "xhigh", "max"]
    assert rows[-1]["efforts"] == []
    picked = episode_models.generation(
        settings(), "claude", {"model": "claude-fable-5-2", "effort": "xhigh"}
    )
    assert picked == {"provider": "Anthropic", "model": "Fable 5.2", "effort": "xhigh"}
    # an effort alone holds for whatever model the CLI starts on
    assert episode_models.generation(settings(), "claude", {"effort": "low"})["effort"] == "low"
    with pytest.raises(ValueError):
        episode_models.generation(
            settings(), "claude", {"model": "claude-haiku-5-5", "effort": "low"}
        )


def test_a_reported_model_is_named_as_it_is_offered() -> None:
    assert episode_models.named("claude", "claude-opus-5-5") == "Opus 5.5"
    assert episode_models.named("claude", "claude-fable-5-2[1m]") == "Fable 5.2"
    assert episode_models.named("claude", "claude-next") == "claude-next"
    assert episode_models.named("codex", "gpt-6.1-sol") == "gpt-6.1-sol"
