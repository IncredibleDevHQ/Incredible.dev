// Research on the canvas: a frame that reads one of your repositories. Its first column asks a
// coding agent on this computer (Claude Code, Codex or Kimi Code, read-only, signed in as you);
// each question grows into a conversation, and a passage of any answer can be kept as a note or
// explored as a branch, which sits to the right of what it branched from. The notes are what
// everything made in the frame starts from.
import { ArrowUp, Check, CornerDownRight, FileText, FolderOpen, GitBranch, MessageSquare, NotebookPen, Pencil, Plus, Quote, Search, Telescope, X } from "lucide-react";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api, type CanvasTask, type Conversation, type Harness, type HarnessId, type Note, type ResearchView } from "../api";
import { useHouse } from "../store";
import { AgentMark, Rich } from "../ui";
import { columnsOf, type Edge } from "./Flow";

export const RESEARCH_NODE = "research";
export const NOTES_NODE = "notes";
const AGENTS: HarnessId[] = ["claude", "codex", "kimi"];
const AGENT_TITLES: Record<HarnessId, string> = { claude: "Claude Code", codex: "Codex", kimi: "Kimi Code" };
// A research frame the canvas has heard of before its research has arrived.
export const EMPTY_RESEARCH: ResearchView = { repo: { name: "", path: "", branch: "" }, harness: "claude", conversations: [], notes: [] };

const say = (error: unknown) => useHouse.getState().say((error as Error).message);

// The frame's lines: the research node to each first question, a conversation to its branches,
// and each conversation that gave a note to the notes. Until one has, the way there is dashed.
export function researchEdges(research: ResearchView): Edge[] {
  const out: Edge[] = research.conversations.map((c) => ({ from: c.parent_id || RESEARCH_NODE, to: c.id }));
  const feeding = research.conversations.filter((c) => c.kept > 0);
  if (feeding.length) out.push(...feeding.map((c) => ({ from: c.id, to: NOTES_NODE })));
  else out.push({ from: RESEARCH_NODE, to: NOTES_NODE, waiting: true });
  return out;
}

export const researching = (research?: ResearchView | null) => Boolean(research?.conversations.some((c) => c.status === "working"));

// The columns before a research frame's assets: the research node, its conversation trees, then
// the notes, whose port makes something from them.
export function ResearchColumns({
  task,
  research,
  onHot,
  onMake,
  making,
}: {
  task: CanvasTask;
  research: ResearchView;
  onHot: (id: string | null) => void;
  onMake: (anchor: HTMLElement | null) => void;
  making: boolean;
}) {
  const frameId = task.thread.id;
  const columns = useMemo(
    () => columnsOf(research.conversations.map((c) => ({ ...c, sources: c.parent_id ? [c.parent_id] : [] }))),
    [research.conversations],
  );
  return (
    <>
      <div className="flow-col">
        <ResearchNode frameId={frameId} research={research} />
      </div>
      {columns.map((column, i) => (
        <div className="flow-col" key={i}>
          {column.map((c) => (
            <ConversationCard key={c.id} frameId={frameId} conversation={c} notes={research.notes} onHot={onHot} />
          ))}
        </div>
      ))}
      <div className="flow-col">
        <NotesNode frameId={frameId} research={research} onHot={onHot} onMake={onMake} making={making} />
      </div>
    </>
  );
}

// The research node: the repository it reads, which agent answers, and a new question.
function ResearchNode({ frameId, research }: { frameId: string; research: ResearchView }) {
  const options = useHouse((s) => s.research);
  const [harness, setHarness] = useState<HarnessId>(research.harness);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!options) void useHouse.getState().loadResearch().catch(() => undefined);
  }, [options]);

  const ask = async () => {
    const words = question.trim();
    if (!words || busy) return;
    setBusy(true);
    try {
      await api.ask(frameId, { question: words, harness });
      setQuestion("");
    } catch (error) {
      say(error);
    } finally {
      setBusy(false);
    }
  };

  return (
    <article className="node research-node" data-node={RESEARCH_NODE} aria-label="Research">
      <header className="node-head">
        <span className="node-icon">
          <Telescope size={16} />
        </span>
        <b>Research</b>
      </header>
      <div className="node-body">
        <p className="repo-line" title={research.repo.path}>
          <GitBranch size={13} />
          <span>{research.repo.name}</span>
          {research.repo.within && <span className="faint">in {research.repo.within}</span>}
          {research.repo.branch && <span className="faint">{research.repo.branch}</span>}
        </p>
        <textarea
          className="ask-box"
          rows={2}
          value={question}
          placeholder={`Ask about ${research.repo.name || "the repository"}…`}
          aria-label="A new question"
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void ask();
            }
          }}
        />
        <div className="ask-row">
          <Agents value={harness} onChange={setHarness} known={options?.harnesses} />
          <button type="button" className="btn primary" disabled={!question.trim() || busy} onClick={() => void ask()}>
            <ArrowUp />
            Ask
          </button>
        </div>
      </div>
    </article>
  );
}

