import { Skeleton } from "./Skeleton";
// The task's project folder on the agent's computer, read-only. Everything the agent makes is
// code here (the brief, the plan, each pose's HTML, the composition, the renders), so a change is
// an edit and a re-render; this is where you can see it.
import { FileCode, FileImage, FileText, FileVideo, Folder as FolderIcon, RefreshCw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api, type FolderFile } from "../api";
import { fileSize } from "../ui";

const kindOf = (path: string) => {
  const ext = path.split(".").pop()?.toLowerCase() ?? "";
  if (["png", "jpg", "jpeg", "webp", "gif", "svg"].includes(ext)) return "image";
  if (["mp4", "webm", "mov"].includes(ext)) return "video";
  if (["md", "txt", "json", "html", "css", "js", "mjs", "toml", "csv", "log"].includes(ext)) return "text";
  return "other";
};

export function Folder({ threadId }: { threadId: string }) {
  const [files, setFiles] = useState<FolderFile[] | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [text, setText] = useState<string | null>(null);
  const [fileError, setFileError] = useState(false);

  const load = () => {
    setFiles(null);
    void api.folder(threadId).then(setFiles).catch(() => setFiles([]));
  };
  useEffect(load, [threadId]);

  useEffect(() => {
    let active = true;
    setFileError(false);
    setText(null);
    if (!open || kindOf(open) !== "text") return;
    void fetch(api.folderUrl(threadId, open))
      .then((r) => { if (!r.ok) throw new Error(); return r.text(); })
      .then((t) => { if (active) setText(t.slice(0, 200_000)); })
      .catch(() => { if (active) setFileError(true); });
    return () => { active = false; };
  }, [open, threadId]);

  const groups = useMemo(() => {
    const out: Record<string, FolderFile[]> = {};
    for (const f of files ?? []) {
      const parts = f.path.split("/");
      const dir = parts.length > 1 ? parts.slice(0, -1).join("/") : ".";
      (out[dir] ??= []).push(f);
    }
    return out;
  }, [files]);

  if (files === null) return <Skeleton label="Loading project files" />;
  if (!files.length) return <p className="muted" style={{ padding: "12px 16px" }}>Nothing in the project folder yet.</p>;

  const kind = open ? kindOf(open) : "";
  return (
    <div className="folder">
      <div className="folder-head">
        <span className="muted mono" style={{ fontSize: 12 }}>/workspace/projects</span>
        <button type="button" className="icon-btn" aria-label="Read again" onClick={load}>
          <RefreshCw />
        </button>
      </div>
      {open && (
        <div className="folder-preview">
          <div className="folder-head">
            <b className="mono" style={{ fontSize: 12, overflow: "hidden", textOverflow: "ellipsis" }}>{open}</b>
            <button type="button" className="linkish" onClick={() => setOpen(null)}>
              Close
            </button>
          </div>
          {kind === "image" && <img src={api.folderUrl(threadId, open)} alt="" />}
          {kind === "video" && <video src={api.folderUrl(threadId, open)} controls />}
          {kind === "text" && (fileError ? <p role="alert">Couldn’t read this file.</p> :
            text === null ? <Skeleton label="Loading file contents" /> : <pre>{text}</pre>)}
          {kind === "other" && (
            <a className="linkish" href={api.folderUrl(threadId, open)} target="_blank" rel="noreferrer">
              Download
            </a>
          )}
        </div>
      )}
      {Object.entries(groups).map(([dir, list]) => (
        <section key={dir}>
          <h4>
            <FolderIcon size={13} />
            {dir}
          </h4>
          <ul>
            {list.map((f) => {
              const k = kindOf(f.path);
              const Icon = k === "image" ? FileImage : k === "video" ? FileVideo : f.path.endsWith(".html") ? FileCode : FileText;
              return (
                <li key={f.path}>
                  <button type="button" aria-pressed={open === f.path} onClick={() => setOpen(f.path)}>
                    <Icon size={14} />
                    <span>{f.path.split("/").pop()}</span>
                    <small>{fileSize(f.size)}</small>
                  </button>
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </div>
  );
}
