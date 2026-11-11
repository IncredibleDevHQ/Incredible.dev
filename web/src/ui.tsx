import { preference } from "./preferences";
// Small pieces every view shares: who said it, what state a thread is in, files, the footer, and
// an agent's words.
import {
  AudioLines,
  Captions,
  ChartColumn,
  Check,
  CircleAlert,
  Clapperboard,
  Crop,
  FileText,
  Film,
  Globe,
  Image as ImageIcon,
  Images,
  LayoutGrid,
  type LucideIcon,
  Palette,
  Paperclip,
  Presentation,
  Repeat2,
  ScanSearch,
  Sparkles,
  SquarePlay,
  X,
} from "lucide-react";
import type { FileView, Footer, Person, Step, ThreadStatus } from "./api";
import { useHouse } from "./store";

// Each kind of work the engine makes (the catalog's capabilities), by its icon.
const KIND_ICONS: Record<string, LucideIcon> = {
  board: LayoutGrid,
  video: Clapperboard,
  film: Film,
  thumbs: SquarePlay,
  still: Images,
  deck: Presentation,
  chart: ChartColumn,
  genimg: Sparkles,
  edit: Crop,
  gif: Repeat2,
  looks: Palette,
  sound: AudioLines,
  captions: Captions,
  study: ScanSearch,
};

export function KindIcon({ kind, size = 16 }: { kind: string; size?: number }) {
  const Icon = KIND_ICONS[kind] ?? Paperclip;
  return <Icon size={size} aria-hidden="true" />;
}

export const capabilityOf = (id: string) => useHouse.getState().catalog.capabilities.find((c) => c.id === id);
export const kindTitle = (id: string) => capabilityOf(id)?.title ?? "";
// What an asset of this kind hands back, as other work is made from it.
export const makesOf = (kind: string) => capabilityOf(kind)?.makes ?? "doc";

