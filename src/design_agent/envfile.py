"""Read and write the project `.env` safely: known keys only, values masked, file mode 0600.

The keys and their one-line descriptions come from `.env.example`, so the documentation and the
allowlist cannot drift apart. A value is never printed: secrets show as set or unset, plain
settings show their value. `design-agent config show|set|generate` and the onboarding skills use
these functions; nothing here talks to the network.
"""

from __future__ import annotations

import os
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

_LINE = re.compile(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=(.*)$")
_SECRET = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD)$|^DATABASE_URL$|_TOKENS$")
#: Keys `generate` may fill with a random value, and how.
GENERATED = {
    "DESIGN_AGENT_API_TOKENS": lambda: f"{secrets.token_urlsafe(32)}:me",
    "PAPER_BRIDGE_TOKEN": lambda: secrets.token_urlsafe(48),
    "POSTGRES_PASSWORD": lambda: secrets.token_urlsafe(24),
}


class EnvFileError(ValueError):
    """A key is unknown or a value cannot be written safely."""


@dataclass(frozen=True)
class EnvKey:
    name: str
    description: str
    group: str

    @property
    def secret(self) -> bool:
        return bool(_SECRET.search(self.name))


def known_keys(root: Path) -> dict[str, EnvKey]:
    """Every key `.env.example` documents, with its inline comment and section."""
    keys: dict[str, EnvKey] = {}
    group = "general"
    for line in (root / ".env.example").read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("#") and not _LINE.match(stripped.lstrip("# ")):
            group = stripped.lstrip("# ").split("(")[0].strip().lower() or group
            continue
        match = _LINE.match(stripped)
        if match:
            value = match.group(2)
            description = value.split("#", 1)[1].strip() if " #" in value else ""
            keys[match.group(1)] = EnvKey(match.group(1), description, group)
    return keys


def _unquote(raw: str) -> str:
    # As python-dotenv reads it: a `#` after whitespace starts a comment, even with no value before.
    if raw[:1].isspace() and raw.lstrip().startswith("#"):
        return ""
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        return raw[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return raw.split(" #", 1)[0].strip()


def _quote(value: str) -> str:
    if any(c in value for c in " #\"'\\"):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value


def read_env(root: Path) -> dict[str, str]:
    path = root / ".env"
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _LINE.match(line)
        if match:
            values[match.group(1)] = _unquote(match.group(2))
    return values


def view(root: Path) -> list[dict[str, str | bool]]:
    """Each known key: its group, whether it is set, and its value unless it is a secret."""
    values = read_env(root)
    rows: list[dict[str, str | bool]] = []
    for key in known_keys(root).values():
        value = values.get(key.name, "")
        rows.append(
            {
                "name": key.name,
                "group": key.group,
                "set": bool(value),
                "value": ("set" if value else "") if key.secret else value,
                "secret": key.secret,
                "description": key.description,
            }
        )
    return rows


def write_env(root: Path, updates: Mapping[str, str]) -> list[str]:
    """Set keys in `.env` (creating it 0600), keeping every other line as it was."""
    known = known_keys(root)
    for name, value in updates.items():
        if name not in known:
            raise EnvFileError(f"{name} is not a setting this project documents in .env.example")
        if "\n" in value or "\r" in value or "\x00" in value:
            raise EnvFileError(f"{name}: values are one line")
    path = root / ".env"
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    remaining = dict(updates)
    out: list[str] = []
    for line in lines:
        match = _LINE.match(line)
        if match and match.group(1) in remaining:
            name = match.group(1)
            out.append(f"{name}={_quote(remaining.pop(name))}")
        else:
            out.append(line)
    out += [f"{name}={_quote(value)}" for name, value in remaining.items()]
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write("\n".join(out) + "\n")
    path.chmod(0o600)
    return sorted(updates)


def generate(root: Path, names: list[str]) -> list[str]:
    """Fill keys that hold a random secret (tokens, passwords); never overwrites one that is set."""
    current = read_env(root)
    updates = {}
    for name in names:
        if name not in GENERATED:
            raise EnvFileError(f"{name} is not generated; set it with `config set`")
        if not current.get(name):
            updates[name] = GENERATED[name]()
    return write_env(root, updates) if updates else []