// Which agent answers, by its logo; one not installed on this computer can't be picked.
function Agents({ value, onChange, known, named }: { value: HarnessId; onChange: (id: HarnessId) => void; known?: Harness[]; named?: boolean }) {
  return (
    <div className={`agents ${named ? "named" : ""}`} role="radiogroup" aria-label="Which agent answers">
      {AGENTS.map((id) => {
        const off = known ? !known.find((h) => h.id === id)?.ready : false;
        return (
          <button
            type="button"
            role="radio"
            key={id}
            aria-checked={value === id}
            aria-label={AGENT_TITLES[id]}
            disabled={off}
            title={off ? `${AGENT_TITLES[id]} isn't installed on this computer` : AGENT_TITLES[id]}
            onClick={() => onChange(id)}
          >
            <AgentMark mark={id} size="sm" />
            {named && <span>{AGENT_TITLES[id]}</span>}
          </button>
        );
      })}
    </div>
  );
}

// One conversation: its question, what the agent is doing, the start of its answer (a passage of
// which can be kept or explored), and a way into the whole of it.
function ConversationCard({
  frameId,
  conversation: c,
  notes,
  onHot,
}: {
  frameId: string;
  conversation: Conversation;
  notes: Note[];
  onHot: (id: string | null) => void;
}) {
  const openThread = useHouse((s) => s.openThread);
  const answer = useRef<HTMLDivElement>(null);
  const working = c.status === "working";
  const keptWhole = notes.some((n) => n.message_id === c.answer_id && n.text === c.answer);
  const keep = async () => {
    try {
      await api.keepNote(frameId, { text: c.answer, conversation_id: c.id, message_id: c.answer_id });
    } catch (error) {
      say(error);
    }
  };
  return (
    <article
      className="node conv"
      data-node={c.id}
      data-status={c.status}
      aria-label={c.question}
      onMouseEnter={() => onHot(c.id)}
      onMouseLeave={() => onHot(null)}
    >
      <header className="node-head">
        <AgentMark mark={c.harness} size="sm" />
        <b title={c.question}>{c.question}</b>
        {working && <span className="spin" aria-label="Researching" />}
      </header>
      <div className="node-body">
        {c.quote && (
          <p className="conv-quote">
            <CornerDownRight size={13} />
            <span>“{c.quote}”</span>
          </p>
        )}
        {working && <p className="node-line conv-step">{c.step || "Starting"}</p>}
        {c.answer && c.follow_up && (
          <p className="conv-follow" title={c.follow_up}>
            <MessageSquare size={13} />
            <span>{c.follow_up}</span>
          </p>
        )}
        {c.answer && (
          <div className="conv-answer rich" ref={answer}>
            <Rich text={c.answer} />
          </div>
        )}
        {c.answer && <Passage within={answer} frameId={frameId} conversationId={c.id} messageId={c.answer_id} />}
        {c.problem && !working && <p className="node-line warn">{c.problem}</p>}
        <div className="conv-actions">
          <button type="button" className="btn" onClick={() => void openThread(c.id)}>
            <MessageSquare />
            Open
          </button>
          {c.answer && (
            <button type="button" className="btn" disabled={keptWhole} onClick={() => void keep()}>
              {keptWhole ? <Check /> : <NotebookPen />}
              {keptWhole ? "Kept" : "Keep"}
            </button>
          )}
          {c.kept > 0 && <span className="faint conv-kept">{c.kept} kept</span>}
        </div>
      </div>
    </article>
  );
}