export function clock(ts: number) {
  const format = preference("clock");
  return new Date(ts * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit", hour12: format === "system" ? undefined : format === "12" });
}

export function Avatar({ person, size }: { person?: Person; size?: "sm" }) {
  if (!person) return <span className={`avatar ${size ?? ""}`} style={{ background: "#444" }} />;
  return (
    <span
      className={`avatar ${size ?? ""}`}
      style={{ background: `hsl(${person.hue} 55% 68%)` }}
      aria-hidden="true"
      title={person.name}
    >
      {person.initials}
    </span>
  );
}

// Agents are shown by their logo (Claude, Codex, Kimi), never by a name.
export function AgentMark({ mark, size }: { mark?: string; size?: "sm" }) {
  const known = mark === "claude" || mark === "codex" || mark === "kimi";
  const label = known ? `${mark![0].toUpperCase()}${mark!.slice(1)}` : "The agent";
  return (
    <img
      className={`mark ${size ?? ""} ${known ? "" : "house"}`}
      src={known ? `/agents/${mark}.png` : "/house.svg"}
      alt={label}
      title={label}
    />
  );
}

export function StatusChip({ status }: { status: ThreadStatus }) {
  if (status === "working") return <span className="chip green"><span className="spin" style={{ width: 10, height: 10, borderWidth: 1.5 }} />Working</span>;
  if (status === "needs_you") return <span className="chip amber">Needs you</span>;
  if (status === "failed") return <span className="chip red">Stopped</span>;
  return <span className="chip">Done</span>;
}

export function StepIcon({ status }: { status: Step["status"] }) {
  if (status === "running") return <span className="st"><span className="spin" /></span>;
  if (status === "done") return <span className="st done"><Check strokeWidth={2.5} /></span>;
  if (status === "failed") return <span className="st"><X strokeWidth={2.5} /></span>;
  return <span className="st pending"><i /></span>;
}

// What a file shows as: a picture, a film, a sound, a document to read (markdown), plain text, or
// a file only to download.
export type FileKind = "image" | "video" | "audio" | "doc" | "text" | "other";
export function fileKind(f: FileView): FileKind {
  if (f.mime.startsWith("image/")) return "image";
  if (f.mime.startsWith("video/")) return "video";
  if (f.mime.startsWith("audio/")) return "audio";
  if (f.mime === "text/markdown" || /\.(md|markdown)$/i.test(f.name)) return "doc";
  if (f.mime.startsWith("text/") || /\.(json|srt|vtt|csv|txt|log|ya?ml|toml)$/i.test(f.name)) return "text";
  return "other";
}

export const fileSize = (n: number) => (n > 1e6 ? `${(n / 1e6).toFixed(1)} MB` : n > 1e3 ? `${Math.round(n / 1e3)} KB` : `${n} B`);

export function FileGlyph({ kind, size }: { kind: FileKind; size?: number }) {
  const Icon = kind === "video" ? Film : kind === "audio" ? AudioLines : kind === "image" ? ImageIcon : kind === "other" ? Paperclip : FileText;
  return <Icon size={size} />;
}

// Files as chips, a film playing in place when `large`. A chip opens its file full size, among the
// set it came in (`among`, or these), under the set's `title`.
export function FileList({ files, large, title, among }: { files?: FileView[]; large?: boolean; title?: string; among?: FileView[] }) {
  const openFiles = useHouse((s) => s.openFiles);
  if (!files?.length) return null;
  const media = large ? files.filter((f) => fileKind(f) === "video") : [];
  const rest = files.filter((f) => !media.includes(f));
  return (
    <>
      {media.map((f) => (
        <div className="media" key={f.id}>
          {/* Two seconds in: a film's first frame is often its empty ground. */}
          <video src={`${f.url}#t=2`} controls preload="metadata" />
        </div>
      ))}
      {rest.length > 0 && (
        <div className="files">
          {rest.map((f) => {
            const kind = fileKind(f);
            // A page read from a link goes by its title, as a page.
            const page = f.origin === "link" && kind === "doc";
            const name = page ? f.name.replace(/\.md$/i, "") : f.name;
            return (
              <button type="button" className="file" key={f.id} title={name} onClick={() => openFiles({ files: among ?? files, at: f.id, title })}>
                {kind === "image" ? (
                  <img src={f.url} alt="" />
                ) : (
                  <span className="ico">{page ? <Globe size={16} /> : <FileGlyph kind={kind} size={16} />}</span>
                )}
                <span>{name}</span>
              </button>
            );
          })}
        </div>
      )}
    </>
  );
}

// The design agent's footer: only what changes. "2 agents running · render 45%, ~6 min left ·
// 12 min · ~$12.40 so far" while work runs; totals once it settles.
export function FooterLine({ footer }: { footer?: Footer }) {
  if (!footer || footer.minutes === undefined) return null;
  const parts: React.ReactNode[] = [];
  if (footer.live) {
    if (footer.agents) parts.push(<span key="a"><b>{footer.agents}</b> {footer.agents === 1 ? "agent" : "agents"} running</span>);
    if (footer.render) {
      const pct = footer.render.fraction != null ? `${Math.round(footer.render.fraction * 100)}%` : "starting";
      const eta = footer.render.eta ? `, ~${Math.max(1, Math.round(footer.render.eta / 60))} min left` : "";
      parts.push(<span key="r">{footer.render.label || "render"} <b>{pct}</b>{eta}</span>);
    }
  }
  parts.push(<span key="m">{Math.max(footer.minutes, 1)} min</span>);
  if (footer.usd) parts.push(<span key="c">~${footer.usd.toFixed(2)} {footer.live ? "so far" : "total"}</span>);
  return (
    <div className="footer-line">
      {parts.map((p, i) => (
        <span key={i}>
          {i > 0 && " · "}
          {p}
        </span>
      ))}
    </div>
  );
}

export function Problem({ text }: { text: string }) {
  return (
    <span className="chip red">
      <CircleAlert />
      {text}
    </span>
  );
}

// -- an agent's words ---------------------------------------------------------------------------

type Spans = { threadId?: string; links: boolean };
type Block = { kind: "p" | "ul" | "ol" | "quote" | "h1" | "h2" | "h3" | "h4" | "pre" | "table" | "hr"; lines: string[] };
const INLINE =
  /(`[^`\n]+`)|(\*\*[^*\n]+?\*\*)|(\[[^\]\n]+\]\([^)\s]+\))|(https?:\/\/[^\s<>()[\]]*[^\s<>()[\].,;:!?'"])|(\*[^*\s](?:[^*\n]*[^*\s])?\*)/g;
const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "0.0.0.0"]);
const FENCE = /^\s*(```|~~~)/;
const RULE_ROW = /^\|?(\s*:?-{2,}:?\s*\|)*\s*:?-{2,}:?\s*\|?$/;

