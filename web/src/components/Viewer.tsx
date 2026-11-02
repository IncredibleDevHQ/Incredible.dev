// A finished file over everything, at its size: a film plays, an image fits the window (a click
// shows a larger one at actual size), a document reads as a page. The rest of its set is a strip
// below; ← and → step through it, and Download saves the one shown.
import { ArrowLeft, ArrowRight, Download, Play, X } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { FileView } from "../api";
import { useHouse } from "../store";
import { FileGlyph, fileKind, fileSize, Rich } from "../ui";

export function Viewer() {
  const viewing = useHouse((s) => s.viewing);
  const openFiles = useHouse((s) => s.openFiles);
  const box = useRef<HTMLDivElement>(null);
  const open = Boolean(viewing);

  // Opening takes the keyboard; closing gives it back to what opened it (without moving the
  // canvas under it).
  useEffect(() => {
    if (!open) return;
    const before = document.activeElement as HTMLElement | null;
    box.current?.focus({ preventScroll: true });
    return () => before?.focus({ preventScroll: true });
  }, [open]);

  useEffect(() => {
    if (!viewing) return;
    const { files, at } = viewing;
    const index = files.findIndex((f) => f.id === at);
    const onKey = (e: KeyboardEvent) => {
      // On top of everything, so Escape closes this and nothing under it.
      if (e.key === "Escape") {
        e.stopPropagation();
        openFiles(null);
        return;
      }
      // A film being played keeps its own arrow keys.
      if ((e.target as HTMLElement).closest("video, audio")) return;
      const next = e.key === "ArrowRight" ? files[index + 1] : e.key === "ArrowLeft" ? files[index - 1] : undefined;
      if (next) openFiles({ ...viewing, at: next.id });
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [viewing, openFiles]);

  if (!viewing) return null;
  const { files, title } = viewing;
  const index = Math.max(0, files.findIndex((f) => f.id === viewing.at));
  const file = files[index];
  if (!file) return null;
  const show = (f: FileView) => openFiles({ ...viewing, at: f.id });
  const close = () => openFiles(null);
  return (
    <div className="viewer" role="dialog" aria-modal="true" aria-label={title ?? file.name} ref={box} tabIndex={-1}>
      <header className="viewer-bar">
        <h2>
          {title ?? file.name}
          {title && <span className="faint"> · {file.name}</span>}
        </h2>
        {files.length > 1 && (
          <>
            <span className="faint">
              {index + 1} of {files.length}
            </span>
            <button type="button" className="icon-btn" aria-label="Previous file" disabled={index === 0} onClick={() => show(files[index - 1])}>
              <ArrowLeft />
            </button>
            <button type="button" className="icon-btn" aria-label="Next file" disabled={index === files.length - 1} onClick={() => show(files[index + 1])}>
              <ArrowRight />
            </button>
          </>
        )}
        <a className="btn" href={file.url} download={file.name}>
          <Download />
          Download
        </a>
        <button type="button" className="icon-btn" aria-label="Close" onClick={close}>
          <X />
        </button>
      </header>
      <div className="viewer-stage" onClick={(e) => e.target === e.currentTarget && close()}>
        <Shown key={file.id} file={file} />
      </div>
      {files.length > 1 && (
        <div className="viewer-strip" role="group" aria-label="Files">
          {files.map((f) => (
            <button type="button" key={f.id} title={f.name} aria-label={f.name} aria-pressed={f.id === file.id} onClick={() => show(f)}>
              <Tile file={f} />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function Shown({ file }: { file: FileView }) {
  const kind = fileKind(file);
  if (kind === "image") return <Picture file={file} />;
  if (kind === "video") return <video src={file.url} controls autoPlay playsInline />;
  if (kind === "doc" || kind === "text") return <Page file={file} doc={kind === "doc"} />;
  return (
    <div className="viewer-card">
      <FileGlyph kind={kind} size={28} />
      <b>{file.name}</b>
      {kind === "audio" ? <audio src={file.url} controls autoPlay /> : <span>{fileSize(file.size)} · no preview for this kind of file</span>}
    </div>
  );
}

// An image fits the window. One larger than that shows at its actual size on a click, with the
// point clicked kept under the pointer.
function Picture({ file }: { file: FileView }) {
  const img = useRef<HTMLImageElement>(null);
  const aim = useRef<{ fx: number; fy: number; px: number; py: number } | null>(null);
  const [larger, setLarger] = useState(false);
  const [actual, setActual] = useState(false);

  useLayoutEffect(() => {
    const shown = img.current;
    const stage = shown?.parentElement;
    if (!actual || !shown || !stage || !aim.current) return;
    stage.scrollLeft = aim.current.fx * shown.offsetWidth - aim.current.px;
    stage.scrollTop = aim.current.fy * shown.offsetHeight - aim.current.py;
    aim.current = null;
  }, [actual]);

  const toggle = (e: React.MouseEvent<HTMLImageElement>) => {
    if (!larger) return;
    const stage = e.currentTarget.parentElement;
    if (!actual && stage) {
      const r = e.currentTarget.getBoundingClientRect();
      const s = stage.getBoundingClientRect();
      aim.current = { fx: (e.clientX - r.left) / r.width, fy: (e.clientY - r.top) / r.height, px: e.clientX - s.left, py: e.clientY - s.top };
    }
    setActual(!actual);
  };

  return (
    <img
      ref={img}
      src={file.url}
      alt={file.name}
      draggable={false}
      className={actual ? "actual" : larger ? "fits" : undefined}
      title={larger ? (actual ? "Fit to the window" : "Actual size") : undefined}
      onLoad={(e) => setLarger(e.currentTarget.naturalWidth > e.currentTarget.clientWidth + 1)}
      onClick={toggle}
    />
  );
}

// A document reads as a page: markdown as it is meant to look, any other text as it is.
function Page({ file, doc }: { file: FileView; doc: boolean }) {
  const [text, setText] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let live = true;
    fetch(file.url)
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error(r.statusText))))
      .then((t) => live && setText(t.slice(0, 400_000)))
      .catch(() => live && setFailed(true));
    return () => {
      live = false;
    };
  }, [file.url]);

  if (failed)
    return (
      <div className="viewer-card">
        <b>{file.name}</b>
        <span>It didn't open. Download it instead.</span>
      </div>
    );
  if (text === null) return <span className="spin" aria-label="Opening" />;
  return doc ? (
    <article className="viewer-doc rich">
      <Rich text={text} />
    </article>
  ) : (
    <pre className="viewer-doc">{text}</pre>
  );
}

function Tile({ file }: { file: FileView }) {
  const kind = fileKind(file);
  if (kind === "image") return <img src={file.url} alt="" loading="lazy" />;
  if (kind === "video")
    return (
      <>
        <video src={`${file.url}#t=2`} preload="metadata" muted />
        <span className="tile-play">
          <Play />
        </span>
      </>
    );
  return (
    <span className="ico">
      <FileGlyph kind={kind} size={15} />
      <small>{file.name}</small>
    </span>
  );
}
