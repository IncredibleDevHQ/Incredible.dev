"""Ban-list scan: nothing private, licensed or third-party reaches the public tree.

Reviewed at every release. Pattern hits name the category, never echo a private value back.
Internal people and their chat ids are checked by hash so this file never lists them.

`DESIGN_AGENT_RELEASE_CHECK=1` removes the pre-release exemptions and also requires the internal
build notes to be gone (SPEC §17, §24).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

import pytest

from design_agent.skills_lock import locked_files, vendored_folders

ROOT = Path(__file__).resolve().parents[2]
RELEASE = os.environ.get("DESIGN_AGENT_RELEASE_CHECK") == "1"

#: Internal build material, deleted before the repository goes public.
PRE_RELEASE_PATHS = (
    "docs/prep/*",
    "IMPLEMENTATION_PROMPT.md",
    "scripts/import_from_reference.py",
)


@dataclass(frozen=True)
class Rule:
    category: str
    pattern: re.Pattern[str]
    allowed: tuple[str, ...] = ()


def _rule(category: str, pattern: str, *allowed: str) -> Rule:
    return Rule(category, re.compile(pattern), allowed)


#: Mentions of a licensed font, a third-party asset or a component library are allowed in the
#: binding spec documents, which explain why they are excluded. Their files never are.
SPEC_DOCS = ("AGENTS.md", "docs/*.md", "docs/**/*.md")

RULES: tuple[Rule, ...] = (
    _rule(
        "public agent name outside its presentation",
        r"(?i)content[\s_-]?studio",
        "AGENTS.md",
        "NOTICE.md",
        "README.md",
        "docs/assets/readme/*",
        "src/design_agent/config.py",
        ".env.example",
    ),
    _rule("internal repository", r"(?i)langchain[-_]media"),
    _rule(
        "company brand asset",
        r"(?i)langchain[-_](?:tokens|logo|mark|wordmark|brand)|--lc-[a-z]|\blc-(?:wordmark|tokens)",
    ),
    _rule("company email", r"(?i)@langchain\.(?:dev|com)\b"),
    _rule(
        "LangSmith workspace or deployment URL",
        r"(?i)smith\.langchain\.com/o/[0-9a-f]{8}-|[a-z0-9-]+\.langgraph\.app\b",
    ),
    _rule("internal snapshot name", r"(?i)media-hyperframes-v\d"),
    _rule("licensed font file", r"(?i)(?:twk-?lausanne|aeonik-?mono)[\w-]*\.(?:woff2?|ttf|otf)"),
    _rule("licensed font", r"(?i)twk\s?lausanne|aeonik", *SPEC_DOCS),
    _rule("unlicensed component library", r"(?i)\bremocn\b", *SPEC_DOCS),
    _rule("non-commercial asset", r"(?i)\bcyberpunk\b|\bcdpr\b", *SPEC_DOCS),
)

#: sha256(lowercase full name or chat user id)[:24] for people on the internal roster.
PRIVATE_IDENTITY_HASHES = frozenset(
    """
    02d6a3212390ee3168af6915 077eab4db96093e504345094 07d525b65a95319f575a2eaa
    0ba157ee9537d4d9df07235f 0e02c2b3bd1f36b7ea3e06ed 10dd2f8b673b124df08e73af
    136a1bd68fa3474e2589f553 1751524cb372b452917bd655 20e5eadbef4386c2171e1504
    23ab6d0ed0ac26f9eb44b2fe 29d23033345a3fc002de3742 2a21f6070c4e2c46ef1cfdcd
    2be5c5ecbbce3823da6f567f 31c6edb63f1d779dee1d0855 3d8a6345116abbf4ee1e9cfa
    4002f18f7742ee5da083578d 41099576e866b89af1fd3c94 41bd17739ee692fa5606b5a1
    4487ef4d7222b3db7551887c 4bc50e8f5bc5d2c779a8418c 545207302037676745a8e075
    56f61520e5944d31e16db45f 58c8d1e0f4063707afc14548 596a74b889e7f22cb59269a4
    5f944d5609525f2fb4a91e34 672a0aa922c2f46abb76d0ff 6d267df0ff4bcb5fb8fcafa6
    706c8b82e33a322d8e4b0d93 71417e55184c56999f468ef0 7425eb9672ba14a4b71a1393
    75507455489df1ccb6fc0088 7559c932efc06cf6106d31eb 77b9f3329fc043e72893e1ec
    77be5b1649d61d777161c526 781be53fe1260d19d4c3ee68 7cafdd283b0fb6d7650eff5f
    7de4a84914fed95d0cb5ac37 82b425954283c059a2b717ae 883b46c1034952664238039f
    8852bfd1fb946f46eca76c1b 89e79acc3009bc8e99aaad86 8a2d3816d9fa634a27c5739d
    930eed3109b135417c050f2e 9c773dbb2565f251486ecca6 9de5a5da70954df3853127e7
    a5aeb585a1ee08ee542fded2 a7762e4f4e9e2746c52d0e08 a95d5b679968f92af817abce
    ac32c709051427f95d5627af aeaba7f60bf44ca54fdb4781 aed54f27a1ac0f96d4655ca6
    b4095c1e7fda156eab0f0678 bc3b7c0c24ada2b987e25a02 bee01eb08e963998865c5a04
    c1e0a7792df994a16aa2c0f4 c3fedf814f9348121509bf18 c45fd361b55b6df22dd05a1b
    c7a3826b1f3b4ae0017c79ba caa29a363bb091c6a708ffdd cc214ecd7f10840d274f9775
    d2787f42ef2852d752d685cc d5204d7c4b1ffd31a381dd28 d5e204222c4310be4c9ac97b
    d5e956f55211671ccb039150 d72b457b0918e5e9e6e4df71 d72f38960a1ba25a0f764ec6
    d81f8bb0b55618b55e4def5a dcc7c593b96db31d22c548f2 de5c45b2b55d4c51888c23cc
    dfe1bf5b095873fd4d32b2ba e12548fed94dc1f98a4da282 e3d522f110dbf33899b044ad
    ec1fca9d3538ed16c18e6fb8 f3b66be567fb15f3a1f2a567 f4b60f6f2634d4c4f1b79446
    f888703d9b14ac8a73ff2204 f9f63a878e72df9d657a04a0 fb255d9e25b4d1f6e32a26ec
    """.split()
)

#: A chat-platform id that looks real: a type letter, then base-32 characters with digits in them.
SLACK_ID = re.compile(r"\b[UCGTWB][0-9A-Z]{8,11}\b")
SYNTHETIC_ID = re.compile(r"TEST|FAKE|EXAMPLE|SAMPLE|X{4}|0{6}")
WORD = re.compile(r"[a-z]+")

MEDIA_EXTENSIONS = frozenset(
    {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v", ".mp3", ".wav", ".m4a", ".aac", ".flac"}
)
FONT_EXTENSIONS = frozenset({".ttf", ".otf", ".woff", ".woff2"})
TEXT_LIMIT_BYTES = 2_000_000


def _matches(path: str, globs: tuple[str, ...]) -> bool:
    return any(fnmatch(path, glob) for glob in globs)


def _exempt(path: str) -> bool:
    return not RELEASE and _matches(path, PRE_RELEASE_PATHS)


def tracked_files() -> list[str]:
    """Files Git would publish: tracked plus untracked-but-not-ignored."""
    output = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout.decode()
    return sorted({p for p in output.split("\0") if p and (ROOT / p).is_file()})


def vendored_files() -> frozenset[str]:
    """Files covered by skills-lock.json, whose licenses are reviewed upstream."""
    lock_path = ROOT / "skills-lock.json"
    if not lock_path.is_file():
        return frozenset()
    return frozenset(
        path
        for folder, entry in vendored_folders(json.loads(lock_path.read_text()))
        for path in locked_files(folder, entry)
    )


def _text(path: str) -> str | None:
    full = ROOT / path
    if full.stat().st_size > TEXT_LIMIT_BYTES:
        return None
    data = full.read_bytes()
    if b"\0" in data[:8192]:
        return None
    return data.decode("utf-8", errors="replace")


def _identity_hits(text: str) -> Iterator[str]:
    words = WORD.findall(text.lower())
    for first, second in zip(words, words[1:], strict=False):
        if hashlib.sha256(f"{first} {second}".encode()).hexdigest()[:24] in PRIVATE_IDENTITY_HASHES:
            yield "internal person's name"
    for found in SLACK_ID.findall(text):
        digest = hashlib.sha256(found.lower().encode()).hexdigest()[:24]
        if digest in PRIVATE_IDENTITY_HASHES:
            yield "internal chat user id"
        elif sum(c.isdigit() for c in found) >= 2 and not SYNTHETIC_ID.search(found):
            yield f"chat platform id {found[0]}…"


def scan(paths: list[str]) -> list[str]:
    """Findings as `path:line: category` strings."""
    findings: list[str] = []
    vendored = vendored_files()
    for path in paths:
        if _exempt(path):
            continue
        suffix = Path(path).suffix.lower()
        if suffix in FONT_EXTENSIONS and not path.startswith("fonts/") and path not in vendored:
            findings.append(f"{path}: font binary outside fonts/")
        if path.startswith(("workspace/references/", "examples/")) and suffix in MEDIA_EXTENSIONS:
            findings.append(f"{path}: third-party media under {path.split('/')[0]}/")
        if path.startswith("workspace/references/") and Path(path).name != "README.md":
            findings.append(f"{path}: reference material is Git-ignored")
        if re.search(r"(?i)(?:^|/)gsap(?:[.-][\w.-]*)?\.js$", path) and path not in vendored:
            findings.append(f"{path}: vendored GSAP (install it in the sandbox instead)")
        if path in vendored:
            continue
        text = _text(path)
        if text is None or path == "tests/unit/test_public_hygiene.py":
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            for rule in RULES:
                if rule.pattern.search(line) and not _matches(path, rule.allowed):
                    findings.append(f"{path}:{number}: {rule.category}")
            findings.extend(f"{path}:{number}: {hit}" for hit in _identity_hits(line))
    return findings


def test_public_tree_has_no_banned_identifiers() -> None:
    findings = scan(tracked_files())
    assert not findings, "banned content in the public tree:\n" + "\n".join(findings)


@pytest.mark.skipif(not RELEASE, reason="release check only")
def test_internal_build_notes_are_gone() -> None:
    present = [p for p in tracked_files() if _matches(p, PRE_RELEASE_PATHS)]
    assert not present, f"delete internal build material before release: {present}"


@pytest.mark.parametrize(
    ("line", "category"),
    [
        (
            "Ported from the internal Content Studio agent",
            "public agent name outside its presentation",
        ),
        ("color: var(--lc-ink);", "company brand asset"),
        ("mail the team at ops@langchain.dev", "company email"),
        ("https://my-agent-1234.us.langgraph.app/threads", "LangSmith workspace or deployment URL"),
        ("snapshot_name='media-hyperframes-v10'", "internal snapshot name"),
        ("src: url(TWKLausanne-250.woff2)", "licensed font file"),
    ],
)
def test_rules_catch_known_leaks(line: str, category: str, tmp_path: Path) -> None:
    hits = [rule.category for rule in RULES if rule.pattern.search(line)]
    assert category in hits


def test_chat_ids_need_digits_and_are_not_synthetic() -> None:
    assert list(_identity_hits("posted in C07ABCD1234 by U0TESTUSER1")) == ["chat platform id C…"]
    assert list(_identity_hits("CONTRIBUTING and BACKGROUND are words")) == []