// What markdown is shown with (an agent's reply, a delivered document): headings, paragraphs,
// lists, quotes, tables, code, bold, italics and links. A link to the thread's own computer (a
// film's Studio preview) opens through the house; any other link opens in a new tab, and nothing
// but http(s) is ever a link. `inline` keeps it to one run of text.
export function Rich({ text, threadId, inline }: { text: string; threadId?: string; inline?: boolean }) {
  if (inline) return <>{spans(text.replace(/\s*\n\s*/g, " "), { links: false })}</>;
  const opts = { threadId, links: true };
  return (
    <>
      {blocksOf(text).map((block, i) => {
        switch (block.kind) {
          case "p":
            return <p key={i}>{spans(block.lines.join("\n"), opts)}</p>;
          case "quote":
            return <blockquote key={i}>{spans(block.lines.join("\n"), opts)}</blockquote>;
          case "pre":
            return (
              <pre key={i}>
                <code>{block.lines.join("\n")}</code>
              </pre>
            );
          case "hr":
            return <hr key={i} />;
          case "table":
            return <Table key={i} rows={block.lines} opts={opts} />;
          case "ul":
          case "ol": {
            const List = block.kind;
            return (
              <List key={i}>
                {block.lines.map((line, j) => (
                  <li key={j}>{spans(line, opts)}</li>
                ))}
              </List>
            );
          }
          default: {
            const Heading = block.kind;
            return <Heading key={i}>{spans(block.lines[0], opts)}</Heading>;
          }
        }
      })}
    </>
  );
}

function blocksOf(text: string): Block[] {
  const out: Block[] = [];
  let open: Block | null = null;
  let fence: Block | null = null;
  for (const raw of text.split("\n")) {
    if (fence) {
      if (FENCE.test(raw)) fence = null;
      else fence.lines.push(raw);
      continue;
    }
    if (FENCE.test(raw)) {
      fence = { kind: "pre", lines: [] };
      out.push(fence);
      open = null;
      continue;
    }
    if (!raw.trim()) {
      open = null;
      continue;
    }
    const heading = /^\s{0,3}(#{1,6})\s+(.*?)(?:\s+#+)?\s*$/.exec(raw);
    if (heading || /^\s{0,3}([-*_])(\s*\1){2,}\s*$/.test(raw)) {
      const level = Math.min(heading?.[1].length ?? 0, 4);
      out.push(heading ? { kind: `h${level}` as Block["kind"], lines: [heading[2]] } : { kind: "hr", lines: [] });
      open = null;
      continue;
    }
    const row = /^\s*\|.*\|\s*$/.test(raw);
    const quote = row ? null : /^\s*>\s?(.*)$/.exec(raw);
    const bullet = row || quote ? null : /^\s*[-*•]\s+(.*)$/.exec(raw);
    const number = row || quote || bullet ? null : /^\s*\d+[.)]\s+(.*)$/.exec(raw);
    const kind = row ? "table" : quote ? "quote" : bullet ? "ul" : number ? "ol" : "p";
    if (!open || open.kind !== kind) {
      open = { kind, lines: [] };
      out.push(open);
    }
    open.lines.push(row ? raw.trim() : ((quote ?? bullet ?? number)?.[1] ?? raw));
  }
  return out;
}

