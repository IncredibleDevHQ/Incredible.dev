import shutil
from pathlib import Path

import pytest

from design_agent.config import project_root
from design_agent.surfaces.web.blobs import BlobFiles, StorageUnavailable
from design_agent.surfaces.web.brand_versions import BrandConflict, BrandVersions
from design_agent.surfaces.web.store import Store
from tests.unit.test_blob_storage import S3, configured


def test_verified_migration_concurrent_save_and_temporary_reads(tmp_path):
    client = S3()
    blobs = BlobFiles(configured(), tmp_path, "a" * 32, client=client)
    store = Store(tmp_path / "store.db")
    packs = BrandVersions(store, blobs, project_root())
    source = tmp_path / "brands" / "test"
    shutil.copytree(project_root() / "examples/brands/example-studio", source)
    client.fail = True
    with pytest.raises(StorageUnavailable):
        packs.migrate(tmp_path / "brands", tmp_path / "brand")
    assert not packs.heads()
    client.fail = False
    packs.migrate(tmp_path / "brands", tmp_path / "brand")
    first = packs.heads()["test"]
    objects = len(client.objects)
    packs.migrate(tmp_path / "brands", tmp_path / "brand")
    assert len(client.objects) == objects
    with packs.snapshot("test", first).open() as folder:
        assert (folder / "voice.md").read_bytes() == (source / "voice.md").read_bytes()
        (folder / "voice.md").write_text("An updated voice.")
        second = packs.save("test", folder, first)
        (folder / "voice.md").write_text("A stale edit.")
        with pytest.raises(BrandConflict):
            packs.save("test", folder, first)
    assert not folder.exists()
    shutil.rmtree(source)
    with packs.snapshot("test", second).open() as current:
        assert (current / "voice.md").read_text() == "An updated voice."
    assert packs.heads()["test"] == second


def test_unsafe_pack_is_never_uploaded(tmp_path):
    client = S3()
    store = Store(tmp_path / "store.db")
    packs = BrandVersions(
        store, BlobFiles(configured(), tmp_path, "b" * 32, client=client), project_root()
    )
    source = tmp_path / "pack"
    shutil.copytree(project_root() / "examples/brands/example-studio", source)
    (source / "linked").symlink_to(Path(__file__))
    with pytest.raises(ValueError):
        packs.save("test", source, None)
    assert not client.objects and not packs.heads()


def test_editor_reads_saves_and_stages_current_version_after_removing_legacy_files(
    tmp_path, monkeypatch
):
    from fastapi.testclient import TestClient

    from design_agent.surfaces.web import blobs as blob_module
    from design_agent.surfaces.web.app import create_app
    from design_agent.workspace.manifest import Manifest, ManifestBook

    s3 = S3()
    monkeypatch.setattr(blob_module, "s3_client", lambda _: s3)
    workspace = tmp_path / "workspace"
    source = workspace / "brands" / "one"
    shutil.copytree(project_root() / "examples/brands/example-studio", source)
    settings = configured().model_copy(update={"workspace_root": workspace, "sandbox": "host"})
    app = create_app(project_root(), settings, demo=True)
    with TestClient(app) as client:
        shutil.rmtree(source)
        initial = client.get("/api/brands/one").json()
        assert client.get(initial["logos"][0]["url"]).status_code == 200
        first = initial["version"]
        data = {"version": first, "files": {"voice.md": "Our new voice."}}
        result = client.patch("/api/brands/one", json=data)
        assert result.status_code == 200, result.text
        assert result.json()["version"] != first
        assert client.patch("/api/brands/one", json=data).status_code == 409
        assert (
            client.patch(
                "/api/brands/one",
                json={"version": result.json()["version"], "files": {"../outside": "bad"}},
            ).status_code
            == 422
        )
        assert not source.exists()
        store = app.state.host.store
        channel = store.channels()[0]["id"]
        assert client.patch(f"/api/channels/{channel}", json={"brand": "one"}).status_code == 200
        store.add_thread(
            thread_id="test", channel_id=channel, task=True, title="Render", kind="task", by="you"
        )
        book = ManifestBook(project_root(), Manifest((), ()), app.state.host.episodes.brand_for)
        manifest = book.for_thread("test")
        assert any(
            str(path).endswith("/brand/voice.md") and text == b"Our new voice."
            for path, text in manifest.generated
        )
        assert book.for_thread("test") is manifest
        # First edit makes a private revision of the sample and never changes the shipped pack.
        sample = project_root() / "examples/brands/example-studio/voice.md"
        original = sample.read_bytes()
        assert "default" not in store.brand_heads()
        response = client.patch(
            "/api/brands/default", json={"version": None, "files": {"voice.md": "Our own voice."}}
        )
        assert response.status_code == 200
        assert store.brand_heads()["default"] == response.json()["version"]
        assert sample.read_bytes() == original and not (workspace / "brand").exists()
        s3.objects.clear()
        assert client.get("/api/brands/one").status_code == 503


