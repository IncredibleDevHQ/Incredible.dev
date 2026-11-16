"""Host tools: SSRF hardening, media tools without keys, provider calls with a mocked transport."""

from __future__ import annotations

import base64
import json
import struct
import zlib
from typing import Any

import httpx
import pytest
from deepagents.backends.protocol import FileDownloadResponse, FileUploadResponse

from design_agent.config import Settings
from design_agent.tools.fetch import FetchRefused, build_fetch_tool, check_url, public_address
from design_agent.tools.media import _png_alpha_report, build_media_tools, image_route


class MemoryBackend:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    async def aupload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        self.files.update(files)
        return [FileUploadResponse(path=p) for p, _ in files]

    async def adownload_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        return [
            FileDownloadResponse(
                path=p,
                content=self.files.get(p),
                error=None if p in self.files else "file_not_found",
            )
            for p in paths
        ]


def resolver_for(mapping: dict[str, list[str]]):  # type: ignore[no-untyped-def]
    async def resolve(host: str, port: int) -> list[str]:
        return mapping[host]

    return resolve


@pytest.mark.parametrize(
    "address",
    [
        "10.0.0.5",
        "127.0.0.1",
        "169.254.169.254",
        "::1",
        "fe80::1",
        "100.64.1.1",
        "::ffff:10.0.0.1",
        "0.0.0.0",
    ],
)
def test_private_and_metadata_addresses_are_not_public(address: str) -> None:
    assert not public_address(address)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/a.png",
        "https://user:pw@example.com/a.png",
        "https://example.com:8443/a.png",
        "http://localhost/a.png",
        "http://metadata.google.internal/computeMetadata/v1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/a.png",
        "https://rebind.example/a.png",
    ],
)
async def test_unsafe_urls_are_refused(url: str) -> None:
    with pytest.raises(FetchRefused):
        await check_url(url, resolver_for({"rebind.example": ["93.184.216.34", "192.168.1.10"]}))


async def test_fetch_rechecks_redirects_and_writes_the_file() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "cdn.example":
            return httpx.Response(302, headers={"location": "https://internal.example/secret.png"})
        return httpx.Response(200, content=b"x", headers={"content-type": "image/png"})

    backend = MemoryBackend()
    tool = build_fetch_tool(
        lambda _rt: backend,  # type: ignore[arg-type,return-value]
        resolver=resolver_for({"cdn.example": ["93.184.216.34"], "internal.example": ["10.1.2.3"]}),
        transport=httpx.MockTransport(handler),
    )
    result = await tool.coroutine(
        url="https://cdn.example/a.png", sandbox_path="/workspace/attachments/a.png", runtime=None
    )  # type: ignore[misc]
    assert "private or reserved" in result and not backend.files


async def test_fetch_refuses_web_pages_and_svg() -> None:
    backend = MemoryBackend()
    for kind in ("text/html", "image/svg+xml"):
        tool = build_fetch_tool(
            lambda _rt: backend,  # type: ignore[arg-type,return-value]
            resolver=resolver_for({"cdn.example": ["93.184.216.34"]}),
            transport=httpx.MockTransport(
                lambda _r, kind=kind: httpx.Response(
                    200, content=b"<x>", headers={"content-type": kind}
                )
            ),
        )
        result = await tool.coroutine(
            url="https://cdn.example/a", sandbox_path="/workspace/attachments/a", runtime=None
        )  # type: ignore[misc]
        assert "not fetched" in result
    assert not backend.files


async def test_media_tools_explain_missing_keys_without_calling_out() -> None:
    backend = MemoryBackend()
    tools = {t.name: t for t in build_media_tools(Settings(_env_file=None), lambda _rt: backend)}  # type: ignore[call-arg,arg-type,return-value]
    image = await tools["generate_image"].coroutine(
        prompt="a lamp", sandbox_path="/workspace/projects/p/lamp.png", runtime=None
    )  # type: ignore[misc]
    assert "no OPENAI_API_KEY" in image
    voice = await tools["generate_voiceover"].coroutine(
        text="Hi",
        voice_id="abcdefghij12",
        sandbox_path="/workspace/projects/p/vo.mp3",
        runtime=None,
    )  # type: ignore[misc]
    assert "no ELEVENLABS_API_KEY" in voice
    assert "under /workspace" in await tools["generate_image"].coroutine(
        prompt="x", sandbox_path="/etc/x.png", runtime=None
    )  # type: ignore[misc]


def _png(width: int, height: int, alpha: int) -> bytes:
    raw = b"".join(b"\x00" + bytes([255, 0, 0, alpha]) * width for _ in range(height))

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def test_alpha_report_measures_pixels_not_the_request_flag() -> None:
    assert _png_alpha_report(_png(4, 4, 0)) == (True, 1.0)
    assert _png_alpha_report(_png(4, 4, 255)) == (True, 0.0)
    assert _png_alpha_report(b"not a png") == (None, None)


