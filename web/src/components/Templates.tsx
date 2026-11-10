// Templates on the canvas: predefined sets of assets wired together for a common job (a launch
// kit, a post turned into social). An empty channel's start opens them; a task's finished asset
// offers the ones that start from it. Placing one sets its assets up as a task, from what you bring
// (files, a link, notes) or from something already on the canvas, and the agent starts on it.
import { ArrowLeft, BadgeCheck, LayoutTemplate, Paperclip, X } from "lucide-react";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { api, type FileView, type Template } from "../api";
import { useHouse } from "../store";
import { KindIcon, makesOf } from "../ui";
import { columnsOf, Lines, useLines, type Edge } from "./Flow";

const FINISHED = new Set(["done", "approved"]);
const START = "start";

export function Templates({ channelId, onPlaced }: { channelId: string; onPlaced: () => void }) {
  const templates = useHouse((s) => s.catalog.templates);
  const picking = useHouse((s) => s.picking);
  const pickTemplate = useHouse((s) => s.pickTemplate);
  const [selected, setSelected] = useState<string | null>(picking?.template ?? null);
  const chosen = templates.find((t) => t.id === selected);

  useEffect(() => setSelected(picking?.template ?? null), [picking?.template]);

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
      <div className="picker-panel">
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
          <div className="tpl-grid">
            {templates.map((t) => (
              <button type="button" className="tpl" key={t.id} onClick={() => setSelected(t.id)}>
                <TemplateFlow template={t} />
                <b>{t.title}</b>
                <small>{t.line}</small>
                <span className="tpl-from">From {t.starts.charAt(0).toLowerCase() + t.starts.slice(1)}</span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// A template's assets as a small flow: what each is made from, and which the team signs off.
function TemplateFlow({ template, large, start = "Source" }: { template: Template; large?: boolean; start?: string }) {
  const frame = useRef<HTMLSpanElement>(null);
  const box = useRef<HTMLSpanElement>(null);
  const [fit, setFit] = useState<{ scale: number; height: number } | null>(null);
  const items = useMemo(() => template.slots.map((s) => ({ ...s, id: s.key })), [template]);
  const columns = useMemo(() => columnsOf(items), [items]);
  // Every template starts from something, as every task on the canvas does: what it is made from.
  const edges = useMemo<Edge[]>(
    () => items.flatMap((s) => (s.sources.length ? s.sources : [START]).map((from) => ({ from, to: s.id }))),
    [items],
  );
  const lines = useLines(box, edges, large ? 17 : 12);
  // A card's flow shrinks to the card's width rather than running off its edge.
  useLayoutEffect(() => {
    const outer = frame.current;
    const inner = box.current;
    if (large || !outer || !inner) return;
    const pad = parseFloat(getComputedStyle(outer).paddingLeft) * 2;
    const scale = Math.min(1, (outer.clientWidth - pad) / inner.scrollWidth);
    const height = Math.ceil(inner.offsetHeight * scale);
    if (!fit || Math.abs(fit.scale - scale) > 0.01 || fit.height !== height) setFit({ scale, height });
  });
  return (
    <span className={`tpl-flow ${large ? "large" : ""}`} ref={frame} style={fit ? { height: fit.height } : undefined}>
      <span className="tpl-flow-inner" ref={box} style={fit && fit.scale < 1 ? { transform: `scale(${fit.scale})` } : undefined}>
        <Lines lines={lines} />
        <span className="tpl-col">
          <span className="tpl-slot start" data-node={START} title={large ? undefined : template.starts}>
            <Paperclip size={large ? 15 : 12} aria-hidden="true" />
            {large && start}
          </span>
        </span>
        {columns.map((column, i) => (
          <span className="tpl-col" key={i}>
            {column.map((slot) => (
              <span className="tpl-slot" key={slot.id} data-node={slot.id} title={large ? undefined : slot.brief}>
                {large && <KindIcon kind={slot.kind} size={15} />}
                {slot.title}
                {slot.gate && <BadgeCheck className="gate" size={large ? 14 : 11} aria-label="signed off by the team first" />}
              </span>
            ))}
          </span>
        ))}
      </span>
    </span>
  );
}

// Placing one template: what it starts from (what you bring, a finished asset, or a research
// frame's notes), then the agent starts on it.
function Place({ template, channelId, from, frame, onPlaced }: { template: Template; channelId: string; from?: string; frame?: string; onPlaced: () => void }) {
  const tasks = useHouse((s) => s.canvas[channelId]) ?? [];
  const channel = useHouse((s) => s.channels.find((c) => c.id === channelId));
  const worn = useHouse((s) => s.brands.find((b) => b.slug === (channel?.brand || "default")));
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

  return (
    <div className="tpl-place">
      <p className="lede">{template.line}.</p>
      <TemplateFlow template={template} large start={frame ? "Notes" : mode === "canvas" ? canvas.find((c) => c.asset.id === source)?.asset.title : undefined} />
      <ul className="tpl-briefs">
        {template.slots.map((s) => (
          <li key={s.key}>
            <b>{s.title}</b> {s.brief}
          </li>
        ))}
      </ul>
      <section className="tpl-start" aria-label="Start from">
        <div className="tpl-start-head">
          <h3>Start from</h3>
          <span className="faint">{template.starts}</span>
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
            <textarea rows={2} value={text} placeholder="Anything it should know? (optional)" aria-label="Anything it should know?" onChange={(e) => setText(e.target.value)} />
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
            <textarea rows={4} value={text} placeholder="Paste a link or your notes" aria-label="Paste a link or your notes" onChange={(e) => setText(e.target.value)} />
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
            <textarea rows={2} value={text} placeholder="Anything it should know? (optional)" aria-label="Anything it should know?" onChange={(e) => setText(e.target.value)} />
          </>
        ) : (
          <p className="muted">{template.starts}. Nothing like that is on this canvas yet.</p>
        )}
      </section>
      <footer className="tpl-foot">
        <span className="faint">{worn ? `It wears ${worn.name}. ` : ""}The agent starts on it right away.</span>
        <button type="button" className="btn primary" disabled={!ready || busy} onClick={() => void place()}>
          <LayoutTemplate />
          Place on the canvas
        </button>
      </footer>
    </div>
  );
}
