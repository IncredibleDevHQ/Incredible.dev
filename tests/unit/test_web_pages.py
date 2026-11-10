"""Links someone brings as material: read on the host, kept as files, refused with a reason."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from design_agent.config import Settings
from design_agent.surfaces.web import pages
from design_agent.surfaces.web.agent import AgentHost
from design_agent.surfaces.web.hub import Hub
from design_agent.surfaces.web.store import Store
from design_agent.tools.fetch import FetchRefused
from tests.unit.test_web_surface import FakeBackend, FakeRuntime

POST = "https://blog.example.com/posts/iceberg-wisdom/"
WORDS = "Iceberg brings forty years of database wisdom to the lakehouse. " * 12
ARTICLE = f"""<!doctype html><html><head>
<title>Iceberg wisdom | Example Blog</title>
<meta property="og:title" content="How Iceberg brought 40 years of database wisdom">
<script>window.track = "never words";</script><style>p {{ color: red }}</style>
</head><body>
<header><nav><a href="/">Home</a><a href="/blog">Blog</a></nav></header>
<main><article>
<header><h1>How Iceberg brought 40 years of database wisdom</h1></header>
<p>{WORDS}</p>
<h2>What tables learned</h2>
<ul><li><p>Snapshots, not locks</p></li><li>Hidden partitions</li></ul>
<blockquote><p>Tables are a contract.</p></blockquote>
<button>Subscribe</button>
</article></main>
<aside>Related posts you may like</aside>
<footer>© Example 2026</footer>
</body></html>"""


async def public(host: str, port: int) -> list[str]:
    return ["93.184.216.34"]


async def private(host: str, port: int) -> list[str]:
    return ["10.0.0.5"]


def serve(responses: dict[str, httpx.Response]) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        return responses.get(str(request.url), httpx.Response(404))

    return httpx.MockTransport(handle)


def html(body: str) -> httpx.Response:
    return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, text=body)


def test_a_page_reads_as_its_article_without_its_frame() -> None:
    title, text = pages.page_text(ARTICLE)
    assert title == "How Iceberg brought 40 years of database wisdom"
    assert text.startswith("# How Iceberg brought 40 years of database wisdom\n\nIceberg brings")
    assert "## What tables learned" in text
    assert "- Snapshots, not locks" in text and "- Hidden partitions" in text
    assert "> Tables are a contract." in text
    for frame in ("Home", "Blog", "never words", "color: red", "Subscribe", "Related", "©"):
        assert frame not in text


def test_links_are_found_once_without_the_sentence_around_them() -> None:
    text = f"Read {POST}. Then (see https://example.com/a) and {POST} again."
    assert pages.links_in(text) == [POST, "https://example.com/a"]
    assert len(pages.links_in(" ".join(f"https://e.com/{n}" for n in range(9)))) == pages.MAX_LINKS


async def test_a_linked_page_is_kept_as_markdown_after_its_redirect() -> None:
    moved = httpx.Response(301, headers={"location": POST})
    transport = serve({"http://blog.example.com/iceberg": moved, POST: html(ARTICLE)})
    read = await pages.read_link(
        "http://blog.example.com/iceberg", resolver=public, transport=transport
    )
    assert read.name == "How Iceberg brought 40 years of database wisdom.md"
    words = read.content.decode()
    assert words.startswith("# How Iceberg brought 40 years of database wisdom\n\nRead from http")
    assert words.count("# How Iceberg brought 40 years of database wisdom") == 1
    assert "Iceberg brings forty years" in words


async def test_a_linked_pdf_is_kept_as_itself() -> None:
    pdf = httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF-1.7 x")
    read = await pages.read_link(
        "https://example.com/files/Launch%20brief.pdf",
        resolver=public,
        transport=serve({"https://example.com/files/Launch%20brief.pdf": pdf}),
    )
    assert (read.name, read.content) == ("Launch brief.pdf", b"%PDF-1.7 x")


@pytest.mark.parametrize(
    ("resolver", "response", "why"),
    [
        (private, html(ARTICLE), "private or reserved address"),
        (public, html("<html><body><div id=app></div><script>render()</script>"), "a browser"),
        (public, httpx.Response(200, headers={"content-type": "image/png"}), "image/png"),
        (public, httpx.Response(403), "HTTP 403"),
    ],
)
async def test_a_link_that_cannot_be_read_says_why(
    resolver: pages.Resolver, response: httpx.Response, why: str
) -> None:
    with pytest.raises(FetchRefused, match=why):
        await pages.read_link(POST, resolver=resolver, transport=serve({POST: response}))


@pytest.fixture
def host(tmp_path: Path) -> AgentHost:
    agent = AgentHost(
        settings=Settings(), store=Store(tmp_path / "house.sqlite"), hub=Hub(), data_dir=tmp_path
    )
    agent.runtime = FakeRuntime(FakeBackend({}))  # type: ignore[assignment]
    agent.link_resolver = public
    return agent


async def test_a_template_started_from_a_link_works_from_the_page(host: AgentHost) -> None:
    host.link_transport = serve({POST: html(ARTICLE)})
    channel = str(host.store.channels()[0]["id"])
    read = await host.read_links(POST, by="you")
    message = host.place_template(channel, "explainer", by="you", text=POST, file_ids=read)
    thread = host.store.thread(message["thread_id"])
    assert thread is not None
    assert thread["title"] == "Explainer from How Iceberg brought 40 years of database wisdom"
    (kept,) = message["data"]["files"]
    assert kept["name"] == "How Iceberg brought 40 years of database wisdom.md"
    assert kept["origin"] == "link"


async def test_a_link_brought_alone_must_be_read_but_beside_notes_it_may_not(
    host: AgentHost,
) -> None:
    host.link_transport = serve({POST: httpx.Response(403)})
    with pytest.raises(
        ValueError, match=r"Couldn't read blog\.example\.com/posts/iceberg-wisdom: "
    ):
        await host.read_links(f" {POST} ", by="you")
    assert await host.read_links(f"Teaser line: one pass. Background: {POST}", by="you") == []