// A pipe table: a header row when a rule row (`| --- |`) follows it, then the body.
function Table({ rows, opts }: { rows: string[]; opts: Spans }) {
  const cells = (row: string) =>
    row
      .replace(/^\|/, "")
      .replace(/\|$/, "")
      .split(/(?<!\\)\|/)
      .map((cell) => cell.replace(/\\\|/g, "|").trim());
  const headed = rows.length > 1 && RULE_ROW.test(rows[1]);
  const body = (headed ? rows.slice(2) : rows).filter((row) => !RULE_ROW.test(row));
  return (
    <div className="table">
      <table>
        {headed && (
          <thead>
            <tr>
              {cells(rows[0]).map((cell, i) => (
                <th key={i}>{spans(cell, opts)}</th>
              ))}
            </tr>
          </thead>
        )}
        <tbody>
          {body.map((row, i) => (
            <tr key={i}>
              {cells(row).map((cell, j) => (
                <td key={j}>{spans(cell, opts)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function spans(text: string, opts: Spans): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  let at = 0;
  for (const match of text.matchAll(INLINE)) {
    const [whole, code, bold, link, bare, italic] = match;
    const start = match.index ?? 0;
    if (start > at) out.push(text.slice(at, start));
    const key = out.length;
    if (code) out.push(<code key={key}>{code.slice(1, -1)}</code>);
    else if (bold) out.push(<b key={key}>{spans(bold.slice(2, -2), opts)}</b>);
    else if (italic) out.push(<i key={key}>{spans(italic.slice(1, -1), opts)}</i>);
    else if (link) {
      const [, label, href] = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(link) ?? [];
      out.push(
        <Link key={key} href={href} opts={opts}>
          {spans(label, { ...opts, links: false })}
        </Link>,
      );
    } else if (bare)
      out.push(
        <Link key={key} href={bare} opts={opts}>
          {bare}
        </Link>,
      );
    at = start + whole.length;
  }
  if (at < text.length) out.push(text.slice(at));
  return out;
}

function Link({ href, opts, children }: { href: string; opts: Spans; children: React.ReactNode }) {
  if (!opts.links) return <>{children}</>;
  const local = opts.threadId ? localTarget(href, opts.threadId) : null;
  if (local) {
    return (
      <a
        href={local.url}
        onClick={(e) => {
          e.preventDefault();
          // The film this preview is the final look of, when its card is loaded: it names the
          // window and lets the render be signed off from it.
          const assets = useHouse.getState().details[local.threadId]?.assets ?? [];
          const film = assets.find((a) => a.preview?.port === local.port && a.preview.project === local.project);
          useHouse.getState().openPreview({ url: film?.preview?.url ?? local.url, title: film?.title ?? "Preview", threadId: local.threadId, assetId: film?.id });
        }}
      >
        {children}
      </a>
    );
  }
  if (/^https?:\/\//i.test(href)) {
    return (
      <a href={href} target="_blank" rel="noreferrer noopener">
        {children}
      </a>
    );
  }
  return <>{children}</>;
}

// A link to the thread's own computer (`http://localhost:3002/#project/video`), as the house's
// route that reaches it.
function localTarget(href: string, threadId: string) {
  let parsed: URL;
  try {
    parsed = new URL(href);
  } catch {
    return null;
  }
  if (!LOCAL_HOSTS.has(parsed.hostname) || !parsed.port) return null;
  const named = /^#project\/([^?&#/]+)/.exec(parsed.hash)?.[1];
  const project = named ? decodeURIComponent(named) : "";
  const query = project ? `?project=${encodeURIComponent(project)}` : "";
  return { url: `/api/threads/${threadId}/preview/${parsed.port}${query}`, threadId, port: Number(parsed.port), project };
}