async def test_website_read_publishes_a_pack_and_cleans_working_files(tmp_path, monkeypatch):
    from design_agent.surfaces.web import brands
    from design_agent.surfaces.web.hub import Hub
    from tests.unit.test_web_brands import FIXTURE, _found

    async def read_fixture(url, out, **options):
        shutil.copytree(FIXTURE, out)
        return _found()

    monkeypatch.setattr(brands, "read_site", read_fixture)
    store = Store(tmp_path / "app.db")
    workspace = tmp_path / "workspace"
    settings = configured().model_copy(update={"workspace_root": workspace})
    packs = BrandVersions(
        store, BlobFiles(settings, tmp_path, "a" * 32, client=S3()), project_root()
    )
    shelf = brands.BrandShelf(
        store=store,
        hub=Hub(),
        settings=settings,
        project_root=project_root(),
        data_dir=workspace / "house",
        versions=packs,
    )
    status = shelf.read("https://example.com", by="you")
    await shelf._reads[status["url"]]
    assert status["status"] == "ready", status
    assert status["brand"]["version"] == store.brand_heads()[status["slug"]]
    with shelf.folder(status["slug"]) as pack:
        assert (pack / "reference/site.jpg").is_file()
    assert not pack.exists() and not (workspace / "brands").exists()
    assert not any(shelf.captures.iterdir())


def test_corrupt_readback_keeps_previous_version(tmp_path):
    class Corrupt(S3):
        damaged = False

        def put_object(self, **args):
            super().put_object(**args)
            if self.damaged:
                self.objects[args["Key"]] = b"damaged"

    client = Corrupt()
    packs = BrandVersions(
        Store(tmp_path / "db"),
        BlobFiles(configured(), tmp_path, "a" * 32, client=client),
        project_root(),
    )
    source = tmp_path / "pack"
    shutil.copytree(project_root() / "examples/brands/example-studio", source)
    first = packs.save("one", source, None)
    (source / "voice.md").write_text("new voice")
    client.damaged = True
    with pytest.raises(StorageUnavailable):
        packs.save("one", source, first)
    assert packs.heads() == {"one": first}
    with packs.snapshot("one", first).open() as restored:
        assert (restored / "voice.md").read_text() != "new voice"


def test_migration_refuses_pack_metadata_pointing_outside(tmp_path):
    client = S3()
    packs = BrandVersions(
        Store(tmp_path / "db"),
        BlobFiles(configured(), tmp_path, "a" * 32, client=client),
        project_root(),
    )
    source = tmp_path / "pack"
    shutil.copytree(project_root() / "examples/brands/example-studio", source)
    (tmp_path / "outside.md").write_text("outside")
    with (source / "brand.toml").open("a") as f:
        f.write('\n[files]\nvoice = "../outside.md"\n')
    with pytest.raises(ValueError):
        packs.save("one", source, None)
    assert not packs.heads() and not client.objects
