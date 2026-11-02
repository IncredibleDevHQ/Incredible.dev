// One thread: a task's whole conversation. People's messages, each agent turn as a live card of
// steps, the replies and files, the boards it put on the canvas, the work still running
// (helpers, renders, pipelines) and the footer, with a way to stop or steer it. A research
// conversation reads the same way, its answers with a way to keep them, or a passage, as notes.
import { Check, ChevronRight, CornerDownRight, LayoutDashboard, NotebookPen, Square, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, type Board, type ConversationRow, type Message, type Step, type Work } from "../api";
import { useHouse } from "../store";
import { AgentMark, Avatar, clock, FileList, FooterLine, kindTitle, Rich, StatusChip, StepIcon } from "../ui";
import { Composer } from "./Composer";
import { Folder } from "./Folder";
import { Passage } from "./Research";

const AGENT_TITLES: Record<string, string> = { claude: "Claude Code", codex: "Codex", kimi: "Kimi Code" };

export function ThreadPanel() {
  const { threadId, details, people } = useHouse();
  const openThread = useHouse((s) => s.openThread);
  const detail = threadId ? details[threadId] : undefined;
  const feed = useRef<HTMLDivElement>(null);
  const [tab, setTab] = useState<"talk" | "files">("talk");
  useEffect(() => setTab("talk"), [threadId]);

  const items = useMemo(() => {
    if (!detail) return [];
    const list: ({ at: number; message: Message } | { at: number; board: Board })[] = [
      ...detail.messages.filter((m) => !(m.kind === "turn" && m.data.state === "quiet")).map((m) => ({ at: m.created_at, message: m })),
      ...detail.boards.map((b) => ({ at: b.updated_at, board: b })),
    ];
    return list.sort((a, b) => a.at - b.at);
  }, [detail]);

  useEffect(() => {
    feed.current?.scrollTo({ top: feed.current.scrollHeight, behavior: "smooth" });
  }, [items.length]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // Escape closes what is on top first: a preview, a frame under review, a menu, the templates.
      const { frameId, picking, preview } = useHouse.getState();
      if (e.key === "Escape" && !frameId && !picking && !preview && !document.querySelector(".pop")) void openThread(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [openThread]);

  if (!threadId) return null;
  if (!detail) return <aside className="thread" aria-label="Thread"><div className="empty">Opening…</div></aside>;
  const { thread } = detail;
  const conversation = detail.conversation ?? null;
  const live = detail.work.filter((w) => w.status === "running");
  const turnRunning = detail.messages.some((m) => m.kind === "turn" && m.data.state === "working");

  return (
    <aside className="thread" aria-label="Thread">
      <header className="thread-bar">
        <div style={{ flex: 1, minWidth: 0 }}>
          <h2>{thread.title}</h2>
          <div className="meta">
            {thread.task ? (
              <StatusChip status={thread.status} />
            ) : conversation ? (
              <>
                <span className="chip">
                  <AgentMark mark={conversation.harness} size="sm" />
                  {AGENT_TITLES[conversation.harness]}
                </span>
                <span className="chip">{conversation.repo.split("/").pop()}</span>
              </>
            ) : (
              <span className="chip">Team thread</span>
            )}
            {kindTitle(thread.kind) && <span className="chip">{kindTitle(thread.kind)}</span>}
            {detail.boards.length > 0 && (
              <button type="button" className="chip" onClick={() => useHouse.getState().setMode("canvas")}>
                <LayoutDashboard />
                On the canvas
              </button>
            )}
          </div>
        </div>
        {turnRunning && (
          <button type="button" className="btn" title="Stop the agent at its next step" onClick={() => void api.stop(thread.id)}>
            <Square size={13} />
            Stop
          </button>
        )}
        <button type="button" className="icon-btn" aria-label="Close thread" onClick={() => void openThread(null)}>
          <X />
        </button>
      </header>
      {thread.task && (
        <div className="tabs" role="tablist" aria-label="Thread">
          <button type="button" role="tab" aria-selected={tab === "talk"} onClick={() => setTab("talk")}>
            Conversation
          </button>
          <button type="button" role="tab" aria-selected={tab === "files"} onClick={() => setTab("files")}>
            Files
          </button>
        </div>
      )}
      {tab === "files" ? (
        <div className="thread-feed">
          <Folder threadId={thread.id} />
        </div>
      ) : (
      <div className="thread-feed" ref={feed}>
        {items.map((item) =>
          "message" in item ? (
            <Item key={item.message.id} message={item.message} conversation={conversation} />
          ) : (
            <BoardCard key={`${item.board.id}-${item.board.version}`} board={item.board} />
          ),
        )}
      </div>
      )}
      {live.length > 0 && <Lanes work={live} threadId={thread.id} />}
      {thread.task && (
        <div className="thread-footer">
          <FooterLine footer={thread.footer} />
        </div>
      )}
      <Composer
        placeholder={thread.task ? "Reply to the agent: a note, a change, “stop”" : conversation ? "Ask a follow-up" : "Reply in the thread"}
        agentLabel="To the agent"
        allowTeam={thread.task}
        attach={!conversation}
        wait={conversation && turnRunning ? "Answering… ask again once it's done, or stop it." : undefined}
        onSend={async (body) => {
          await api.reply(thread.id, { text: body.text, to_agent: thread.task && body.to_agent, files: body.files });
        }}
      />
      <span className="sr-only">{people[thread.started_by]?.name}</span>
    </aside>
  );
}

function Item({ message, conversation }: { message: Message; conversation?: ConversationRow | null }) {
  const people = useHouse((s) => s.people);
  const text = useRef<HTMLDivElement>(null);
  if (message.kind === "turn") return <TurnCard message={message} />;
  const agent = message.author_id === "agent";
  const author = people[message.author_id];
  const state = message.data.state;
  const answer = conversation && message.kind === "agent" ? conversation : null;
  return (
    <article className="msg">
      {agent ? <AgentMark mark={message.data.mark} /> : <Avatar person={author} />}
      <div className="msg-body">
        <div className="msg-head">
          <strong>{agent ? "" : author?.name ?? "Someone"}</strong>
          <time>{clock(message.created_at)}</time>
          {!agent && !message.to_agent && message.id !== message.thread_id && <span className="chip">Team only</span>}
        </div>
        {message.data.quote && (
          <p className="msg-quote">
            <CornerDownRight size={13} />
            <span>“{message.data.quote}”</span>
          </p>
        )}
        {message.text &&
          (agent ? (
            <div className="msg-text agent rich" ref={text}>
              <Rich text={message.text} threadId={message.thread_id} />
            </div>
          ) : (
            <p className="msg-text">{message.text}</p>
          ))}
        {answer && message.text && (
          <>
            <Passage within={text} frameId={answer.frame_id} conversationId={answer.id} messageId={message.id} />
            <KeepAnswer message={message} conversation={answer} />
          </>
        )}
        <FileList files={message.data.files} large={agent} />
        {message.data.ask && <Answers message={message} />}
        {state === "queued" && <p className="queued">Waiting for the agent's next step…</p>}
        {state === "folded" && <p className="queued">Worked into the running turn.</p>}
        {state === "stop" && <p className="queued">Stopping at the agent's next step.</p>}
      </div>
    </article>
  );
}

// A research answer kept whole as a note (a passage of it is kept by selecting it).
function KeepAnswer({ message, conversation }: { message: Message; conversation: ConversationRow }) {
  const kept = useHouse((s) =>
    Object.values(s.canvas)
      .flat()
      .find((t) => t.thread.id === conversation.frame_id)
      ?.research?.notes.some((n) => n.message_id === message.id && n.text === message.text),
  );
  const keep = async () => {
    try {
      await api.keepNote(conversation.frame_id, { text: message.text, conversation_id: conversation.id, message_id: message.id });
    } catch (error) {
      useHouse.getState().say((error as Error).message);
    }
  };
  return (
    <div className="answer-tools">
      <button type="button" className="btn" disabled={kept} onClick={() => void keep()}>
        {kept ? <Check /> : <NotebookPen />}
        {kept ? "Kept as a note" : "Keep as a note"}
      </button>
      <span className="faint">or select a passage to keep or explore it</span>
    </div>
  );
}

// A question the engine waits on, answered with one click; the answer goes to the agent as your
// reply, and the question remembers who answered it.
function Answers({ message }: { message: Message }) {
  const people = useHouse((s) => s.people);
  const ask = message.data.ask!;
  const done = message.data.answered;
  if (done) {
    return (
      <p className="queued">
        {people[done.by]?.name ?? "Someone"} answered: <b>{done.text}</b>
      </p>
    );
  }
  return (
    <div className="board-actions" style={{ marginTop: 8, flexWrap: "wrap" }}>
      {ask.options.map((option, i) => (
        <button
          type="button"
          key={option}
          className={`btn ${i === 0 ? "primary" : ""}`}
          onClick={() => void api.reply(message.thread_id, { text: option, to_agent: true, files: [], answers: message.id })}
        >
          {option}
        </button>
      ))}
    </div>
  );
}

function TurnCard({ message }: { message: Message }) {
  const data = message.data;
  const working = data.state === "working";
  const [open, setOpen] = useState(working);
  useEffect(() => setOpen(working), [working]);
  const steps = data.steps ?? [];
  const header = working ? data.header || "Working" : data.state === "stopped" ? "Stopped" : data.woken ? "Picked up the background news" : "Done";
  const note = working ? data.notes?.[data.notes.length - 1] : undefined;
  return (
    <div className="turn" data-open={open}>
      <button type="button" className="turn-head" aria-expanded={open} onClick={() => setOpen(!open)}>
        <AgentMark mark={data.mark} size="sm" />
        <span className="what">{header}</span>
        {working ? <span className="spin" /> : <span className="faint" style={{ fontSize: 12 }}>{steps.length} steps</span>}
        <ChevronRight className="chev" />
      </button>
      {note && <p className="turn-note">{note}</p>}
      {open && steps.length > 0 && (
        <ol className="steps">
          {runs(steps).map(({ step: s, count }) => (
            <li key={s.id} data-status={s.status}>
              <StepIcon status={s.status} />
              {s.title}
              {count > 1 && <span className="faint">×{count}</span>}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

/** Back-to-back steps with the same words and state read once: "Studied the brand book ×3". */
function runs(steps: Step[]): { step: Step; count: number }[] {
  const out: { step: Step; count: number }[] = [];
  for (const step of steps) {
    const last = out[out.length - 1];
    if (last && last.step.title === step.title && last.step.status === step.status) last.count += 1;
    else out.push({ step, count: 1 });
  }
  return out;
}

function BoardCard({ board }: { board: Board }) {
  const openFrame = useHouse((s) => s.openFrame);
  const notes = board.frames.reduce((n, f) => n + f.comments.filter((c) => !c.parent_id && !c.resolved).length, 0);
  return (
    <section className="board-card" aria-label={`${board.title} board`}>
      <header>
        <LayoutDashboard size={15} className="muted" />
        <b>{board.title}</b>
        <span className="faint mono" style={{ fontSize: 11 }}>v{board.version}</span>
        <span style={{ marginLeft: "auto" }}>
          {board.status === "approved" ? <span className="chip green">Approved</span> : board.status === "changes" ? <span className="chip amber">Notes sent</span> : <span className="chip amber">For review</span>}
        </span>
      </header>
      <div className="frames-mini">
        {board.frames.map((f) => (
          <button type="button" key={f.id} style={{ padding: 0, border: 0, background: "none" }} onClick={() => openFrame(f.id, board.id)} aria-label={`Review ${f.name}`}>
            <img src={f.versions[f.versions.length - 1]?.url} alt="" />
          </button>
        ))}
      </div>
      <div className="board-actions" style={{ marginTop: 8 }}>
        <button type="button" className="btn" onClick={() => openFrame(board.frames[0]?.id ?? null, board.id)}>
          Review frames{notes ? ` · ${notes} ${notes === 1 ? "note" : "notes"}` : ""}
        </button>
      </div>
    </section>
  );
}

function Lanes({ work, threadId }: { work: Work[]; threadId: string }) {
  // Redrawn every half minute, so how long each job has run stays current between its updates.
  const [, tick] = useState(0);
  const [opened, setOpened] = useState<string | null>(null);
  useEffect(() => {
    const timer = window.setInterval(() => tick((n) => n + 1), 30_000);
    return () => window.clearInterval(timer);
  }, []);
  return (
    <div className="lanes" aria-label="Running in the background">
      {work.map((w) => {
        const step = [...w.steps].reverse().find((s) => s.status === "running") ?? w.steps[w.steps.length - 1];
        const minutes = Math.max(1, Math.round((Date.now() / 1000 - w.started_at) / 60));
        return (
          <div className="lane" key={w.id}>
            <span className="spin" />
            <b>{w.kind === "render" ? `Rendering ${w.label || "the film"}` : w.label || (w.kind === "pipeline" ? "Pipeline" : "A helper")}</b>
            <span style={{ display: "flex", gap: 6, alignItems: "center" }}>
              {w.effort && <span className="effort">{w.effort}</span>}
              {w.kind !== "render" && (
                <button type="button" className="linkish" style={{ fontSize: 12 }} onClick={() => void api.cancelWork(threadId, w.id)}>
                  Cancel
                </button>
              )}
            </span>
            {w.kind === "render" ? (
              <>
                <div className="bar-track">
                  <div className="bar-fill" style={{ width: `${Math.round((w.fraction ?? 0) * 100)}%` }} />
                </div>
                <small>
                  {w.phase || "starting"}
                  {w.fraction != null ? ` · ${Math.round(w.fraction * 100)}%` : ""}
                  {w.eta ? ` · ~${Math.max(1, Math.round(w.eta / 60))} min left` : ""}
                </small>
              </>
            ) : (
              <>
                <small>
                  {minutes} min in · {step?.title ?? "Working"}
                </small>
                {/* The helper's own account of where it is and what's left; a click reads it all. */}
                {w.note && (
                  <button
                    type="button"
                    className="lane-note"
                    aria-expanded={opened === w.id}
                    onClick={() => setOpened(opened === w.id ? null : w.id)}
                  >
                    <Rich text={w.note} inline />
                  </button>
                )}
              </>
            )}
          </div>
        );
      })}
    </div>
  );
}