async def test_generate_image_writes_b64_output_and_reports_alpha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {"data": [{"b64_json": base64.b64encode(_png(2, 2, 0)).decode()}]}
    seen: dict[str, Any] = {}

    async def fake_post(self: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
        seen.update(url=url, body=kwargs["json"])
        return httpx.Response(
            200, content=json.dumps(payload).encode(), request=httpx.Request("POST", url)
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    backend = MemoryBackend()
    tools = {
        t.name: t
        for t in build_media_tools(
            Settings(_env_file=None, openai_api_key="sk-test"), lambda _rt: backend
        )
    }  # type: ignore[call-arg,arg-type,return-value]
    result = await tools["generate_image"].coroutine(
        prompt="a lamp",
        sandbox_path="/workspace/projects/p/lamp.png",
        runtime=None,
        background="transparent",
        output_format="png",
    )  # type: ignore[misc]
    assert "wrote /workspace/projects/p/lamp.png" in result and "alpha verified" in result
    assert seen["body"]["model"] == "gpt-image-2.5-flare"
    assert seen["url"].startswith("https://api.openai.com/")


def _settings(**values: Any) -> Settings:
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def test_images_go_to_openai_with_its_key_else_through_the_gateway() -> None:
    direct = image_route(_settings(openai_api_key="sk-test", langsmith_gateway_api_key="lsv2-g"))
    assert direct is not None and direct.url.startswith("https://api.openai.com/")
    assert direct.key == "sk-test"

    gateway = image_route(_settings(langsmith_gateway_api_key="lsv2-g", langsmith_api_key="lsv2-l"))
    assert gateway is not None
    assert gateway.url == "https://gateway.smith.langchain.com/openai/v1/images/generations"
    assert gateway.key == "lsv2-g"

    lead = image_route(
        _settings(model="langsmith:anthropic/claude-opus-5-5", langsmith_api_key="lsv2-l")
    )
    assert lead is not None and lead.key == "lsv2-l" and lead.via == "the LangSmith Gateway"

    assert image_route(_settings(langsmith_api_key="lsv2-l")) is None


async def test_a_gateway_without_an_openai_key_says_where_to_add_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_post(self: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
        return httpx.Response(424, content=b"{}", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    backend = MemoryBackend()
    tools = {
        t.name: t
        for t in build_media_tools(
            _settings(langsmith_gateway_api_key="lsv2-g"), lambda _rt: backend
        )
    }  # type: ignore[arg-type,return-value]
    result = await tools["generate_image"].coroutine(
        prompt="a lamp", sandbox_path="/workspace/projects/p/lamp.png", runtime=None
    )  # type: ignore[misc]
    assert "LangSmith Gateway HTTP 424" in result and "no OpenAI key" in result
    assert not backend.files


async def test_a_voice_is_cloned_from_recordings_and_the_accounts_own_are_listed_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from design_agent.tools.media import Cloned, MediaKeys, Voice, clone_voice, voices

    keys = MediaKeys.from_settings(_settings(elevenlabs_api_key="xi-test"))
    seen: dict[str, Any] = {}

    async def fake_post(self: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
        seen.update(url=url, **kwargs)
        made = {"voice_id": "clone1234567890", "requires_verification": False}
        return httpx.Response(200, json=made, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    samples = [("take-1.m4a", b"one"), ("/tmp/memo.wav", b"two")]
    assert await clone_voice(keys, "  My   voice ", samples) == Cloned(
        "clone1234567890", verify=False
    )
    assert seen["url"] == "https://api.elevenlabs.io/v1/voices/add"
    assert seen["headers"] == {"xi-api-key": "xi-test"}
    assert seen["data"] == {"name": "My voice", "remove_background_noise": "false"}
    assert seen["files"] == [
        ("files", ("take-1.m4a", b"one", "audio/mp4")),
        ("files", ("memo.wav", b"two", "audio/wav")),
    ]
    # what cannot make a voice is refused here, before a recording leaves this computer
    seen.clear()
    one = [("a.m4a", b"a")]
    assert "no ELEVENLABS_API_KEY" in str(
        await clone_voice(MediaKeys.from_settings(_settings()), "x", one)
    )
    assert "needs a name" in str(await clone_voice(keys, " ", one))
    assert "1 to 25 recordings" in str(await clone_voice(keys, "x", []))
    assert "empty" in str(await clone_voice(keys, "x", [("a.m4a", b"")]))
    assert not seen

    # the provider's own reason is passed on: a plan without cloning says so
    async def refused(self: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
        detail = {"status": "no_cloning", "message": "Your plan has no instant voice cloning."}
        return httpx.Response(401, json={"detail": detail}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", refused)
    assert await clone_voice(keys, "x", one) == (
        "cloning failed: ElevenLabs HTTP 401: Your plan has no instant voice cloning."
    )

    pages: list[dict[str, Any]] = [
        {
            "voices": [
                {
                    "voice_id": "premade123456",
                    "name": "Ada",
                    "category": "premade",
                    "preview_url": "https://storage.googleapis.com/eleven-public-prod/ada.mp3",
                },
                {"voice_id": "not an id", "name": "x"},
            ],
            "has_more": True,
            "next_page_token": "t2",
        },
        {
            "voices": [
                {
                    "voice_id": "clone1234567890",
                    "name": "My voice",
                    "category": "cloned",
                    "preview_url": "http://untrusted.invalid/sample",
                }
            ],
            "has_more": False,
        },
    ]
    asked: list[dict[str, Any]] = []

    async def fake_get(self: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
        asked.append({"url": url, **kwargs["params"]})
        return httpx.Response(200, json=pages[len(asked) - 1], request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    listed = await voices(keys)
    assert listed == [
        Voice("clone1234567890", "My voice", "cloned"),
        Voice(
            "premade123456",
            "Ada",
            "premade",
            "https://storage.googleapis.com/eleven-public-prod/ada.mp3",
        ),
    ]
    assert isinstance(listed, list) and listed[0].own and not listed[1].own
    assert asked[0]["url"] == "https://api.elevenlabs.io/v2/voices"
    assert "next_page_token" not in asked[0] and asked[1]["next_page_token"] == "t2"
