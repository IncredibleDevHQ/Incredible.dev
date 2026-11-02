"""Embed sandbox/render/{package.json,package-lock.json} into sandbox/setup.sh.

The bake runs setup.sh without the repository, so the pinned render toolchain travels inside the
script as a deterministic gzip'd tar. Run after changing anything in sandbox/render/; the unit
suite fails while the embedded copy is stale.

    uv run python scripts/sync_sandbox_recipe.py [--check]
"""

from __future__ import annotations

import argparse
import base64
import gzip
import io
import re
import sys
import tarfile
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "sandbox" / "setup.sh"
RENDER = ROOT / "sandbox" / "render"
FILES = ("package.json", "package-lock.json")
BLOCK = re.compile(
    r"(# >>> render-lock[^\n]*\n)RENDER_LOCK_B64='[^']*'\n(# <<< render-lock)", re.MULTILINE
)


def render_lock_archive(render_dir: Path = RENDER) -> str:
    """The lock files as a base64 gzip'd tar with fixed metadata, wrapped at 100 columns."""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        for name in FILES:
            data = (render_dir / name).read_bytes()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o644
            info.mtime = 0
            tar.addfile(info, io.BytesIO(data))
    packed = gzip.compress(raw.getvalue(), compresslevel=9, mtime=0)
    return "\n".join(textwrap.wrap(base64.b64encode(packed).decode("ascii"), 100))


def embedded(setup_text: str, archive: str) -> str:
    """`setup_text` with the render-lock block holding `archive`."""
    if not BLOCK.search(setup_text):
        raise ValueError("sandbox/setup.sh has no render-lock block")
    return BLOCK.sub(lambda m: f"{m.group(1)}RENDER_LOCK_B64='{archive}'\n{m.group(2)}", setup_text)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="exit 1 if setup.sh is stale")
    args = parser.parse_args()
    current = SETUP.read_text()
    wanted = embedded(current, render_lock_archive())
    if current == wanted:
        print("sandbox/setup.sh is current")
        return 0
    if args.check:
        print("sandbox/setup.sh is stale: run scripts/sync_sandbox_recipe.py", file=sys.stderr)
        return 1
    SETUP.write_text(wanted)
    print("updated sandbox/setup.sh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
