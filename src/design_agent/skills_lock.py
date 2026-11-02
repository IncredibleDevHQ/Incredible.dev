"""Vendored upstream skills: the lock, verification and the vendoring sync.

Skills for the deployed agent keep their upstream names at `skills/<name>/` (MDA discovers skills
one level deep); skills for coding agents sit at `.agents/skills/<name>/`. Both are byte-identical
to their upstream at its pinned commit. `skills-lock.json` records each upstream's repository,
commit and license, every vendored file's sha256 under `skills` (runtime) or `agent_skills`
(coding agents), and files deliberately left out with the reason. MDA syncs `skills/` to Context
Hub, which takes only UTF-8 text, so a runtime skill's binary files (fonts, images) are vendored to
`skill-binaries/<name>/` instead and listed under `binaries`; the workspace stager puts them back
beside the skill in the sandbox, and a plain `mda deploy` works. CI fails if a vendored file
differs, an unlisted file appears, or an excluded file is present. Local routing and guidance live
in our own sibling skills and summaries, never as edits.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from design_agent.workspace.manifest import SKILL_BINARIES


@dataclass(frozen=True)
class Upstream:
    repo: str
    commit: str
    release: str | None
    """The release tag the commit belongs to; None when the upstream pins a branch commit."""
    license: str
    license_file: str
    source: str
    """The folder in the upstream repository that holds its skills."""
    runtime: tuple[str, ...] = ()
    """Skills for the deployed agent, vendored into `skills/`."""
    coding: tuple[str, ...] = ()
    """Skills for coding agents, vendored into `.agents/skills/`."""


#: Where each section of the lock vendors to.
ROOTS = {"skills": "skills", "agent_skills": ".agents/skills"}

UPSTREAMS: dict[str, Upstream] = {
    # Left out: figma (needs a Figma connection), hyperframes-studio (the desktop app),
    # product-launch-video (overlaps the launch_film pipeline's routing), talking-head-recut
    # (MIT-derived; not in the v0.1 skill set).
    "hyperframes": Upstream(
        repo="heygen-com/hyperframes",
        commit="7735338b49ed6e11c227b0710da3bd35c3366b9c",
        release="v0.8.169",
        license="Apache-2.0",
        license_file="licenses/hyperframes-LICENSE.txt",
        source="skills",
        runtime=(
            "hyperframes",
            "hyperframes-core",
            "hyperframes-cli",
            "hyperframes-animation",
            "hyperframes-creative",
            "hyperframes-audio",
            "hyperframes-keyframes",
            "hyperframes-registry",
            "media-use",
            "slideshow",
            "pr-to-video",
            "music-to-video",
            "embedded-captions",
            "faceless-explainer",
            "general-video",
            "motion-graphics",
            "remotion-to-hyperframes",
        ),
    ),
    # LangChain's skill packs publish from `main`; their v0.1.0 tags predate most of the skills.
    # Left out: LangChain, LangGraph, eval-engineering, swarm, custom apps and online evals, which
    # cover building other agents rather than running or changing this one.
    "langsmith-skills": Upstream(
        repo="langchain-ai/langsmith-skills",
        commit="1fb52e836f2d9f8d95c9f0b27d796ab20dac34d1",
        release=None,
        license="MIT",
        license_file="licenses/langsmith-skills-LICENSE.txt",
        source="config/skills",
        runtime=("langsmith-trace",),
        coding=("langsmith-dataset", "langsmith-evaluator"),
    ),
    "langchain-skills": Upstream(
        repo="langchain-ai/langchain-skills",
        commit="16a992f09ab3ccfb642dd4f08d350d833d1990bf",
        release=None,
        license="MIT",
        license_file="licenses/langchain-skills-LICENSE.txt",
        source="config/skills",
        coding=(
            "deep-agents-core",
            "deep-agents-memory",
            "deep-agents-orchestration",
            "managed-deep-agents",
        ),
    ),
}

#: Upstream files not vendored, with the reason. Third-party assets whose license is not
#: recorded beside them stay out until the partner confirms terms.
EXCLUDED: tuple[tuple[str, str], ...] = (
    ("*/gsap*.js", "vendored GSAP: the sandbox installs GSAP; compositions copy it from there"),
    (
        "media-use/audio/assets/sfx/*.mp3",
        "Pixabay Content License audio, pending partner and legal review",
    ),
    (
        "embedded-captions/modes/standard/fonts/files/*",
        "font binaries without license text beside them",
    ),
    (
        "embedded-captions/modes/standard/fonts/fonts.css",
        "inlines the excluded font binaries as base64",
    ),
    ("embedded-captions/assets/strokefonts/*", "assets without recorded provenance"),
    # fnmatch's `*` crosses `/`, so this covers every depth under a template's assets.
    (
        "music-to-video/references/templates/*/assets/*",
        "template assets without recorded provenance",
    ),
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def exclusion_reason(relative: str) -> str | None:
    """Why `relative` (``<skill>/<path>``) is not vendored, or None when it is."""
    for pattern, reason in EXCLUDED:
        if fnmatch.fnmatchcase(relative, pattern):
            return reason
    return None


def load_lock(root: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((root / "skills-lock.json").read_text())
    return data


def vendored_folders(lock: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    """Every vendored skill as (its folder relative to the repository root, its lock entry)."""
    for section, base in ROOTS.items():
        for name, entry in sorted(lock.get(section, {}).items()):
            yield f"{base}/{name}", entry


def locked_files(folder: str, entry: dict[str, Any]) -> dict[str, str]:
    """Every file of one vendored skill, as repository-relative path to sha256."""
    name = folder.rsplit("/", 1)[-1]
    return {
        **{f"{folder}/{relative}": digest for relative, digest in entry["files"].items()},
        **{
            f"{SKILL_BINARIES}/{name}/{relative}": digest
            for relative, digest in entry.get("binaries", {}).items()
        },
    }


def is_text(path: Path) -> bool:
    try:
        path.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


@dataclass(frozen=True)
class VerifyResult:
    problems: tuple[str, ...]
    files: int

    @property
    def ok(self) -> bool:
        return not self.problems


def verify(root: Path) -> VerifyResult:
    """Every vendored file matches the lock; nothing extra; nothing excluded is present."""
    lock = load_lock(root)
    upstreams: dict[str, dict[str, Any]] = lock["upstreams"]
    problems: list[str] = []
    count = 0
    for upstream in upstreams.values():
        if not (root / upstream["license_file"]).is_file():
            problems.append(f"missing upstream license {upstream['license_file']}")
    for relative_folder, entry in vendored_folders(lock):
        if not (root / relative_folder).is_dir():
            problems.append(f"{relative_folder}: missing")
            continue
        commit = upstreams[entry["upstream"]]["commit"][:12]
        expected = locked_files(relative_folder, entry)
        name = relative_folder.rsplit("/", 1)[-1]
        homes = [root / relative_folder]
        if entry.get("binaries") or (root / SKILL_BINARIES / name).is_dir():
            homes.append(root / SKILL_BINARIES / name)
        present = {
            p.relative_to(root).as_posix()
            for home in homes
            if home.is_dir()
            for p in home.rglob("*")
            if p.is_file()
        }
        for path in sorted(present - expected.keys()):
            problems.append(f"{path}: not in skills-lock.json")
        for path, digest in sorted(expected.items()):
            if not (root / path).is_file():
                problems.append(f"{path}: missing")
            elif sha256(root / path) != digest:
                problems.append(f"{path}: differs from upstream {commit}")
            count += 1
        for relative in entry.get("excluded", {}):
            if (root / relative_folder / relative).exists():
                problems.append(f"{relative_folder}/{relative}: excluded file is present")
    return VerifyResult(problems=tuple(problems), files=count)


def fetch_upstream(upstream: Upstream, destination: Path) -> Path:
    """Sparse-checkout the upstream's skills folder and LICENSE at its commit into `destination`."""
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git is required to vendor upstream skills")
    url = f"https://github.com/{upstream.repo}.git"
    for args in (
        ["clone", "--filter=blob:none", "--no-checkout", "--sparse", url, str(destination)],
        ["-C", str(destination), "sparse-checkout", "set", "--no-cone"]
        + [f"/{upstream.source}/", "/LICENSE"],
        ["-C", str(destination), "checkout", "--quiet", upstream.commit],
    ):
        subprocess.run([git, *args], check=True, capture_output=True)  # noqa: S603 - fixed argv
    return destination


