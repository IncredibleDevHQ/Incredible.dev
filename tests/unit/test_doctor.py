"""`doctor`'s MDA deploy check: what would make a plain `mda deploy` fail or ship the wrong thing."""

from __future__ import annotations

import shutil
from pathlib import Path

from design_agent.doctor import _check_mda_deploy

ROOT = Path(__file__).resolve().parents[2]


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    for name in ("skills", "skill-binaries", "licenses"):
        shutil.copytree(ROOT / name, root / name, symlinks=True)
    shutil.copytree(ROOT / ".agents", root / ".agents", symlinks=True)
    shutil.copy(ROOT / "skills-lock.json", root / "skills-lock.json")
    return root


def test_this_checkout_is_ready_for_a_plain_mda_deploy(tmp_path: Path) -> None:
    check = _check_mda_deploy(_project(tmp_path))
    assert check.status == "ok", check.detail


def test_a_binary_file_in_skills_fails_the_check(tmp_path: Path) -> None:
    root = _project(tmp_path)
    (root / "skills" / "stills" / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfe")
    check = _check_mda_deploy(root)
    assert check.status == "fail"
    assert "skills/stills/logo.png" in check.detail and "skill-binaries/" in check.detail


def test_self_hosting_keys_in_env_are_named_never_printed(tmp_path: Path) -> None:
    root = _project(tmp_path)
    (root / ".env").write_text(
        "ANTHROPIC_API_KEY=sk-ant-secret\nSLACK_APP_TOKEN=xapp-secret\nDATABASE_URL=\n"
    )
    check = _check_mda_deploy(root)
    assert check.status == "warn"
    assert "SLACK_APP_TOKEN" in check.detail and "DATABASE_URL" not in check.detail
    assert "secret" not in check.detail.replace("deployment secrets", "")
