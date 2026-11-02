"""`design-agent config`: known keys only, secrets never shown, other lines kept, mode 0600."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

from design_agent.envfile import EnvFileError, generate, known_keys, read_env, view, write_env

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def project(tmp_path: Path) -> Path:
    shutil.copy(ROOT / ".env.example", tmp_path / ".env.example")
    return tmp_path


def test_every_setting_the_code_reads_is_documented() -> None:
    from design_agent.config import Settings

    documented = set(known_keys(ROOT))
    for name, field in Settings.model_fields.items():
        alias = field.validation_alias if isinstance(field.validation_alias, str) else None
        env = alias or f"DESIGN_AGENT_{name.upper()}"
        if name in {"live_tests", "runtime"} or env in {"DESIGN_AGENT_PROJECT_ROOT"}:
            continue
        aliases = getattr(field.validation_alias, "choices", None) or [env]
        assert any(str(a) in documented for a in aliases), f"{name} is not in .env.example"


def test_set_keeps_other_lines_masks_secrets_and_is_private(project: Path) -> None:
    (project / ".env").write_text("# mine\nUNRELATED=keep\nANTHROPIC_API_KEY=old\n")
    write_env(
        project, {"ANTHROPIC_API_KEY": "sk-new", "DESIGN_AGENT_MODEL": "anthropic:claude-opus-5-5"}
    )
    text = (project / ".env").read_text()
    assert text.startswith("# mine\nUNRELATED=keep\nANTHROPIC_API_KEY=sk-new\n")
    assert read_env(project)["DESIGN_AGENT_MODEL"] == "anthropic:claude-opus-5-5"
    if sys.platform != "win32":
        assert (project / ".env").stat().st_mode & 0o077 == 0
    rows = {row["name"]: row for row in view(project)}
    assert rows["ANTHROPIC_API_KEY"]["value"] == "set" and rows["ANTHROPIC_API_KEY"]["secret"]
    assert rows["DESIGN_AGENT_MODEL"]["value"] == "anthropic:claude-opus-5-5"
    assert "sk-new" not in str(view(project))


def test_unknown_keys_and_multiline_values_are_refused(project: Path) -> None:
    with pytest.raises(EnvFileError, match="not a setting"):
        write_env(project, {"SOMETHING_ELSE": "x"})
    with pytest.raises(EnvFileError, match="one line"):
        write_env(project, {"DESIGN_AGENT_MODEL": "a\nEVIL=1"})


def test_generate_fills_secrets_once(project: Path) -> None:
    assert generate(project, ["PAPER_BRIDGE_TOKEN"]) == ["PAPER_BRIDGE_TOKEN"]
    first = read_env(project)["PAPER_BRIDGE_TOKEN"]
    assert len(first) >= 32 and generate(project, ["PAPER_BRIDGE_TOKEN"]) == []
    assert read_env(project)["PAPER_BRIDGE_TOKEN"] == first


def test_a_comment_after_an_empty_value_is_not_the_value(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("A=            # what A is for\nB=#hex\nC=v # note\n")
    assert read_env(tmp_path) == {"A": "", "B": "#hex", "C": "v"}
