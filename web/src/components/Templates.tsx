// Templates on the canvas: predefined sets of assets wired together for a common job (a launch
// kit, a post turned into social). An empty channel's start opens them; a task's finished asset
// offers the ones that start from it. Placing one sets its assets up as a task, from what you bring
// (files, a link, notes) or from something already on the canvas, and the agent starts on it.
import { AlignLeft, ArrowLeft, BadgeCheck, FileText, Globe, LayoutTemplate, Paperclip, Telescope, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { api, type BrandPackView, type FileView, type Template } from "../api";
import { useFaces } from "../kit";
import { useHouse } from "../store";
import { KindIcon, makesOf } from "../ui";
import { columnsOf, Lines, useLines, type Edge } from "./Flow";
import { linksIn, siteOf } from "./Source";
import { lookOf, SlotArt, TemplateCover, type Look } from "./TemplateCover";
import { TextArea } from "./TextArea";

const FINISHED = new Set(["done", "approved"]);
const START = "start";
// Brand packs already read, so covers draw at once the next time the gallery opens.
const packs = new Map<string, BrandPackView>();
const sentence = (words: string) => words.charAt(0).toUpperCase() + words.slice(1);

export function Templates({ channelId, onPlaced }: { channelId: string; onPlaced: () => void }) {
  const templates = useHouse((s) => s.catalog.templates);
  const picking = useHouse((s) => s.picking);
  const pickTemplate = useHouse((s) => s.pickTemplate);
  const channel = useHouse((s) => s.channels.find((c) => c.id === channelId));
  const [selected, setSelected] = useState<string | null>(picking?.template ?? null);
  const chosen = templates.find((t) => t.id === selected);
  const panel = useRef<HTMLDivElement>(null);
  // Covers draw in the brand the channel wears, in its own faces.
  const slug = channel?.brand || "default";
  const [pack, setPack] = useState<BrandPackView | null>(packs.get(slug) ?? null);
  useEffect(() => {
    void api
      .brandPack(slug)
      .then((read) => {
        packs.set(slug, read);
        setPack(read);
      })
      .catch(() => undefined);
  }, [slug]);
  const type = useFaces(pack);
  const look = useMemo(() => lookOf(pack), [pack]);

  useEffect(() => setSelected(picking?.template ?? null), [picking?.template]);
  // A template opens at its top, not where the gallery was scrolled to.
  useEffect(() => {
    // A block, not an expression: scrollTo can return a promise, which React would take for a cleanup.
    panel.current?.scrollTo({ top: 0 });
  }, [selected]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || (e.target as HTMLElement).closest("textarea, input")) return;
      if (chosen && !picking?.template) setSelected(null);
      else pickTemplate(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [chosen, picking?.template, pickTemplate]);

  return (
    <div className="picker" role="dialog" aria-modal="true" aria-label="Templates">
      <div className="picker-panel" ref={panel} style={type.vars}>
        <style>{type.css}</style>
        <header className="picker-head">
          {chosen && !picking?.template && (
            <button type="button" className="icon-btn" aria-label="All templates" onClick={() => setSelected(null)}>
              <ArrowLeft />
            </button>
          )}
          <h2>{chosen ? chosen.title : "Templates"}</h2>
          <button type="button" className="icon-btn" aria-label="Close" onClick={() => pickTemplate(null)}>
            <X />
          </button>
        </header>
        {chosen ? (
          <Place
            key={chosen.id}
            template={chosen}
            look={look}
            channelId={channelId}
            from={picking?.from}
            frame={picking?.frame}
            onPlaced={() => {
              pickTemplate(null);
              setSelected(null);
              onPlaced();
            }}
          />
        ) : (
          <>
            {look.name && channel && (
              <p className="picker-lede">
                Shown in {look.name}, the brand #{channel.name} wears.
              </p>
            )}
            <div className="tpl-grid">
              {templates.map((t, i) => {
                const first = t.slots.find((s) => s.gate);
                return (
                  <button type="button" className="tpl" key={t.id} onClick={() => setSelected(t.id)}>
                    <TemplateCover template={t} look={look} tint={i} />
                    <span className="tpl-text">
                      <b>{t.title}</b>
                      <span className="tpl-gets" aria-label="What you get">
                        {t.slots
                          .filter((s) => !s.gate)
                          .map((s) => (
                            <span className="tpl-get" key={s.key}>
                              <KindIcon kind={s.kind} size={13} />
                              {s.gets || s.title}
                            </span>
                          ))}
                      </span>
                      {first && (
                        <span className="tpl-gate">
                          <BadgeCheck size={13} />
                          {first.gets ? `${sentence(first.gets)}.` : `${first.title} signed off first.`}
                        </span>
                      )}
                      <span className="tpl-from">
                        <Paperclip size={12} />
                        From {t.starts.charAt(0).toLowerCase() + t.starts.slice(1)}
                      </span>
                    </span>
                  </button>
                );
              })}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// A template's assets as they land on the canvas: a card for each, after what it is made from,
// drawn in the brand the channel wears and saying what it is; one the team signs off says so, and
// what is made from it waits, dashed. The source leads, showing what is brought. A light runs down
// the lines once, in the order the work is made (as affectUI's Integration Beam pulses along its
// beams), and a card in hand lights its own lines.
type Brought = { icon: ReactNode; label: string };
// Where lines meet a card: the middle of its picture (8px in, a 160×100 picture).
const ANCHOR = 58;

function TemplateFlow({ template, look, brought, empty }: { template: Template; look: Look; brought: Brought | null; empty: string }) {
  const box = useRef<HTMLDivElement>(null);
  const [hot, setHot] = useState<string | null>(null);
  const items = useMemo(() => template.slots.map((s) => ({ ...s, id: s.key })), [template]);
  const columns = useMemo(() => columnsOf(items), [items]);
  // Every template starts from something, as every task on the canvas does.
  const edges = useMemo<Edge[]>(
    () => items.flatMap((s) => (s.sources.length ? s.sources : [START]).map((from) => ({ from, to: s.id, waiting: items.some((g) => g.id === from && g.gate) }))),
    [items],
  );
  const lines = useLines(box, edges, ANCHOR);
  const step = (id: string) => (id === START ? 0 : columns.findIndex((c) => c.some((s) => s.id === id)) + 1);
  const hover = (id: string) => ({ onPointerEnter: () => setHot(id), onPointerLeave: () => setHot(null) });
  return (
    <div className="tpl-flow">
      <div className="tpl-flow-inner" ref={box}>
        <Lines lines={lines} hot={hot} />
        <svg className="tpl-pulses" aria-hidden="true">
          {lines.map((l) => (
            <path key={`${l.from}>${l.to}`} d={l.d} pathLength={100} style={{ "--step": step(l.from) } as CSSProperties} />
          ))}
        </svg>
        <div className="tpl-col">
          <div className="tpl-node source" data-node={START} data-brought={brought ? "" : undefined} {...hover(START)}>
            <span className="tpl-node-art">
              {brought?.icon ?? <Paperclip />}
              <span>{brought?.label ?? empty}</span>
            </span>
            <b className="tpl-node-title">Source</b>
            <span className="tpl-node-line">{template.starts}</span>
          </div>
        </div>
        {/* A column of more than two lays its cards out as rows, the picture beside the words. */}
        {columns.map((column, i) => (
          <div className={`tpl-col ${column.length > 2 ? "rows" : ""}`} key={i}>
            {column.map((slot, n) => (
              <div className="tpl-node" key={slot.id} data-node={slot.id} {...hover(slot.id)}>
                <SlotArt slot={slot} look={look} tint={i + n} />
                <b className="tpl-node-title">
                  <KindIcon kind={slot.kind} size={14} />
                  {slot.title}
                </b>
                <span className="tpl-node-line">{slot.brief}</span>
                {slot.gate && (
                  <span className="tpl-node-gate">
                    <BadgeCheck size={13} />
                    You sign it off first
                  </span>
                )}
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

// Placing one template: what it starts from (what you bring, a finished asset, or a research
// frame's notes), then the agent starts on it.
function Place({ template, look, channelId, from, frame, onPlaced }: { template: Template; look: Look; channelId: string; from?: string; frame?: string; onPlaced: () => void }) {
  const tasks = useHouse((s) => s.canvas[channelId]) ?? [];
  const channel = useHouse((s) => s.channels.find((c) => c.id === channelId));
  const worn = useHouse((s) => s.brands.find((b) => b.slug === (channel?.brand || "default")));
  const demo = useHouse((s) => s.session?.demo);
  const notesOf = tasks.find((t) => t.thread.id === frame);
  const canvas = tasks.flatMap((task) =>
    task.assets
      .filter((a) => FINISHED.has(a.status) && template.starts_from.includes(makesOf(a.kind)))
      .map((asset) => ({ asset, task: task.thread.title })),
  );
  const material = template.starts_from.includes("material");
  const [mode, setMode] = useState<"material" | "canvas">(from || !material ? "canvas" : "material");
  const [source, setSource] = useState(from ?? canvas[0]?.asset.id ?? "");
  const [text, setText] = useState("");
  const [files, setFiles] = useState<FileView[]>([]);
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const ready = frame ? true : mode === "canvas" ? Boolean(source) : Boolean(text.trim() || files.length);
  // A link brought is read before the agent starts: which pages, said as it is pasted.
  const links = linksIn(text);
  const sites = [...new Set(links.slice(0, 3).map(siteOf).filter(Boolean))].join(", ");
  const reads =
    links.length === 1
      ? `Reads the page at ${sites || "that link"}; the agent starts from its words.`
      : links.length > 1
        ? `Reads ${links.length > 3 ? "the first 3 links" : `${links.length} pages`} (${sites}); the agent starts from their words.`
        : undefined;
  // What the source card shows: what is brought so far.
  const picked = canvas.find((c) => c.asset.id === source)?.asset;
  const brings = [links.length === 1 ? sites || "a page" : links.length ? `${links.length} pages` : "", files.length === 1 ? files[0].name : files.length ? `${files.length} files` : ""].filter(Boolean);
  const brought: Brought | null = frame
    ? { icon: <Telescope />, label: "The research notes" }
    : mode === "canvas"
      ? picked
        ? { icon: <KindIcon kind={picked.kind} size={18} />, label: picked.title }
        : null
      : brings.length
        ? { icon: links.length ? <Globe /> : <FileText />, label: brings.join(" and ") }
        : text.trim()
          ? { icon: <AlignLeft />, label: "Your notes" }
          : null;

  const attach = async (list: FileList | null) => {
    if (!list?.length) return;
    try {
      const uploaded = await api.upload(Array.from(list));
      setFiles((f) => [...f, ...uploaded]);
    } catch (error) {
      useHouse.getState().say((error as Error).message);
    }
  };

  const place = async () => {
    setBusy(true);
    try {
      await api.placeTemplate(channelId, {
        template: template.id,
        text: text.trim(),
        files: mode === "material" && !frame ? files.map((f) => f.id) : [],
        from_asset: mode === "canvas" && !frame ? source : "",
        from_frame: frame ?? "",
      });
      useHouse.getState().say(`${template.title} is on the canvas. The agent is starting.`);
      onPlaced();
    } catch (error) {
      useHouse.getState().say((error as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const send = () => {
    if (ready && !busy) void place();
  };

  return (
    <div className="tpl-place">
      <p className="lede">{template.line}.</p>
      <TemplateFlow template={template} look={look} brought={brought} empty={material ? "Bring it below" : "None on the canvas yet"} />
      <section className="tpl-start" aria-label="Start from">
        <div className="tpl-start-head">
          <h3>Start from</h3>
          {material && canvas.length > 0 && !frame && (
            <div className="seg" role="group" aria-label="Start from">
              <button type="button" aria-pressed={mode === "material"} onClick={() => setMode("material")}>
                What you bring
              </button>
              <button type="button" aria-pressed={mode === "canvas"} onClick={() => setMode("canvas")}>
                On the canvas
              </button>
            </div>
          )}
        </div>
        {frame ? (
          <>
            <p className="muted">The notes of “{notesOf?.thread.title ?? "the research"}”: {notesOf?.research?.notes.length ?? 0} kept.</p>
            <TextArea minRows={2} maxRows={6} value={text} placeholder="Anything it should know? (optional)" aria-label="Anything it should know?" onSubmitShortcut={send} onChange={(e) => setText(e.target.value)} />
          </>
        ) : mode === "material" ? (
          <div
            className="drop"
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              void attach(e.dataTransfer.files);
            }}
          >
            <TextArea minRows={3} maxRows={10} value={text} placeholder="Paste a link or your notes" aria-label="Paste a link or your notes" hint={reads} onSubmitShortcut={send} onChange={(e) => setText(e.target.value)} />
            <div className="drop-row">
              <button type="button" className="btn" onClick={() => input.current?.click()}>
                <Paperclip />
                Attach files
              </button>
              {files.map((f) => (
                <span className="chip" key={f.id}>
                  {f.name}
                  <X role="button" aria-label={`Remove ${f.name}`} onClick={() => setFiles(files.filter((x) => x.id !== f.id))} />
                </span>
              ))}
              <input ref={input} type="file" multiple hidden onChange={(e) => void attach(e.target.files)} />
            </div>
          </div>
        ) : canvas.length ? (
          <>
            <div className="choices" role="radiogroup" aria-label="On the canvas">
              {canvas.map(({ asset, task }) => (
                <label key={asset.id} className={source === asset.id ? "on" : ""}>
                  <input type="radio" name="tpl-source" checked={source === asset.id} onChange={() => setSource(asset.id)} />
                  <KindIcon kind={asset.kind} />
                  <b>{asset.title}</b>
                  <small>{task}</small>
                </label>
              ))}
            </div>
            <TextArea minRows={2} maxRows={6} value={text} placeholder="Anything it should know? (optional)" aria-label="Anything it should know?" onSubmitShortcut={send} onChange={(e) => setText(e.target.value)} />
          </>
        ) : (
          <p className="muted">{template.starts}. Nothing like that is on this canvas yet.</p>
        )}
      </section>
      <footer className="tpl-foot">
        <span className="faint">
          {demo ? "Demo: the scripted agent makes the same sample work, not from what you bring." : `${worn ? `It wears ${worn.name}. ` : ""}The agent starts on it right away.`}
        </span>
        <button type="button" className="btn primary" disabled={!ready || busy} onClick={send}>
          <LayoutTemplate />
          {/* A link is read before the task starts, which takes a moment. */}
          {busy && /https?:\/\//.test(text) ? "Reading the page…" : "Place on the canvas"}
        </button>
      </footer>
    </div>
  );
}