def _vendor(
    source: Path, target: Path, name: str, binaries: Path | None = None
) -> dict[str, dict[str, str]]:
    """Copy one upstream skill folder unmodified, minus excluded files; its lock entry. With
    `binaries`, files that are not UTF-8 text go there instead of into the skill folder."""
    shutil.rmtree(target, ignore_errors=True)
    if binaries is not None:
        shutil.rmtree(binaries, ignore_errors=True)
    files: dict[str, str] = {}
    moved: dict[str, str] = {}
    excluded: dict[str, str] = {}
    for path in sorted(p for p in source.rglob("*") if p.is_file()):
        relative = path.relative_to(source).as_posix()
        if reason := exclusion_reason(f"{name}/{relative}"):
            excluded[relative] = reason
            continue
        home, listed = (
            (binaries, moved) if binaries is not None and not is_text(path) else (target, files)
        )
        destination = home / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
        listed[relative] = sha256(destination)
    entry = {"files": files, "excluded": excluded}
    if moved:
        entry["binaries"] = moved
    return entry


def sync(
    root: Path, *, only: str | None = None, commit: str | None = None, release: str | None = None
) -> dict[str, Any]:
    """Re-vendor upstream skills unmodified at their pins and rewrite skills-lock.json.

    `only` re-vendors one upstream, at `commit` (and `release`) when given, and keeps every other
    upstream's lock entries as they are.
    """
    if only is not None and only not in UPSTREAMS:
        raise ValueError(f"unknown upstream {only!r}; known: {', '.join(UPSTREAMS)}")
    if only is None and (commit or release):
        raise ValueError("a commit or release override needs one upstream")
    current = load_lock(root) if only is not None else None
    lock: dict[str, Any] = {"version": 2, "upstreams": {}, **{section: {} for section in ROOTS}}
    with tempfile.TemporaryDirectory() as scratch:
        for key, pin in UPSTREAMS.items():
            if current is not None and key != only:
                lock["upstreams"][key] = current["upstreams"][key]
                for section in ROOTS:
                    lock[section].update(
                        (name, entry)
                        for name, entry in current.get(section, {}).items()
                        if entry["upstream"] == key
                    )
                continue
            if key == only:
                pin = replace(
                    pin, commit=commit or pin.commit, release=release if commit else pin.release
                )
            checkout = fetch_upstream(pin, Path(scratch) / key)
            lock["upstreams"][key] = {
                "repo": pin.repo,
                "commit": pin.commit,
                "release": pin.release,
                "license": pin.license,
                "license_file": pin.license_file,
            }
            (root / pin.license_file).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(checkout / "LICENSE", root / pin.license_file)
            for section, names in (("skills", pin.runtime), ("agent_skills", pin.coding)):
                for name in names:
                    source = checkout / pin.source / name
                    if not source.is_dir():
                        raise RuntimeError(
                            f"{pin.repo} {pin.commit[:12]} has no {pin.source}/{name}"
                        )
                    binaries = root / SKILL_BINARIES / name if section == "skills" else None
                    entry = _vendor(source, root / ROOTS[section] / name, name, binaries)
                    lock[section][name] = {"upstream": key, **entry}
    (root / "skills-lock.json").write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n")
    return lock
