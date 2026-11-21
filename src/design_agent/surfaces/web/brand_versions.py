"""Immutable workspace-scoped brand snapshots with an atomic current-version pointer."""

from __future__ import annotations

import hashlib
import io
import re
import stat
import tomllib
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from zipfile import ZIP_STORED, ZipFile, ZipInfo

from design_agent.brand.schema import BrandToml, FontsFile, load_brand_pack
from design_agent.surfaces.web.blobs import BlobFiles, StorageUnavailable
from design_agent.surfaces.web.store import Store
from design_agent.workspace.manifest import BrandSnapshot

MAX_BYTES = 128 * 1024 * 1024
MAX_FILES = 2048
ARCHIVE = "brand-pack.zip"
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


class BrandConflict(ValueError):
    """The pack changed after the editor opened it."""


def _safe_name(name: str) -> bool:
    path = PurePosixPath(name)
    return bool(
        path.parts
        and not path.is_absolute()
        and path.as_posix() == name
        and name.isprintable()
        and "\\" not in name
        and ".." not in path.parts
        and not any(p.startswith(".env") or p == ".git" for p in path.parts)
    )


def _encode(folder: Path) -> bytes:
    buf = io.BytesIO()
    total = count = 0
    if folder.is_symlink() or not folder.is_dir():
        raise ValueError("Invalid brand directory")
    with ZipFile(buf, "w") as archive:
        for file in sorted(folder.rglob("*")):
            name = file.relative_to(folder).as_posix()
            if file.is_symlink() or not _safe_name(name):
                raise ValueError("Unsafe entry in brand pack")
            if file.is_dir():
                continue
            info = file.stat()
            count += 1
            total += info.st_size
            if not stat.S_ISREG(info.st_mode) or count > MAX_FILES or total > MAX_BYTES:
                raise ValueError("Invalid or oversized brand pack")
            archive.writestr(ZipInfo(name), file.read_bytes())
    if buf.tell() > MAX_BYTES:
        raise ValueError("Brand pack exceeds storage limit")
    return buf.getvalue()


def _validate(folder: Path, project: Path) -> None:
    brand = BrandToml.model_validate(tomllib.loads((folder / "brand.toml").read_text()))
    if not all(
        _safe_name(v)
        for v in [*brand.files.model_dump().values(), *(logo.file for logo in brand.logos)]
    ):
        raise ValueError("Brand file references must stay inside the pack")
    fonts = FontsFile.model_validate(tomllib.loads((folder / brand.files.fonts).read_text()))
    for face in fonts.fonts:
        path = Path(face.file)
        if path.parent.name == "fonts" and (folder / "fonts" / path.name).is_file():
            continue
        if not _safe_name(face.file) or path.parts[0] not in {"fonts", "private-fonts"}:
            raise ValueError("Invalid external brand font reference")
        if not (project / path).resolve().is_relative_to((project / path.parts[0]).resolve()):
            raise ValueError("External brand font escapes its directory")
    load_brand_pack(folder, project_root=project)


@contextmanager
def _open(data: bytes) -> Iterator[Path]:
    with (
        TemporaryDirectory(prefix="brand-pack-") as tmp,
        ZipFile(io.BytesIO(data)) as archive,
    ):
        folder = Path(tmp).resolve()
        for entry in archive.infolist():
            if not _safe_name(entry.filename) or entry.compress_type != ZIP_STORED:
                raise ValueError("Invalid brand snapshot")
            dest = folder / entry.filename
            dest.parent.mkdir(parents=True, exist_ok=True)
            with dest.open("xb") as output:
                output.write(archive.read(entry))
        yield folder


class BrandVersions:
    def __init__(self, store: Store, blobs: BlobFiles, project: Path):
        self.store, self.blobs, self.project = store, blobs, project

    def heads(self) -> dict[str, str]:
        return self.store.brand_heads()

    def _read(self, version: str) -> bytes:
        if not re.fullmatch(r"[0-9a-f]{64}", version):
            raise ValueError("Invalid brand version")
        key = f"{self.blobs.prefix}{version}/{ARCHIVE}"
        try:
            data = self.blobs.read({"storage": "s3", "rel_path": key}, MAX_BYTES + 1)
        except FileNotFoundError:
            raise StorageUnavailable() from None
        if len(data) > MAX_BYTES or hashlib.sha256(data).hexdigest() != version:
            raise StorageUnavailable()
        return data

    def snapshot(self, slug: str, version: str) -> BrandSnapshot:
        return BrandSnapshot(slug, version, lambda: _open(self._read(version)))

    def save(self, slug: str, folder: Path, expected: str | None) -> str:
        if not SLUG.fullmatch(slug):
            raise ValueError("Invalid brand slug")
        data = _encode(folder)
        with _open(data) as snapshot:
            _validate(snapshot, self.project)
        version = hashlib.sha256(data).hexdigest()
        if self.heads().get(slug) != expected:
            raise BrandConflict("Brand changed; reopen the latest version.")
        saved = self.blobs.save("", ARCHIVE, data)
        if saved["sha256"] != version or self._read(version) != data:
            raise StorageUnavailable()
        if not self.store.publish_brand(slug, version, expected):
            raise BrandConflict("Brand changed; reopen the latest version.")
        return version

    def migrate(self, root: Path, default: Path) -> int:
        heads = self.heads()
        if root.is_symlink():
            raise ValueError("Unsafe brand shelf")
        candidates = (
            [
                (p.name, p)
                for p in sorted(root.iterdir())
                if not p.name.startswith(".") and p.name != "default"
            ]
            if root.is_dir()
            else []
        )
        candidates.append(("default", default))
        migrated = 0
        for slug, path in candidates:
            if slug in heads or not (path / "brand.toml").is_file():
                continue
            try:
                self.save(slug, path, None)
            except BrandConflict:
                # Another process published a verified pack while this one was migrating.
                continue
            migrated += 1
        return migrated
