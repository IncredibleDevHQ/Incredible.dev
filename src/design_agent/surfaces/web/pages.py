"""Links someone brings as material, read on the host.

A link pasted as what a task starts from (a launch post, an article) is no use to the agent as a
link: its computer has no network, and `fetch_asset` takes files, not web pages. So the host reads
each link when the person sends it, as carefully as `fetch_asset` does (http(s) to public addresses
only, every redirect checked again, size and time bounded). A web page is kept as the words of its
article in Markdown, a PDF as itself, and either goes with the ask as a file. A page with no
readable words (one a browser has to build) is refused with that reason, so the person can paste
its text instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit

import httpx

from design_agent.tools.fetch import FetchRefused, Resolver, fetch, system_resolver

#: A link in what someone wrote; trailing punctuation is the sentence's, not the link's.
LINK = re.compile(r"https?://[^\s<>\"'`]+")
MAX_LINKS = 3
MAX_BYTES = 20 * 1024 * 1024
PAGE_TYPES = ("text/html", "application/xhtml+xml", "text/plain", "text/markdown")
FILE_TYPES = ("application/pdf",)
#: Fewer characters than this and the page is a shell that a browser fills in.
MIN_TEXT = 400
MAX_TEXT = 80_000
AGENT = "Mozilla/5.0 (compatible; CreativeHouse/0.1; reads pages people bring as material)"

# Never words: what runs in a page, draws in it, or is a control.
HIDDEN = frozenset({"script", "style", "noscript", "template", "svg", "canvas", "iframe", "button"})
# A page's frame (menus, headers, footers, side columns), left out unless it sits in the article.
FRAME = frozenset({"nav", "header", "footer", "aside"})
BLOCKS = frozenset(
    {
        "p", "div", "section", "article", "main", "li", "ul", "ol", "blockquote", "pre",
        "figure", "figcaption", "table", "tr", "td", "th", "dl", "dt", "dd", "hr",
        "h1", "h2", "h3", "h4", "h5", "h6",
    }
)  # fmt: skip
PREFIX = {"h1": "# ", "h2": "## ", "h3": "### ", "h4": "#### ", "li": "- ", "blockquote": "> "}


@dataclass(frozen=True)
class Read:
    """One link as a file: its name, its bytes, and what it is called."""

    url: str
    name: str
    content: bytes
    title: str


def links_in(text: str) -> list[str]:
    """The links in what someone wrote, each once, at most MAX_LINKS."""
    found: list[str] = []
    for match in LINK.finditer(text):
        url = match.group(0).rstrip(".,;:!?)]}")
        if url not in found:
            found.append(url)
    return found[:MAX_LINKS]


async def read_link(
    url: str,
    *,
    resolver: Resolver = system_resolver,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Read:
    """Fetch one link and keep it: a page as its article's words in Markdown, a PDF as itself.
    Raises FetchRefused, with a reason safe to show, when it can't be read."""
    async with httpx.AsyncClient(timeout=30, follow_redirects=False, transport=transport) as client:
        data, kind = await fetch(
            url,
            client=client,
            resolver=resolver,
            types=PAGE_TYPES + FILE_TYPES,
            limit=MAX_BYTES,
            agent=AGENT,
        )
    if kind in FILE_TYPES:
        return Read(url, _file_name(url, ".pdf"), data, "")
    raw = data.decode("utf-8", errors="replace")
    title, text = ("", raw.strip()) if kind in ("text/plain", "text/markdown") else page_text(raw)
    if len(text) < MIN_TEXT:
        raise FetchRefused("the page has no readable text (a browser builds it)")
    # The page's own heading leads, once, with where it was read from under it.
    heading = f"# {title or url}"
    body = text[len(heading) :].lstrip("\n") if text.startswith(heading) else text
    words = f"{heading}\n\nRead from {url}\n\n{body[:MAX_TEXT]}\n"
    return Read(url, _file_name(url, ".md", title), words.encode(), title)


def page_text(html: str) -> tuple[str, str]:
    """A page's title and the words of its article (else its main part, else its body) as
    Markdown blocks: headings, paragraphs, lists and quotes, without its frame or scripts."""
    words = _Words()
    words.feed(html)
    words.close()
    title = " ".join((words.og_title or words.title).split())
    for region in ("article", "main", "body"):
        text = "\n\n".join(_unrepeated(words.blocks[region]))
        if len(text) >= MIN_TEXT or region == "body":
            return title, text
    return title, ""


def _unrepeated(blocks: list[str]) -> list[str]:
    out: list[str] = []
    for block in blocks:
        if not out or out[-1] != block:
            out.append(block)
    return out


def _file_name(url: str, suffix: str, title: str = "") -> str:
    path = unquote(urlsplit(url).path).rstrip("/")
    words = title or path.rsplit("/", 1)[-1].rsplit(".", 1)[0] or urlsplit(url).hostname or "page"
    return f"{' '.join(words.split())[:90].strip()}{suffix}"


class _Words(HTMLParser):
    """Collects a page's title and its text blocks, each counted in every region it sits in:
    the body always, the article and the main part while inside them."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.og_title = ""
        self.blocks: dict[str, list[str]] = {"article": [], "main": [], "body": []}
        self._regions: list[str] = []
        self._hidden = 0
        self._framed = 0
        self._in_title = False
        self._pre = 0
        self._line: list[str] = []
        self._prefix = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "meta":
            found = dict(attrs)
            if found.get("property") == "og:title" and found.get("content"):
                self.og_title = str(found["content"])
            return
        if tag == "title":
            self._in_title = True
            return
        if tag in HIDDEN:
            self._hidden += 1
            return
        if tag in FRAME and not self._regions:
            self._framed += 1
            return
        if tag == "br":
            self._line.append("\n" if self._pre else " ")
            return
        if tag in BLOCKS:
            # A paragraph or box inside a list item or a quote keeps its bullet or its mark.
            kept = self._prefix
            self._flush()
            self._prefix = PREFIX.get(tag, kept if tag in ("p", "div") else "")
        if tag in ("article", "main"):
            self._regions.append(tag)
        if tag == "pre":
            self._pre += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
            return
        if tag in HIDDEN:
            self._hidden = max(0, self._hidden - 1)
            return
        if tag in FRAME and self._framed:
            self._framed -= 1
            return
        if tag in BLOCKS:
            self._flush()
        if tag in ("article", "main") and tag in self._regions:
            del self._regions[len(self._regions) - 1 - self._regions[::-1].index(tag)]
        if tag == "pre":
            self._pre = max(0, self._pre - 1)

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif not (self._hidden or self._framed):
            self._line.append(data if self._pre else re.sub(r"\s+", " ", data))

    def close(self) -> None:
        super().close()
        self._flush()

    def _flush(self) -> None:
        text = "".join(self._line)
        text = text.strip("\n") if self._pre else " ".join(text.split())
        self._line = []
        if text:
            block = f"```\n{text}\n```" if self._pre else self._prefix + text
            self.blocks["body"].append(block)
            for region in set(self._regions):
                self.blocks[region].append(block)
        self._prefix = ""
