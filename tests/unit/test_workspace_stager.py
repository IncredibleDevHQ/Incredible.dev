"""Workspace manifest generation and the staging contract (fake sandbox target)."""

from __future__ import annotations

import gzip
import io
import shutil
import tarfile
from pathlib import Path
from typing import Any

import pytest
from deepagents.backends.protocol import ExecuteResponse

from design_agent.brand.schema import load_brand_pack
from design_agent.middleware.workspace import (
    MARKER,
    StagingError,
    WorkspaceStagerMiddleware,
    stage,
    staging_script,
)
from design_agent.workspace.manifest import ManifestError, build_manifest

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "examples/brands/example-studio"


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    (tmp_path / "skills/media-production/scripts").mkdir(parents=True)
    (tmp_path / "skills/media-production/SKILL.md").write_text("---\nname: media-production\n---\n")
    (tmp_path / "skills/media-production/scripts/run.mjs").write_text("console.log(1)\n")
    (tmp_path / "workspace/tools").mkdir(parents=True)
    (tmp_path / "workspace/tools/brand-lint.mjs").write_text("// gate\n")
    shutil.copytree(SAMPLE, tmp_path / "examples/brands/example-studio")
    shutil.copytree(ROOT / "fonts", tmp_path / "fonts")
    return tmp_path


def _manifest(root: Path):  # type: ignore[no-untyped-def]
    pack = load_brand_pack(root / "examples/brands/example-studio", project_root=root)
    return build_manifest(root, pack)


def test_manifest_stages_skills_tools_and_brand(checkout: Path) -> None:
    destinations = {str(a.destination) for a in _manifest(checkout).assets}
    assert "/workspace/skills/media-production/scripts/run.mjs" in destinations
    assert "/workspace/tools/brand-lint.mjs" in destinations
    assert "/workspace/brand/tokens.json" in destinations
    assert "/workspace/brand/logos/mark.svg" in destinations


def test_baked_open_fonts_are_not_uploaded_again(checkout: Path) -> None:
    """The sample brand's faces are open but not baked, so they are staged; nothing baked is."""
    from design_agent.workspace.manifest import BAKED_FONT_SHA256

    fonts = [
        a for a in _manifest(checkout).assets if str(a.destination).startswith("/workspace/fonts/")
    ]
    assert {a.destination.name for a in fonts} == {
        "Geist-Variable.ttf",
        "Geist-Italic-Variable.ttf",
        "FragmentMono-Regular.ttf",
        "FragmentMono-Italic.ttf",
    }
    assert not [a for a in fonts if a.sha256 in BAKED_FONT_SHA256]


def test_a_non_baked_brand_font_is_staged(checkout: Path) -> None:
    (checkout / "private-fonts").mkdir()
    font = checkout / "private-fonts/House-Regular.otf"
    font.write_bytes(b"OTTO-fake-font")
    import hashlib

    sha = hashlib.sha256(font.read_bytes()).hexdigest()
    fonts = checkout / "examples/brands/example-studio/fonts.toml"
    fonts.write_text(
        fonts.read_text()
        + f'\n[[fonts]]\nfamily = "Geist"\nweight = "400"\nfile = "private-fonts/House-Regular.otf"\nsha256 = "{sha}"\nrequired = true\nlicense = "commercial"\n'
    )
    staged = {str(a.destination) for a in _manifest(checkout).assets}
    assert "/workspace/fonts/House-Regular.otf" in staged


def test_env_files_are_refused(checkout: Path) -> None:
    (checkout / "workspace/tools/.env").write_text("SECRET=1\n")
    with pytest.raises(ManifestError, match="environment file"):
        _manifest(checkout)


def test_symlinks_leaving_the_checkout_are_refused(
    checkout: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    outside = tmp_path_factory.mktemp("outside") / "secret.txt"
    outside.write_text("nope")
    (checkout / "workspace/tools/link.txt").symlink_to(outside)
    with pytest.raises(ManifestError, match="symlink"):
        _manifest(checkout)


def test_digest_and_archive_are_deterministic(checkout: Path) -> None:
    first, second = _manifest(checkout), _manifest(checkout)
    assert first.digest == second.digest
    assert first.archive() == second.archive()
    with tarfile.open(fileobj=io.BytesIO(gzip.decompress(first.archive()))) as tar:
        names = tar.getnames()
        directories = [m.name for m in tar.getmembers() if m.isdir()]
    assert names[: len(directories)] == directories, "parent directories come first"
    assert all(not n.startswith("/") and ".." not in n.split("/") for n in names)


def test_digest_changes_when_a_staged_file_changes(checkout: Path) -> None:
    before = _manifest(checkout).digest
    (checkout / "workspace/tools/brand-lint.mjs").write_text("// gate v2\n")
    assert _manifest(checkout).digest != before


class FakeTarget:
    def __init__(self, marker: bytes | None = None, exit_code: int = 0) -> None:
        self.marker = marker
        self.exit_code = exit_code
        self.uploads: list[list[tuple[str, bytes]]] = []
        self.commands: list[str] = []

    def upload(self, files: list[tuple[str, bytes]]) -> None:
        self.uploads.append(files)

    def execute(self, command: str, *, timeout: int) -> ExecuteResponse:
        self.commands.append(command)
        return ExecuteResponse(output="", exit_code=self.exit_code)

    def read(self, path: str) -> bytes | None:
        assert path == MARKER
        return self.marker


def test_warm_sandbox_costs_one_marker_read(checkout: Path) -> None:
    manifest = _manifest(checkout)
    target = FakeTarget(marker=manifest.digest.encode())
    assert stage(target, manifest) is False
    assert target.uploads == [] and target.commands == []


def test_cold_sandbox_uploads_once_and_runs_one_script(checkout: Path) -> None:
    manifest = _manifest(checkout)
    target = FakeTarget()
    assert stage(target, manifest) is True
    assert len(target.uploads) == 1 and len(target.commands) == 1
    paths = [p for p, _ in target.uploads[0]]
    assert paths[0].startswith("/tmp/design-agent-stage-") and paths[1].startswith(
        "/tmp/design-agent-check-"
    )
    script = target.commands[0]
    assert "fc-match" in script and "Geist" in script and "'Fragment Mono'" in script
    assert MARKER in script


def test_failed_staging_names_the_phase(checkout: Path) -> None:
    with pytest.raises(StagingError, match="brand font"):
        stage(FakeTarget(exit_code=93), _manifest(checkout))


def test_script_clears_staged_roots_but_never_projects() -> None:
    script = staging_script(
        digest="d", archive_path="/tmp/a", check_path="/tmp/c", families=("Inter",)
    )
    first = script.splitlines()[1]
    assert first.startswith(
        "rm -rf /workspace/skills /workspace/tools /workspace/brand /workspace/fonts"
    )
    assert "/workspace/projects" not in script and "/workspace/attachments" not in script


def test_middleware_reports_failure_to_the_model_instead_of_ending_silently(checkout: Path) -> None:
    middleware = WorkspaceStagerMiddleware(
        _manifest(checkout), lambda _rt: FakeTarget(exit_code=92)
    )
    update: dict[str, Any] | None = middleware.before_agent({"messages": []}, runtime=None)  # type: ignore[arg-type]
    assert update is not None
    note = update["messages"][0].content
    assert "not ready" in note and "checksums" in note


def test_middleware_is_a_no_op_without_a_target(checkout: Path) -> None:
    middleware = WorkspaceStagerMiddleware(_manifest(checkout), lambda _rt: None)
    assert middleware.before_agent({"messages": []}, runtime=None) is None  # type: ignore[arg-type]
