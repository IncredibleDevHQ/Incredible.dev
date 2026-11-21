import io
import wave

import httpx
import pytest

from design_agent.tools import voice_lab
from design_agent.tools.media import Cloned, MediaKeys


def sample(frames=16000):
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setparams((1, 2, 16000, frames, "NONE", ""))
        wav.writeframes(bytes(frames * 2))
    return output.getvalue()


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["ok", "provider error", "truncated", "cleanup error"])
async def test_converts_entire_take_and_releases_only_created_voice(monkeypatch, outcome):
    calls = []

    async def clone(keys, name, samples):
        assert samples == [("recording.wav", sample())]
        return Cloned("newTestVoice", False)

    def provider(req):
        calls.append((req.method, req.url.path))
        if req.method == "DELETE":
            return httpx.Response(500 if outcome == "cleanup error" else 200)
        return httpx.Response(
            422 if outcome == "provider error" else 200,
            content=bytes(100 if outcome == "truncated" else 31980),
        )

    monkeypatch.setattr(voice_lab, "clone_voice", clone)
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        if outcome != "ok":
            with pytest.raises(ValueError):
                await voice_lab.render(client, MediaKeys(None, "test", None, ""), "Take", sample())
        else:
            data = await voice_lab.render(
                client, MediaKeys(None, "test", None, ""), "Take", sample()
            )
            with wave.open(io.BytesIO(data)) as wav:
                assert wav.getnframes() == 16000
    assert calls == [
        ("POST", "/v1/voice-changer/newTestVoice"),
        ("DELETE", "/v1/voices/newTestVoice"),
    ]


def test_rejects_unreadable_recording():
    with pytest.raises(ValueError):
        voice_lab.frame_count(b"broken")


@pytest.mark.asyncio
async def test_page_scope_and_consent(tmp_path, monkeypatch):
    from design_agent.config import Settings
    from design_agent.surfaces.web.app import create_app

    settings = Settings(_env_file=None, workspace_root=tmp_path)
    app = create_app(tmp_path, settings)
    store = app.state.host.store
    monkeypatch.setattr(
        store, "episode", lambda key: {"id": key} if key in ("one", "two") else None
    )
    monkeypatch.setattr(store, "person", lambda key: {"id": key})

    async def mock_render(client, keys, name, original, text):
        assert text == "Hello tomorrow!"
        return sample()

    monkeypatch.setattr(voice_lab, "render", mock_render)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            url = "/api/episodes/one/voice-tests"
            form = {"name": "First read", "consent": "false", "text": "Hello tomorrow!"}
            files = {"file": ("take.wav", sample(), "audio/wav")}
            assert (await client.post(url, data=form, files=files)).status_code == 422
            form["consent"] = "true"
            made = (await client.post(url, data=form, files=files)).raise_for_status().json()
            assert (await client.get(url)).json()["clips"] == [made]
            assert (await client.get(url, headers={"X-Person": "other"})).json()["clips"] == []
            for kind in ("original", "clone"):
                audio = f"{url}/{made['id']}/{kind}"
                assert (await client.get(audio)).content == sample()
                assert (await client.get(audio, headers={"X-Person": "other"})).status_code == 404
                assert (await client.get(audio.replace("/one/", "/two/"))).status_code == 404
    finally:
        store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["permission", "provider", "timeout"])
async def test_conversion_failure_explains_the_provider_or_transport_problem(monkeypatch, failure):
    async def clone(*args):
        return Cloned("newTestVoice", False)

    def provider(request):
        if request.method == "DELETE":
            return httpx.Response(200)
        if failure == "permission":
            return httpx.Response(
                401,
                json={
                    "detail": {
                        "status": "missing_permissions",
                        "message": "Missing permission speech_to_speech",
                    }
                },
            )
        if failure == "timeout":
            raise httpx.ReadTimeout("timeout", request=request)
        return httpx.Response(
            403, json={"detail": {"message": "Voice Changer permission is missing."}}
        )

    monkeypatch.setattr(voice_lab, "clone_voice", clone)
    reason = {
        "timeout": "timed out",
        "provider": "403.*Voice Changer permission",
        "permission": "needs Speech to Speech",
    }[failure]
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        with pytest.raises(ValueError, match=reason):
            await voice_lab.render(client, MediaKeys(None, "test", None, ""), "Take", sample())


@pytest.mark.asyncio
async def test_new_words_use_clone_id_and_natural_duration(monkeypatch):
    async def clone(*args):
        return Cloned("newTestVoice", False)

    def provider(request):
        if request.method == "DELETE":
            return httpx.Response(200)
        import json

        assert request.url.path == "/v1/text-to-speech/newTestVoice"
        body = json.loads(request.content)
        assert body["text"] == "Tomorrow we take the train."
        assert body["model_id"] == "eleven_multilingual_v2"
        assert body["voice_settings"] == {"similarity_boost": 0.9, "stability": 0.5}
        return httpx.Response(200, content=bytes(64000))

    monkeypatch.setattr(voice_lab, "clone_voice", clone)
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        data = await voice_lab.render(
            client,
            MediaKeys(None, "test", None, ""),
            "Take",
            sample(),
            "Tomorrow we take the train.",
        )
        assert voice_lab.frame_count(data) == 32000
