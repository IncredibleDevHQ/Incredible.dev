from pathlib import Path
from runpy import run_path

import pytest

SETUP = run_path(str(Path(__file__).resolve().parents[2] / "scripts/setup_minio.py"))["setup"]


def test_credentials_are_private_separate_and_never_printed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    SETUP(tmp_path)
    root, app = tmp_path / ".env.minio", tmp_path / ".env.storage"
    assert root.stat().st_mode & 0o777 == 0o600
    assert app.stat().st_mode & 0o777 == 0o600
    assert "MINIO_ROOT_" not in app.read_text()
    admin_secret = root.read_text().split("MINIO_ROOT_PASSWORD=", 1)[1].strip()
    app_secret = app.read_text().split("DESIGN_AGENT_S3_SECRET_KEY=", 1)[1].strip()
    output = capsys.readouterr().out
    assert admin_secret != app_secret
    assert not any(value in output for value in (admin_secret, app_secret))


def test_existing_pair_is_preserved(tmp_path: Path) -> None:
    SETUP(tmp_path)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    SETUP(tmp_path)
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}


def test_incomplete_pair_is_not_overwritten(tmp_path: Path) -> None:
    (tmp_path / ".env.minio").write_text("existing")
    with pytest.raises(SystemExit, match="restore the matching file"):
        SETUP(tmp_path)
    assert (tmp_path / ".env.minio").read_text() == "existing"
    assert not (tmp_path / ".env.storage").exists()