// A passage selected in an answer: keep it as a note, or explore it in a new conversation that
// branches from this one.
export function Passage({
  within,
  frameId,
  conversationId,
  messageId,
}: {
  within: React.RefObject<HTMLElement | null>;
  frameId: string;
  conversationId: string;
  messageId: string;
}) {
  const [picked, setPicked] = useState<{ text: string; x: number; y: number } | null>(null);
  const [asking, setAsking] = useState(false);
  const [question, setQuestion] = useState("");
  const bar = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = within.current;
    if (!el) return;
    const read = () => {
      const selection = window.getSelection();
      if (!selection || selection.isCollapsed || !selection.rangeCount) return;
      const range = selection.getRangeAt(0);
      if (!el.contains(range.commonAncestorContainer)) return;
      wholeWords(range);
      selection.removeAllRanges();
      selection.addRange(range);
      const text = range.toString().trim();
      if (text.length < 3) return;
      const r = range.getBoundingClientRect();
      setPicked({ text, x: r.left + r.width / 2, y: r.top });
      setAsking(false);
      setQuestion("");
    };
    el.addEventListener("mouseup", read);
    el.addEventListener("keyup", read);
    return () => {
      el.removeEventListener("mouseup", read);
      el.removeEventListener("keyup", read);
    };
  }, [within]);

  useEffect(() => {
    if (!picked) return;
    const onDown = (e: PointerEvent) => {
      if (!bar.current?.contains(e.target as Node)) setPicked(null);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setPicked(null);
    };
    window.addEventListener("pointerdown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("pointerdown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [picked]);

  if (!picked) return null;
  const done = () => {
    setPicked(null);
    window.getSelection()?.removeAllRanges();
  };
  const keep = async () => {
    try {
      await api.keepNote(frameId, { text: picked.text, conversation_id: conversationId, message_id: messageId });
      done();
    } catch (error) {
      say(error);
    }
  };
  const explore = async () => {
    if (!question.trim()) return;
    try {
      await api.ask(frameId, { question: question.trim(), parent: conversationId, quote: picked.text });
      done();
    } catch (error) {
      say(error);
    }
  };
  return createPortal(
    <div className="passage" ref={bar} style={{ left: picked.x, top: picked.y }} role="toolbar" aria-label="The selected passage">
      {asking ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void explore();
          }}
        >
          <input autoFocus value={question} placeholder="What should it find out about this?" aria-label="A question about the passage" onChange={(e) => setQuestion(e.target.value)} />
          <button type="submit" className="icon-btn send" aria-label="Ask" disabled={!question.trim()}>
            <ArrowUp />
          </button>
        </form>
      ) : (
        <>
          <button type="button" onClick={() => void keep()}>
            <NotebookPen />
            Keep
          </button>
          <button type="button" onClick={() => setAsking(true)}>
            <GitBranch />
            Explore
          </button>
        </>
      )}
    </div>,
    document.body,
  );
}

// A selection that starts or ends inside a word takes the whole word.
function wholeWords(range: Range) {
  const word = /[\p{L}\p{N}_'’-]/u;
  if (range.startContainer.nodeType === Node.TEXT_NODE) {
    const text = range.startContainer.textContent ?? "";
    let at = range.startOffset;
    while (at > 0 && word.test(text[at - 1])) at--;
    range.setStart(range.startContainer, at);
  }
  if (range.endContainer.nodeType === Node.TEXT_NODE) {
    const text = range.endContainer.textContent ?? "";
    let at = range.endOffset;
    while (at < text.length && word.test(text[at])) at++;
    range.setEnd(range.endContainer, at);
  }
}

// The notebook: what was kept from the answers and what the team wrote, each with where it came
// from. Its port makes something from the notes.
function NotesNode({
  frameId,
  research,
  onHot,
  onMake,
  making,
}: {
  frameId: string;
  research: ResearchView;
  onHot: (id: string | null) => void;
  onMake: (anchor: HTMLElement | null) => void;
  making: boolean;
}) {
  const people = useHouse((s) => s.people);
  const [draft, setDraft] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const asked = new Map(research.conversations.map((c) => [c.id, c]));
  const add = async () => {
    const words = draft.trim();
    if (!words) return;
    try {
      await api.keepNote(frameId, { text: words });
      setDraft("");
    } catch (error) {
      say(error);
    }
  };
  return (
    <article className="node notes-node" data-node={NOTES_NODE} aria-label="Notes" onMouseEnter={() => onHot(NOTES_NODE)} onMouseLeave={() => onHot(null)}>
      <header className="node-head">
        <span className="node-icon">
          <NotebookPen size={16} />
        </span>
        <b>Notes</b>
        {research.notes.length > 0 && <span className="chip">{research.notes.length}</span>}
      </header>
      <div className="node-body">
        {research.notes.length === 0 && <p className="node-line">Select a passage in an answer to keep it here.</p>}
        {research.notes.map((n) => (
          <NoteRow
            key={n.id}
            note={n}
            from={asked.get(n.conversation_id)}
            author={people[n.author_id]?.name}
            editing={editing === n.id}
            onEdit={(on) => setEditing(on ? n.id : null)}
          />
        ))}
        <div className="note-new">
          <textarea
            rows={1}
            value={draft}
            placeholder="Write a note"
            aria-label="Write a note"
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void add();
              }
            }}
          />
          <button type="button" className="icon-btn" aria-label="Add the note" disabled={!draft.trim()} onClick={() => void add()}>
            <Plus />
          </button>
        </div>
      </div>
      <button
        type="button"
        className="port"
        aria-label="Make something from the notes"
        title="Make something from the notes"
        aria-expanded={making}
        onClick={(e) => onMake(making ? null : e.currentTarget)}
      >
        <Plus />
      </button>
    </article>
  );
}

