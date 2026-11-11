// What a task started from, first in its flow: each page read from a link someone brought (shown
// as the page it is: its site, its title, a line of it and how much was read), the files they
// attached, and whatever else they wrote.
import { ArrowUpRight, Check, Globe, Paperclip } from "lucide-react";
import { useEffect, useState } from "react";
import type { FileView, Material } from "../api";
import { useHouse } from "../store";
import { FileList, fileSize } from "../ui";

export const SOURCE = "source";
// A link in what someone wrote, as the host finds them (pages.py's LINK and links_in): each once,
// without the sentence's trailing punctuation.
const LINK = /https?:\/\/[^\s<>"'`]+/g;
export const linksIn = (text: string) => [...new Set((text.match(LINK) ?? []).map((u) => u.replace(/[.,;:!?)\]}]+$/, "")))];
export const siteOf = (url: string) => {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
};

export function SourceNode({ material }: { material: Material }) {
  const [first, ...rest] = material.text.split("\n");
  // A template's first line names it (the frame's title says so); the material is what follows.
  const words = rest.join("\n").trim() || (material.files.length ? "" : first);
  const read = material.files.filter((f) => f.origin === "link");
  const files = material.files.filter((f) => f.origin !== "link");
  const links = linksIn(words);
  // Every link was read: each shows as its page, and the words keep only what else they say.
  const each = read.length > 0 && links.length === read.length;
  const notes = each ? words.replace(LINK, "").trim() : words;
  return (
    <article className="node source" data-node={SOURCE} aria-label="What this started from">
      <header className="node-head">
        <span className="node-icon">
          <Paperclip size={16} />
        </span>
        <b>Source</b>
      </header>
      <div className="node-body">
        {read.map((f, i) => (
          <PageCard key={f.id} file={f} among={material.files} link={each ? links[i] : undefined} />
        ))}
        {files.length > 0 && <FileList files={files} title="Source" />}
        {notes && <p className="source-words">{notes}</p>}
      </div>
    </article>
  );
}

type Page = { title: string; url: string; words: number; line: string };
const pages = new Map<string, Promise<Page | null>>();

// A page is kept as Markdown: its heading, "Read from <its address>", then its words (pages.py).
function readPage(id: string, url: string): Promise<Page | null> {
  let page = pages.get(id);
  if (!page) {
    page = fetch(url)
      .then((r) => (r.ok ? r.text() : ""))
      .then((text) => {
        const [head = "", from = "", ...blocks] = text.split(/\n{2,}/);
        if (!head.startsWith("# ") || !from.startsWith("Read from ")) return null;
        return {
          title: head.slice(2).trim(),
          url: from.slice("Read from ".length).trim(),
          words: blocks.join(" ").split(/\s+/).filter((w) => /\w/.test(w)).length,
          // Its first paragraph long enough to be the article's, not a byline or a date.
          line: blocks.find((b) => b.length > 80 && !/^(#|- |> |\||```)/.test(b)) ?? "",
        };
      })
      .catch(() => null);
    pages.set(id, page);
  }
  return page;
}

function PageCard({ file, among, link }: { file: FileView; among: FileView[]; link?: string }) {
  const openFiles = useHouse((s) => s.openFiles);
  const [page, setPage] = useState<Page | null>(null);
  const { id, url: kept } = file;
  const pdf = file.mime === "application/pdf";
  useEffect(() => {
    let live = true;
    if (!pdf) void readPage(id, kept).then((p) => live && setPage(p));
    return () => {
      live = false;
    };
  }, [id, kept, pdf]);
  const url = page?.url || link || "";
  const site = siteOf(url);
  return (
    <div className="page-card">
      <button type="button" className="page-main" title="Read the words it kept" onClick={() => openFiles({ files: among, at: id, title: "Source" })}>
        <span className="page-site">
          <Globe />
          {site || "A page from a link"}
        </span>
        <b className="page-title">{page?.title || file.name.replace(/\.(md|pdf)$/i, "")}</b>
        {page?.line && <span className="page-line">{page.line}</span>}
        <span className="page-read">
          <Check />
          {page ? `${page.words.toLocaleString("en")} words read` : pdf ? `Kept as a PDF · ${fileSize(file.size)}` : "Read"}
        </span>
      </button>
      {url && (
        <a className="page-out" href={url} target="_blank" rel="noreferrer" title={`Open it on ${site}`} aria-label={`Open it on ${site}`}>
          <ArrowUpRight />
        </a>
      )}
    </div>
  );
}
