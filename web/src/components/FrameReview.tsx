// Reviewing one frame of a board: click anywhere on it to pin a note there, compare versions,
// approve the frame or send it back, and send the board's notes to the agent when you're done.
// A brief's and a plan's frames are sections in words, so they open in their own review
// (PlanReview).
import { ArrowLeft, ArrowRight, Check, CornerDownRight, Send, Undo2, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, type Board, type Comment } from "../api";
import { useHouse } from "../store";
import { Avatar, clock } from "../ui";
import { PlanReview } from "./PlanReview";

export function FrameReview() {
  const { frameId, focusBoard, details, canvas, people } = useHouse();
  const openFrame = useHouse((s) => s.openFrame);
  const board: Board | undefined = useMemo(() => {
    const all = [...Object.values(details).flatMap((d) => d.boards), ...Object.values(canvas).flatMap((t) => t.flatMap((x) => x.boards))];
    return all.find((b) => b.id === focusBoard && b.frames.some((f) => f.id === frameId)) ?? all.find((b) => b.frames.some((f) => f.id === frameId));
  }, [details, canvas, frameId, focusBoard]);
  const frame = board?.frames.find((f) => f.id === frameId);
  const [version, setVersion] = useState<number | null>(null);
  const [draft, setDraft] = useState<{ x: number; y: number } | null>(null);
  const [text, setText] = useState("");
  const [hot, setHot] = useState<string | null>(null);
  const [replying, setReplying] = useState<string | null>(null);
  const [reply, setReply] = useState("");
  const [why, setWhy] = useState("");
  const note = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    setVersion(null);
    setDraft(null);
    setText("");
  }, [frameId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest("textarea, input")) return;
      if (e.key === "Escape") openFrame(null);
      if (!board || !frame || board.kind === "plan" || board.kind === "brief") return;
      const i = board.frames.findIndex((f) => f.id === frame.id);
      if (e.key === "ArrowRight" && board.frames[i + 1]) openFrame(board.frames[i + 1].id, board.id);
      if (e.key === "ArrowLeft" && board.frames[i - 1]) openFrame(board.frames[i - 1].id, board.id);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [board, frame, openFrame]);

  if (!board || !frame) return null;
  if (board.kind === "plan" || board.kind === "brief") return <PlanReview board={board} frame={frame} />;
  const index = board.frames.findIndex((f) => f.id === frame.id);
  const shown = frame.versions.find((v) => v.v === version) ?? frame.versions[frame.versions.length - 1];
  const roots = frame.comments.filter((c) => !c.parent_id);
  const repliesTo = (id: string) => frame.comments.filter((c) => c.parent_id === id);
  const openNotes = board.frames.flatMap((f) => f.comments.filter((c) => !c.parent_id && !c.resolved && !c.answered_in)).length;

  const place = (e: React.MouseEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    setDraft({ x: Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), y: Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)) });
    requestAnimationFrame(() => note.current?.focus());
  };

  const addNote = async () => {
    const words = text.trim();
    if (!words) return;
    await api.comment(frame.id, { text: words, x: draft?.x ?? null, y: draft?.y ?? null });
    setText("");
    setDraft(null);
  };

  const addReply = async (parent: Comment) => {
    const words = reply.trim();
    if (!words) return;
    await api.comment(frame.id, { text: words, parent_id: parent.id });
    setReply("");
    setReplying(null);
  };

  return (
    <div className="review" role="dialog" aria-modal="true" aria-label={`Review ${frame.name}`}>
      <div className="review-stage">
        <div className="review-top">
          <button type="button" className="icon-btn" aria-label="Close" onClick={() => openFrame(null)}>
            <X />
          </button>
          <h2>{board.title} · {frame.name}</h2>
          <span className="faint">
            {index + 1} of {board.frames.length}
          </span>
          <span style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
            <button type="button" className="icon-btn" aria-label="Previous frame" disabled={index === 0} onClick={() => openFrame(board.frames[index - 1].id, board.id)}>
              <ArrowLeft />
            </button>
            <button type="button" className="icon-btn" aria-label="Next frame" disabled={index === board.frames.length - 1} onClick={() => openFrame(board.frames[index + 1].id, board.id)}>
              <ArrowRight />
            </button>
          </span>
        </div>
        <div className="review-art" onClick={place} title="Click to pin a note here">
          <img src={shown?.url} alt={frame.name} draggable={false} />
          {roots.map((c, i) =>
            c.x != null && c.y != null ? (
              <span
                key={c.id}
                className={`pin ${c.resolved ? "resolved" : c.answered_in ? "answered" : ""}`}
                style={{ left: `${c.x * 100}%`, top: `${c.y * 100}%`, outline: hot === c.id ? "2px solid #fff" : undefined }}
                onMouseEnter={() => setHot(c.id)}
                onMouseLeave={() => setHot(null)}
              >
                {i + 1}
              </span>
            ) : null,
          )}
          {draft && <span className="draft-pin" style={{ left: `${draft.x * 100}%`, top: `${draft.y * 100}%` }} />}
        </div>
      </div>
      <aside className="review-side">
        <header>
          <div>
            <b>{frame.name}</b>
            {frame.note && <p className="muted" style={{ margin: "2px 0 0", fontSize: 13 }}>{frame.note}</p>}
          </div>
          {frame.versions.length > 1 && (
            <div className="versions" role="group" aria-label="Versions">
              {frame.versions.map((v) => (
                <button type="button" key={v.v} aria-pressed={shown?.v === v.v} onClick={() => setVersion(v.v)}>
                  v{v.v}
                </button>
              ))}
            </div>
          )}
          {board.kind === "looks" ? (
            <div style={{ display: "grid", gap: 8 }}>
              {frame.verdict === "approved" ? (
                <span className="chip green"><Check />Picked</span>
              ) : (
                <>
                  <div className="box">
                    <textarea rows={2} value={why} placeholder="Why this one? The agent learns from it." aria-label="Why this look" onChange={(e) => setWhy(e.target.value)} />
                  </div>
                  <button type="button" className="btn primary" onClick={() => void api.pickLook(board.id, frame.id, why).then(() => openFrame(null))}>
                    <Check />
                    Pick this look
                  </button>
                </>
              )}
            </div>
          ) : (
          <div style={{ display: "flex", gap: 8 }}>
            <button
              type="button"
              className={`btn ${frame.verdict === "approved" ? "primary" : ""}`}
              onClick={() => void api.verdict(frame.id, frame.verdict === "approved" ? "" : "approved")}
            >
              <Check />
              {frame.verdict === "approved" ? "Approved" : "Approve frame"}
            </button>
            <button
              type="button"
              className={`btn ${frame.verdict === "changes" ? "warn" : ""}`}
              onClick={() => void api.verdict(frame.id, frame.verdict === "changes" ? "" : "changes")}
            >
              <Undo2 />
              {frame.verdict === "changes" ? "Changes asked" : "Ask for changes"}
            </button>
          </div>
          )}
        </header>
        <div className="notes" aria-label="Notes">
          {roots.length === 0 && <p className="muted" style={{ padding: "8px 16px", margin: 0 }}>No notes yet. Click the frame to pin one where it applies.</p>}
          {roots.map((c, i) => (
            <div
              key={c.id}
              className={`note ${hot === c.id ? "hot" : ""} ${c.resolved ? "resolved" : ""} ${c.answered_in ? "answered" : ""}`}
              onMouseEnter={() => setHot(c.id)}
              onMouseLeave={() => setHot(null)}
            >
              <span className="n">{i + 1}</span>
              <div>
                <div className="msg-head">
                  <strong>{c.author}</strong>
                  <time>{clock(c.created_at)}</time>
                </div>
                <p>{c.text}</p>
              </div>
              <div className="row">
                <span className="mono">on v{c.version}</span>
                {c.answered_in ? <span className="chip green">Answered in v{c.answered_in}</span> : null}
                <button type="button" className="linkish" onClick={() => void api.resolve(c.id, !c.resolved)}>
                  {c.resolved ? "Reopen" : "Resolve"}
                </button>
                <button type="button" className="linkish" onClick={() => setReplying(replying === c.id ? null : c.id)}>
                  Reply
                </button>
              </div>
              {repliesTo(c.id).map((r) => (
                <div className="reply" key={r.id}>
                  <div className="msg-head">
                    <Avatar person={people[r.author_id]} size="sm" />
                    <strong>{r.author}</strong>
                  </div>
                  <p>{r.text}</p>
                </div>
              ))}
              {replying === c.id && (
                <div className="reply">
                  <div className="box">
                    <textarea rows={2} value={reply} autoFocus placeholder="Reply" onChange={(e) => setReply(e.target.value)} onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey) {
                        e.preventDefault();
                        void addReply(c);
                      }
                    }} />
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
        <div className="new-note">
          <p>{draft ? "Your note is pinned where you clicked." : "A note on the whole frame, or click the frame to pin it."}</p>
          <div className="box">
            <textarea
              ref={note}
              rows={2}
              value={text}
              placeholder="What should change?"
              aria-label="New note"
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void addNote();
                }
                if (e.key === "Escape") setDraft(null);
              }}
            />
            <div className="box-row">
              {draft && (
                <button type="button" className="linkish" style={{ fontSize: 12 }} onClick={() => setDraft(null)}>
                  Unpin
                </button>
              )}
              <button type="button" className="icon-btn send" aria-label="Add note" disabled={!text.trim()} onClick={() => void addNote()}>
                <CornerDownRight />
              </button>
            </div>
          </div>
          {board.status !== "approved" && board.kind !== "looks" && (
            <div className="board-actions">
              <button type="button" className="btn" disabled={!openNotes && !board.frames.some((f) => f.verdict === "changes")} onClick={() => void api.sendBoard(board.id, false).then(() => openFrame(null))}>
                <Send />
                Send {openNotes ? `${openNotes} ${openNotes === 1 ? "note" : "notes"}` : "changes"} to the agent
              </button>
              <button type="button" className="btn primary" onClick={() => void api.sendBoard(board.id, true).then(() => openFrame(null))}>
                <Check />
                Approve board
              </button>
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}