function NoteRow({
  note,
  from,
  author,
  editing,
  onEdit,
}: {
  note: Note;
  from?: Conversation;
  author?: string;
  editing: boolean;
  onEdit: (on: boolean) => void;
}) {
  const [text, setText] = useState(note.text);
  const [open, setOpen] = useState(false);
  const long = note.text.length > 320;
  useEffect(() => setText(note.text), [note.text]);
  const save = async () => {
    try {
      await api.editNote(note.id, text);
      onEdit(false);
    } catch (error) {
      say(error);
    }
  };
  return (
    <div className="note-row">
      {editing ? (
        <>
          <textarea rows={5} value={text} autoFocus aria-label="The note" onChange={(e) => setText(e.target.value)} />
          <div className="note-edit">
            <button type="button" className="btn" onClick={() => onEdit(false)}>
              Cancel
            </button>
            <button type="button" className="btn primary" disabled={!text.trim()} onClick={() => void save()}>
              Save
            </button>
          </div>
        </>
      ) : (
        <div className={`note-text rich ${long && !open ? "clamped" : ""}`}>
          <Rich text={note.text} />
        </div>
      )}
      <p className="note-from">
        <span className="note-kind" title={note.kind === "answer" ? "The whole answer" : note.kind === "passage" ? "A passage of the answer" : "Written by the team"}>
          {note.kind === "answer" ? <FileText size={12} /> : note.kind === "passage" ? <Quote size={12} /> : <Pencil size={12} />}
        </span>
        {from ? (
          <Lineage steps={note.lineage} />
        ) : (
          <span className="lineage-step">{author ? `Written by ${author}` : "Written here"}</span>
        )}
        <span className="note-tools">
          {long && !editing && (
            <button type="button" className="linkish" onClick={() => setOpen(!open)}>
              {open ? "Less" : "All"}
            </button>
          )}
          <button type="button" className="icon-btn" aria-label="Edit the note" onClick={() => onEdit(true)}>
            <Pencil />
          </button>
          <button type="button" className="icon-btn" aria-label="Remove the note" onClick={() => void api.dropNote(note.id).catch(say)}>
            <X />
          </button>
        </span>
      </p>
    </div>
  );
}

// Where a note came from: the repository, then each conversation down to the one it was kept from.
function Lineage({ steps }: { steps: Note["lineage"] }) {
  return (
    <span className="lineage" title={steps.map((s) => s.label + (s.detail ? ` (${s.detail})` : "")).join(" › ")}>
      {steps.map((step, i) => (
        <span key={i} className={`lineage-step ${step.kind}`}>
          {i > 0 && <i aria-hidden="true">›</i>}
          {step.kind === "repo" ? (
            <GitBranch size={11} />
          ) : step.kind === "follow_up" ? (
            <MessageSquare size={11} />
          ) : (
            step.harness && <AgentMark mark={step.harness} size="sm" />
          )}
          <span>{step.label}</span>
        </span>
      ))}
    </span>
  );
}

