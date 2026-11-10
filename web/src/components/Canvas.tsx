// The channel's canvas, in place of Paper. Every task is a frame holding its work as a flow: what
// it started from, then each asset the agent makes (a storyboard, a teaser, thumbnails, cards),
// with a line from what each is made from. People review here (a note pinned to a frame, a board
// approved), add an asset made from any card, or place a template that sets several up at once;
// all of it reaches the agent in the task's thread. A research frame starts further back: questions
// about a repository, the conversations they grow into, and the notes its assets are made from.
import { ArrowLeft, Check, LayoutTemplate, Maximize, MessageSquare, Minus, Paperclip, Play, Plus, Send, Telescope } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api, type Asset, type Board, type CanvasTask, type Capability, type FileView, type FrameView, type Material, type Work } from "../api";
import { useHouse } from "../store";
import { Avatar, FileList, FooterLine, KindIcon, makesOf, StatusChip } from "../ui";
import { columnsOf, Lines, useLines, type Edge } from "./Flow";
import { EMPTY_RESEARCH, NOTES_NODE, ResearchColumns, researchEdges, researching, ResearchStart } from "./Research";
import { ChannelStart } from "./Start";
import { Templates } from "./Templates";

type Camera = { x: number; y: number; z: number };
const cameras: Record<string, Camera> = {};
const SOURCE = "source";
// What something on the canvas can be made from: a signed-off, delivered or dropped asset.
const READY = new Set(["approved", "done", "skipped"]);
// Pointer and wheel events from these belong to them, not to the canvas's pan and zoom.
const OWN_POINTER = "button, a, video, audio, textarea, input, label, .tf, .picker, .pop, .canvas-start";
const OWN_WHEEL = ".tf video, .picker, .pop, .canvas-start";