// Starting research from the canvas: which repository, which agent, and the first question.
export function ResearchStart({ channelId, anchor, onClose, onStarted }: { channelId: string; anchor: HTMLElement; onClose: () => void; onStarted?: () => void }) {
  const options = useHouse((s) => s.research);
  const box = useRef<HTMLDivElement>(null);
  const search = useRef<HTMLInputElement>(null);
  const ask = useRef<HTMLTextAreaElement>(null);
  const [query, setQuery] = useState("");
  const [repo, setRepo] = useState("");
  const [harness, setHarness] = useState<HarnessId>("claude");
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [place, setPlace] = useState<{ top: number; left: number } | null>(null);

  useEffect(() => {
    void useHouse
      .getState()
      .loadResearch()
      .then((found) => {
        setRepo((r) => r || found.repos[0]?.path || "");
        setHarness((h) => (found.harnesses.find((x) => x.id === h)?.ready ? h : (found.harnesses.find((x) => x.ready)?.id ?? h)));
      })
      .catch(say);
  }, []);

  // Below its button, moved up as far as it must to stay on screen. Its list keeps one height, so
  // the card never grows or moves while someone searches and picks.
  useLayoutEffect(() => {
    const r = anchor.getBoundingClientRect();
    const width = box.current?.offsetWidth ?? 380;
    const height = box.current?.offsetHeight ?? 480;
    setPlace({
      top: Math.max(12, Math.min(r.bottom + 8, window.innerHeight - 12 - height)),
      left: Math.max(12, Math.min(window.innerWidth - width - 12, r.left)),
    });
  }, [anchor]);

  // The search takes the keyboard once, when the card is placed (a hidden field can't be focused).
  const placed = Boolean(place);
  useEffect(() => {
    if (placed) search.current?.focus();
  }, [placed]);

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

  const wanted = query.trim().toLowerCase();
  const shown = (options?.repos ?? []).filter((r) => r.name.toLowerCase().includes(wanted));
  const folder = /[/~]/.test(query);
  const chosen = folder && repo === query.trim() ? query.trim().split("/").filter(Boolean).pop() : options?.repos.find((r) => r.path === repo)?.name;
  // A search that hides the picked repository picks its first match instead, so what will be read
  // is always in sight; picking one, by click or Enter, moves on to the question.
  const find = (text: string) => {
    setQuery(text);
    const matches = (options?.repos ?? []).filter((r) => r.name.toLowerCase().includes(text.trim().toLowerCase()));
    if (!/[/~]/.test(text) && matches.length && !matches.some((r) => r.path === repo)) setRepo(matches[0].path);
  };
  const choose = (path: string) => {
    setRepo(path);
    ask.current?.focus();
  };
  const start = async () => {
    if (!repo || !question.trim() || busy) return;
    setBusy(true);
    try {
      await api.openResearch(channelId, { repo, harness, question: question.trim() });
      onStarted?.();
      onClose();
    } catch (error) {
      say(error);
    } finally {
      setBusy(false);
    }
  };
  return createPortal(
    <div
      className="pop research-start"
      ref={box}
      role="dialog"
      aria-label="Research a repository"
      style={place ? { top: place.top, left: place.left } : { visibility: "hidden", top: 0, left: 0 }}
    >
      <h3>Research a repository</h3>
      <label className="repo-find">
        <Search size={14} />
        <input
          ref={search}
          value={query}
          placeholder="Find a repository"
          aria-label="Find a repository"
          onChange={(e) => find(e.target.value)}
          onKeyDown={(e) => {
            if (e.key !== "Enter") return;
            e.preventDefault();
            if (folder) choose(query.trim());
            else if (repo) ask.current?.focus();
          }}
        />
      </label>
      <div className="repo-list" role="listbox" aria-label="Repositories">
        {!options && <p className="muted">Looking for repositories…</p>}
        {options && !shown.length && !folder && <p className="muted">No repository matches. Type a folder's path to research one inside a repository.</p>}
        {folder && (
          <button type="button" role="option" aria-selected={repo === query.trim()} title={query.trim()} onClick={() => choose(query.trim())}>
            <FolderOpen size={14} />
            <b>{query.trim().split("/").filter(Boolean).pop()}</b>
            <small>this folder</small>
          </button>
        )}
        {shown.map((r) => (
          <button type="button" role="option" aria-selected={repo === r.path} key={r.path} title={r.path} onClick={() => choose(r.path)}>
            <GitBranch size={14} />
            <b>{r.name}</b>
            <small>{r.branch}</small>
          </button>
        ))}
      </div>
      <Agents value={harness} onChange={setHarness} known={options?.harnesses} named />
      <textarea
        ref={ask}
        rows={3}
        value={question}
        placeholder={chosen ? `What should it find out about ${chosen}?` : "What should it find out?"}
        aria-label="The first question"
        onChange={(e) => setQuestion(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void start();
        }}
      />
      <div className="pop-actions">
        <span className="faint">Read-only, on this computer</span>
        <button type="button" className="btn primary" disabled={!repo || !question.trim() || busy} onClick={() => void start()}>
          <Telescope />
          Start research
        </button>
      </div>
    </div>,
    document.body,
  );
}