export function Canvas({ channelId }: { channelId: string }) {
  const tasks = useHouse((s) => s.canvas[channelId]);
  const channel = useHouse((s) => s.channels.find((c) => c.id === channelId));
  const picking = useHouse((s) => s.picking);
  const pickTemplate = useHouse((s) => s.pickTemplate);
  const view = useRef<HTMLDivElement>(null);
  const world = useRef<HTMLDivElement>(null);
  const [camera, setCamera] = useState<Camera>(cameras[channelId] ?? { x: 0, y: 0, z: 0.5 });
  const [dragging, setDragging] = useState(false);
  const [starting, setStarting] = useState<HTMLElement | null>(null);
  const fitted = useRef(Boolean(cameras[channelId]));
  // Until someone pans or zooms, the canvas keeps everything in view as work lands on it.
  const moved = useRef(Boolean(cameras[channelId]));
  const shape = (tasks ?? [])
    .map((t) => `${t.thread.id}:${t.assets.map((a) => `${a.id}.${a.status}.${a.files.length}.${a.board_id}.${a.preview ? 1 : 0}`).join(",")}:${t.boards.map((b) => `${b.frames.length}.${b.version}`).join(",")}:${t.work.filter((w) => w.status === "running").length}`)
    .join("|");

  useEffect(() => {
    cameras[channelId] = camera;
  }, [camera, channelId]);

  useEffect(() => () => pickTemplate(null), [channelId, pickTemplate]);

  const fit = useCallback(() => {
    const v = view.current;
    const w = world.current;
    if (!v || !w || !w.children.length) return;
    // Fit what is on the canvas (the frames), not the world's fixed width.
    const kids = Array.from(w.children) as HTMLElement[];
    const minX = Math.min(...kids.map((k) => k.offsetLeft));
    const minY = Math.min(...kids.map((k) => k.offsetTop));
    const width = Math.max(...kids.map((k) => k.offsetLeft + k.offsetWidth)) - minX;
    const height = Math.max(...kids.map((k) => k.offsetTop + k.offsetHeight)) - minY;
    const z = Math.max(0.12, Math.min(1, Math.min((v.clientWidth - 48) / width, (v.clientHeight - 96) / height)));
    setCamera({ z, x: (v.clientWidth - width * z) / 2 - minX * z, y: Math.max(72, (v.clientHeight - height * z) / 2) - minY * z });
  }, []);

  useLayoutEffect(() => {
    if (!tasks) return;
    if (!fitted.current || !moved.current) {
      fitted.current = true;
      requestAnimationFrame(fit);
    }
  }, [shape, tasks, fit]);

  const zoomAt = (factor: number, px: number, py: number) =>
    setCamera((c) => {
      moved.current = true;
      const z = Math.max(0.12, Math.min(2.5, c.z * factor));
      return { z, x: px - ((px - c.x) * z) / c.z, y: py - ((py - c.y) * z) / c.z };
    });

  useEffect(() => {
    const v = view.current;
    if (!v) return;
    const onWheel = (e: WheelEvent) => {
      if ((e.target as HTMLElement).closest(OWN_WHEEL)) return;
      e.preventDefault();
      const r = v.getBoundingClientRect();
      moved.current = true;
      if (e.ctrlKey || e.metaKey) zoomAt(Math.exp(-e.deltaY * 0.01), e.clientX - r.left, e.clientY - r.top);
      else setCamera((c) => ({ ...c, x: c.x - e.deltaX, y: c.y - e.deltaY }));
    };
    v.addEventListener("wheel", onWheel, { passive: false });
    return () => v.removeEventListener("wheel", onWheel);
  }, []);

  const onPointerDown = (e: React.PointerEvent) => {
    if (e.button !== 0 || (e.target as HTMLElement).closest(OWN_POINTER)) return;
    const start = { x: e.clientX, y: e.clientY, cx: camera.x, cy: camera.y };
    moved.current = true;
    setDragging(true);
    const move = (ev: PointerEvent) => setCamera((c) => ({ ...c, x: start.cx + ev.clientX - start.x, y: start.cy + ev.clientY - start.y }));
    const up = () => {
      setDragging(false);
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  const center = () => {
    const v = view.current;
    return v ? [v.clientWidth / 2, v.clientHeight / 2] : [0, 0];
  };

  const empty = tasks !== undefined && tasks.length === 0;
  return (
    <div className={`canvas ${dragging ? "dragging" : ""}`} ref={view} onPointerDown={onPointerDown} aria-label="Canvas">
      <div className="canvas-dots" style={{ backgroundSize: `${24 * camera.z}px ${24 * camera.z}px`, backgroundPosition: `${camera.x}px ${camera.y}px` }} />
      <div className="world" ref={world} style={{ transform: `translate(${camera.x}px, ${camera.y}px) scale(${camera.z})` }}>
        {tasks?.map((task) => <TaskFrame key={task.thread.id} task={task} />)}
      </div>
      {!empty && (
        <div className="canvas-bar">
          <button type="button" className="btn" aria-expanded={Boolean(starting)} onClick={(e) => setStarting(starting ? null : e.currentTarget)}>
            <Telescope />
            Research
          </button>
          <button type="button" className="btn" aria-expanded={Boolean(picking)} onClick={() => pickTemplate(picking ? null : {})}>
            <LayoutTemplate />
            Templates
          </button>
        </div>
      )}
      {starting && (
        <ResearchStart
          channelId={channelId}
          anchor={starting}
          onClose={() => {
            setStarting(null);
            moved.current = false;
          }}
        />
      )}
      <div className="zoom" aria-label="Zoom">
        <button type="button" className="icon-btn" aria-label="Zoom out" onClick={() => zoomAt(0.8, ...(center() as [number, number]))}>
          <Minus />
        </button>
        <output>{Math.round(camera.z * 100)}%</output>
        <button type="button" className="icon-btn" aria-label="Zoom in" onClick={() => zoomAt(1.25, ...(center() as [number, number]))}>
          <Plus />
        </button>
        <button
          type="button"
          className="icon-btn"
          aria-label="Fit everything"
          title="Fit everything"
          onClick={() => {
            moved.current = false;
            fit();
          }}
        >
          <Maximize />
        </button>
      </div>
      {/* An empty canvas starts where an empty chat does: the brand, then research or material. */}
      {empty && !picking && channel && (
        <div className="canvas-start">
          <ChannelStart channel={channel} />
        </div>
      )}
      {picking && (
        <Templates
          channelId={channelId}
          onPlaced={() => {
            moved.current = false;
          }}
        />
      )}
    </div>
  );
}

function TaskFrame({ task }: { task: CanvasTask }) {
  const people = useHouse((s) => s.people);
  const openThread = useHouse((s) => s.openThread);
  const [adding, setAdding] = useState<HTMLElement | null>(null);
  const { thread, work } = task;
  const titles = new Set(task.assets.map((a) => a.title));
  // A render named after an asset shows on its card; the strip holds the rest.
  const running = work.filter((w) => w.status === "running" && !(w.kind === "render" && titles.has(w.label)));
  const research = thread.kind === "research";
  return (
    <section className="tf" aria-label={thread.title}>
      <header className="tf-head">
        <Avatar person={people[thread.started_by]} size="sm" />
        <div style={{ minWidth: 0 }}>
          <h2>{thread.title}</h2>
          <FooterLine footer={thread.footer} />
        </div>
        <div className="actions">
          {research && researching(task.research) ? (
            <span className="chip green">
              <span className="spin" style={{ width: 10, height: 10, borderWidth: 1.5 }} />
              Researching
            </span>
          ) : (
            (!research || task.assets.length > 0) && <StatusChip status={thread.status} />
          )}
          <button type="button" className="btn" aria-expanded={Boolean(adding)} onClick={(e) => setAdding(adding ? null : e.currentTarget)}>
            <Plus />
            Add
          </button>
          <button type="button" className="btn" onClick={() => void openThread(thread.id)}>
            <MessageSquare />
            Thread
          </button>
        </div>
      </header>
      {running.length > 0 && <Running work={running} />}
      <TaskFlow task={task} />
      {adding && <MakeMenu task={task} anchor={adding} onClose={() => setAdding(null)} />}
    </section>
  );
}

function Running({ work }: { work: Work[] }) {
  return (
    <div className="tf-running" aria-label="Running">
      {work.map((w) => (
        <span key={w.id}>
          <span className="spin" />
          {w.kind === "render" ? `Rendering ${w.label || "the film"}` : w.label || "A helper"}
          {w.kind === "render" && w.fraction != null && <b>{Math.round(w.fraction * 100)}%</b>}
        </span>
      ))}
    </div>
  );
}

function TaskFlow({ task }: { task: CanvasTask }) {
  const { assets } = task;
  const box = useRef<HTMLDivElement>(null);
  const [hot, setHot] = useState<string | null>(null);
  const [making, setMaking] = useState<HTMLElement | null>(null);
  const research = task.thread.kind === "research" ? (task.research ?? EMPTY_RESEARCH) : null;
  const start = research ? NOTES_NODE : SOURCE;
  const columns = useMemo(() => columnsOf(assets), [assets]);
  const edges = useMemo<Edge[]>(() => {
    const byId = new Map(assets.map((a) => [a.id, a]));
    const made = assets.flatMap((a) => {
      const sources = a.sources.filter((s) => byId.has(s));
      if (!sources.length) return [{ from: start, to: a.id }];
      return sources.map((s) => ({ from: s, to: a.id, waiting: a.status === "planned" && !READY.has(byId.get(s)!.status) }));
    });
    return research ? [...researchEdges(research), ...made] : made;
  }, [assets, research, start]);
  const lines = useLines(box, edges);
  // A film's proof sheets arrive as deliveries before they are filed with its preview.
  const filed = new Set(assets.flatMap((a) => [...a.files, ...(a.preview?.proofs ?? [])].map((f) => f.id)));
  const loose = task.files.filter((f) => !filed.has(f.id));
  return (
    <div className="flow" ref={box}>
      <Lines lines={lines} hot={hot} />
      {research ? (
        <ResearchColumns task={task} research={research} onHot={setHot} onMake={setMaking} making={Boolean(making)} />
      ) : (
        <div className="flow-col">
          <SourceNode material={task.material} />
        </div>
      )}
      {making && <MakeMenu task={task} anchor={making} onClose={() => setMaking(null)} />}
      {columns.map((column, i) => (
        <div className="flow-col" key={i}>
          {column.map((asset) => (
            <AssetCard key={asset.id} asset={asset} task={task} onHot={setHot} />
          ))}
        </div>
      ))}
      {(loose.length > 0 || (assets.length === 0 && !research)) && (
        <div className="flow-col">
          {loose.length > 0 ? (
            <article className="node">
              <header className="node-head">
                <span className="node-icon">
                  <Paperclip size={16} />
                </span>
                <b>Delivered</b>
              </header>
              <div className="node-body">
                <FileList files={loose} large title="Delivered" />
              </div>
            </article>
          ) : (
            <p className="flow-empty">The agent is on it. What it makes lands here.</p>
          )}
        </div>
      )}
    </div>
  );
}

// What the task started from: the files someone brought and their words (a link, notes, the ask).
function SourceNode({ material }: { material: Material }) {
  const [first, ...rest] = material.text.split("\n");
  // A template's first line names it (the frame's title says so); the material is what follows.
  const words = rest.join("\n").trim() || (material.files.length ? "" : first);
  return (
    <article className="node source" data-node={SOURCE} aria-label="What this started from">
      <header className="node-head">
        <span className="node-icon">
          <Paperclip size={16} />
        </span>
        <b>Source</b>
      </header>
      <div className="node-body">
        {material.files.length > 0 && <FileList files={material.files} title="Source" />}
        {words && <p className="source-words">{words}</p>}
      </div>
    </article>
  );
}

const CHIPS: Partial<Record<Asset["status"], [string, string]>> = {
  review: ["amber", "For review"],
  changes: ["amber", "Notes sent"],
  approved: ["green", "Signed off"],
  done: ["green", "Delivered"],
  blocked: ["red", "Blocked"],
  skipped: ["", "Skipped"],
};

function AssetCard({ asset, task, onHot }: { asset: Asset; task: CanvasTask; onHot: (id: string | null) => void }) {
  const templates = useHouse((s) => s.catalog.templates);
  const [making, setMaking] = useState<HTMLElement | null>(null);
  // Two assets of one name in a task (a template placed onto it) are told apart by the template.
  const twin = task.assets.some((a) => a.id !== asset.id && a.title === asset.title);
  const from = twin ? templates.find((t) => t.id === asset.template)?.title : undefined;
  const board = task.boards.find((b) => b.id === asset.board_id);
  const finished = asset.files.length > 0 && (asset.status === "done" || !board);
  const reviewing = asset.preview && (asset.status === "review" || asset.status === "changes");
  const draft = isDraft(asset);
  const live = asset.status === "making" && task.thread.status === "working";
  const chip = CHIPS[asset.status];
  return (
    <article
      className="node"
      data-status={asset.status}
      data-node={asset.id}
      aria-label={asset.title}
      onMouseEnter={() => onHot(asset.id)}
      onMouseLeave={() => onHot(null)}
    >
      <header className="node-head">
        <span className="node-icon">
          <KindIcon kind={asset.kind} />
        </span>
        <b>
          {asset.title}
          {from && <span className="faint"> · {from}</span>}
        </b>
        {live ? (
          <span className="chip green">
            <span className="spin" style={{ width: 10, height: 10, borderWidth: 1.5 }} />
            Making
          </span>
        ) : (
          chip && <span className={`chip ${chip[0]}`}>{chip[1]}</span>
        )}
      </header>
      <div className="node-body">
        {reviewing ? (
          <FilmPreview asset={asset} />
        ) : finished ? (
          <>
            <Finals files={asset.files} title={asset.title} />
            {draft && <DraftActions asset={asset} />}
          </>
        ) : board ? (
          <BoardPreview board={board} />
        ) : null}
        <AssetLine asset={asset} task={task} live={live} />
      </div>
      <button
        type="button"
        className="port"
        aria-label={`Make something from ${asset.title}`}
        title="Make something from this"
        aria-expanded={Boolean(making)}
        onClick={(e) => setMaking(making ? null : e.currentTarget)}
      >
        <Plus />
      </button>
      {making && <MakeMenu task={task} from={asset} anchor={making} onClose={() => setMaking(null)} />}
    </article>
  );
}

// One line on where an asset stands, only where the card doesn't already show it.
function AssetLine({ asset, task, live }: { asset: Asset; task: CanvasTask; live: boolean }) {
  const turn = useHouse((s) => s.turns[asset.thread_id]);
  if (asset.status === "planned") {
    const byId = new Map(task.assets.map((a) => [a.id, a]));
    const waiting = asset.sources.map((s) => byId.get(s)).filter((s): s is Asset => Boolean(s && !READY.has(s.status)));
    const on = waiting.map((s) => `“${s.title}”${s.gate ? " sign-off" : ""}`).join(" and ");
    return (
      <>
        {asset.brief && <p className="node-brief">{asset.brief}</p>}
        <p className="node-line">{waiting.length ? `Waits for ${on}` : "Up next"}</p>
      </>
    );
  }
  if (asset.status === "making") {
    const render = task.work.find((w) => w.status === "running" && w.kind === "render" && w.label === asset.title);
    if (render) {
      const pct = render.fraction != null ? Math.round(render.fraction * 100) : null;
      return (
        <div className="node-render">
          <div className="bar-track">
            <div className="bar-fill" style={{ width: `${pct ?? 0}%` }} />
          </div>
          <p className="node-line">
            Rendering{pct != null ? ` · ${pct}%` : ""}
            {render.eta ? ` · ~${Math.max(1, Math.round(render.eta / 60))} min left` : ""}
          </p>
        </div>
      );
    }
    const step = live && turn?.data.state === "working" ? turn.data.header : "";
    return <p className="node-line">{live ? step || "Working on it" : "Started"}</p>;
  }
  if (asset.note && (["done", "blocked", "skipped"].includes(asset.status) || isDraft(asset))) {
    return <p className={`node-line ${asset.status === "blocked" ? "warn" : ""}`}>{asset.note}</p>;
  }
  return null;
}

// A draft (a timing preview, an animatic) is out for review on its own: no board, no Studio preview.
function isDraft(asset: Asset) {
  return asset.status === "review" && !asset.preview && !asset.board_id && asset.files.length > 0;
}

// A draft's sign-off: approving it has the agent make the final; notes go to it in the thread.
function DraftActions({ asset }: { asset: Asset }) {
  const openThread = useHouse((s) => s.openThread);
  const [busy, setBusy] = useState(false);
  const approve = async () => {
    setBusy(true);
    try {
      await api.approveDraft(asset.id);
    } catch (error) {
      useHouse.getState().say((error as Error).message);
    } finally {
      setBusy(false);
    }
  };
  // The thread opens with its reply box ready for the notes.
  const notes = async () => {
    await openThread(asset.thread_id);
    requestAnimationFrame(() => document.querySelector<HTMLTextAreaElement>("aside.thread .composer textarea")?.focus());
  };
  return (
    <div className="board-actions">
      <button type="button" className="btn primary" disabled={busy} onClick={() => void approve()}>
        <Check />
        Approve
      </button>
      <button type="button" className="btn" onClick={() => void notes()}>
        <Send />
        Send notes
      </button>
    </div>
  );
}

function BoardPreview({ board }: { board: Board }) {
  const openFrame = useHouse((s) => s.openFrame);
  const [hero, ...rest] = board.frames;
  const open = board.frames.flatMap((f) => f.comments.filter((c) => !c.parent_id && !c.resolved && !c.answered_in));
  const sentBack = board.frames.some((f) => f.verdict === "changes");
  if (!hero) return null;
  return (
    <div className="board-mini">
      <FrameTile frame={hero} onOpen={() => openFrame(hero.id, board.id)} />
      {rest.length > 0 && (
        <div className="strip">
          {rest.map((f) => (
            <button type="button" key={f.id} onClick={() => openFrame(f.id, board.id)} aria-label={`Review ${f.name}`} title={f.name}>
              <img src={f.versions[f.versions.length - 1]?.url} alt="" loading="lazy" />
            </button>
          ))}
        </div>
      )}
      {board.kind === "looks"
        ? board.status !== "approved" && <p className="node-line">Open a look to pick it, and say why.</p>
        : board.status !== "approved" && (
            <div className="board-actions">
              <button type="button" className="btn primary" onClick={() => void api.sendBoard(board.id, true)}>
                <Check />
                Approve
              </button>
              <button type="button" className="btn" disabled={!open.length && !sentBack} onClick={() => void api.sendBoard(board.id, false)}>
                <Send />
                {open.length ? `Send ${open.length} ${open.length === 1 ? "note" : "notes"}` : "Send notes"}
              </button>
            </div>
          )}
    </div>
  );
}

// A film before its render: its proof frames, the Studio preview it plays and is edited in, and
// the sign-off that renders it.
function FilmPreview({ asset }: { asset: Asset }) {
  const openPreview = useHouse((s) => s.openPreview);
  const [busy, setBusy] = useState(false);
  const shown = asset.preview!;
  const [hero] = shown.proofs;
  const watch = () => openPreview({ url: shown.url, title: asset.title, threadId: asset.thread_id, assetId: asset.id });
  const render = async () => {
    setBusy(true);
    try {
      await api.renderFilm(asset.id);
    } catch (error) {
      useHouse.getState().say((error as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="film-preview">
      <button type="button" className="film-hero" onClick={watch} aria-label={`Play ${asset.title}`}>
        {hero && <img src={hero.url} alt="" loading="lazy" />}
        <span className="play">
          <Play />
        </span>
      </button>
      <div className="board-actions">
        <button type="button" className="btn primary" disabled={busy} onClick={() => void render()}>
          <Check />
          Render it
        </button>
        <button type="button" className="btn" onClick={watch}>
          Watch and edit
        </button>
      </div>
    </div>
  );
}

// An asset's finished files: a film shows a frame to play, images show (the first large), the rest
// are files. Any of them opens full size, among the asset's other files.
function Finals({ files, title }: { files: FileView[]; title: string }) {
  const openFiles = useHouse((s) => s.openFiles);
  const video = files.find((f) => f.mime.startsWith("video/"));
  const audio = files.find((f) => f.mime.startsWith("audio/"));
  const images = files.filter((f) => f.mime.startsWith("image/"));
  const lead = video ? null : images[0];
  const others = images.filter((f) => f !== lead);
  const rest = files.filter((f) => f !== video && f !== audio && !images.includes(f));
  const open = (f: FileView) => openFiles({ files, at: f.id, title });
  return (
    <div className="finals">
      {video && (
        <button type="button" className="film-hero" onClick={() => open(video)} aria-label={`Play ${title}`}>
          {/* Two seconds in: a film's first frame is often its empty ground. */}
          <video src={`${video.url}#t=2`} preload="metadata" muted />
          <span className="play">
            <Play />
          </span>
        </button>
      )}
      {lead && (
        <button type="button" className="lead" title={lead.name} onClick={() => open(lead)}>
          <img src={lead.url} alt={lead.name} loading="lazy" />
        </button>
      )}
      {others.length > 0 && (
        <div className="strip">
          {others.map((f) => (
            <button type="button" key={f.id} title={f.name} onClick={() => open(f)}>
              <img src={f.url} alt={f.name} loading="lazy" />
            </button>
          ))}
        </div>
      )}
      {audio && <audio src={audio.url} controls preload="metadata" />}
      {rest.length > 0 && <FileList files={rest} among={files} title={title} />}
    </div>
  );
}

// What can be made next: from what the task started from (the frame's Add), or from one card
// (its port). A card that is finished also offers the templates that start from what it is.
function MakeMenu({ task, from, anchor, onClose }: { task: CanvasTask; from?: Asset; anchor: HTMLElement; onClose: () => void }) {
  const catalog = useHouse((s) => s.catalog);
  const pickTemplate = useHouse((s) => s.pickTemplate);
  const box = useRef<HTMLDivElement>(null);
  const [chosen, setChosen] = useState<Capability | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [place, setPlace] = useState<{ top: number; left: number } | null>(null);
  const media = from ? makesOf(from.kind) : "material";
  const kinds = catalog.capabilities.filter((c) => c.takes.includes(media));
  const finished = from && READY.has(from.status) && from.status !== "skipped";
  // A research frame's notes are what it started from; templates that start from material join it.
  const notes = !from && task.thread.kind === "research";
  const templates = finished || notes ? catalog.templates.filter((t) => t.starts_from.includes(media)) : [];

  useLayoutEffect(() => {
    const r = anchor.getBoundingClientRect();
    const height = box.current?.offsetHeight ?? 420;
    const width = box.current?.offsetWidth ?? 340;
    const left = from ? r.right + 10 : r.right - width;
    setPlace({
      top: Math.max(12, Math.min(window.innerHeight - height - 12, from ? r.top - 8 : r.bottom + 8)),
      left: Math.max(12, Math.min(window.innerWidth - width - 12, left)),
    });
  }, [anchor, from, chosen]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    const onDown = (e: PointerEvent) => {
      const target = e.target as Node;
      if (!box.current?.contains(target) && !anchor.contains(target)) onClose();
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("pointerdown", onDown);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("pointerdown", onDown);
    };
  }, [anchor, onClose]);

  const add = async () => {
    if (!chosen) return;
    setBusy(true);
    try {
      await api.addAsset(task.thread.id, { kind: chosen.id, sources: from ? [from.id] : [], note: note.trim() });
      onClose();
    } catch (error) {
      useHouse.getState().say((error as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const title = from ? `Make from “${from.title}”` : notes ? "Make from the notes" : "Add to this task";
  return createPortal(
    <div
      className="pop"
      ref={box}
      role="dialog"
      aria-label={title}
      style={place ? { top: place.top, left: place.left } : { visibility: "hidden", top: 0, left: 0 }}
    >
      {chosen ? (
        <>
          <header className="pop-head">
            <button type="button" className="icon-btn" aria-label="Back" onClick={() => setChosen(null)}>
              <ArrowLeft />
            </button>
            <KindIcon kind={chosen.id} />
            <b>{chosen.title}</b>
          </header>
          <p className="pop-line">{from ? `Made from “${from.title}”.` : notes ? "Made from the research notes." : "Made from what this task started from."}</p>
          <textarea
            autoFocus
            rows={3}
            value={note}
            placeholder="Anything it should know? (optional)"
            aria-label="Anything it should know?"
            onChange={(e) => setNote(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void add();
            }}
          />
          <div className="pop-actions">
            <button type="button" className="btn primary" disabled={busy} onClick={() => void add()}>
              Ask the agent
            </button>
          </div>
        </>
      ) : (
        <>
          <h3>{title}</h3>
          <div className="pop-list">
            {kinds.map((k) => (
              <button type="button" key={k.id} onClick={() => setChosen(k)}>
                <KindIcon kind={k.id} />
                <span>
                  <b>{k.title}</b>
                  <small>{k.line}</small>
                </span>
              </button>
            ))}
          </div>
          {templates.length > 0 && (
            <>
              <h3>Templates</h3>
              <div className="pop-list">
                {templates.map((t) => (
                  <button
                    type="button"
                    key={t.id}
                    onClick={() => {
                      pickTemplate(from ? { template: t.id, from: from.id } : { template: t.id, frame: task.thread.id });
                      onClose();
                    }}
                  >
                    <LayoutTemplate size={16} />
                    <span>
                      <b>{t.title}</b>
                      <small>{t.slots.map((s) => s.title).join(" · ")}</small>
                    </span>
                  </button>
                ))}
              </div>
            </>
          )}
        </>
      )}
    </div>,
    document.body,
  );
}

export function FrameTile({ frame, onOpen }: { frame: FrameView; onOpen: () => void }) {
  const current = frame.versions[frame.versions.length - 1];
  const roots = frame.comments.filter((c) => !c.parent_id);
  return (
    <button type="button" className="frame" onClick={onOpen} aria-label={`Review ${frame.name}`}>
      <span className="frame-art">
        {current && <img src={current.url} alt="" loading="lazy" />}
        {roots.map((c, i) =>
          c.x != null && c.y != null ? (
            <span key={c.id} className={`pin ${c.resolved ? "resolved" : c.answered_in ? "answered" : ""}`} style={{ left: `${c.x * 100}%`, top: `${c.y * 100}%` }}>
              {i + 1}
            </span>
          ) : null,
        )}
        <span className="frame-flag">
          {frame.verdict === "approved" ? (
            <span className="chip green">
              <Check />
              Approved
            </span>
          ) : frame.verdict === "changes" ? (
            <span className="chip amber">Changes</span>
          ) : null}
        </span>
      </span>
      <span className="frame-meta">
        <b>{frame.name}</b>
        <span className="ver">v{frame.version}</span>
        {roots.length > 0 && (
          <span className="faint" style={{ marginLeft: "auto", display: "inline-flex", gap: 4, alignItems: "center", fontSize: 12 }}>
            <MessageSquare size={13} />
            {roots.length}
          </span>
        )}
      </span>
    </button>
  );
}
