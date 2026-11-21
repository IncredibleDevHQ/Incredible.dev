import { Skeleton } from "./Skeleton";
// Research on the canvas: a frame that reads one of your repositories. Its first column asks a
// coding agent on this computer (Claude Code, Codex or Kimi Code, read-only, signed in as you),
// on a model and effort it offers, picked as an episode's writer is; each question grows into a
// conversation, and a passage of any answer can be kept as a note or explored as a branch, which
// sits to the right of what it branched from. The notes are what everything made in the frame
// starts from, and read as one page in the viewer.
import { isWorkspaceTarget } from "./workspaceTarget";
import { ArrowUp, BookOpen, Check, CornerDownRight, FileText, FolderOpen, GitBranch, MessageSquare, NotebookPen, Paperclip, Pencil, Plus, Quote, Reply, Search, Telescope, X } from "lucide-react";
import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api, type CanvasTask, type Conversation, type Harness, type HarnessId, type FileView, type RepoView, type Note, type ResearchView } from "../api";
import { useFocused, useHouse } from "../store";
import { AgentMark, FileList, Rich } from "../ui";
import { AgentModel, offersPicks, shownPick, type ModelPick } from "./episode/AgentModel";
import { columnsOf, type Edge } from "./Flow";
import { ThinkingLoader } from "./ThinkingLoader";
import { Tooltip } from "./Tooltip";

export const RESEARCH_NODE = "research";
export const NOTES_NODE = "notes";
const AGENTS: HarnessId[] = ["claude", "codex", "kimi"];
const AGENT_TITLES: Record<HarnessId, string> = { claude: "Claude Code", codex: "Codex", kimi: "Kimi Code" };
// A research frame the canvas has heard of before its research has arrived.
export const EMPTY_RESEARCH: ResearchView = { repo: { name: "", path: "", branch: "" }, harness: "claude", model: "", effort: "", conversations: [], notes: [] };
// No model or effort picked: the agent's own default.
const DEFAULT_PICK: ModelPick = { model: "", effort: "" };

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

// The research node: the repository it reads, a new question, which agent answers and on what
// model and effort. It starts from the pick the frame last asked with, and goes back to it
// whenever another question is asked.
function ResearchNode({ frameId, research }: { frameId: string; research: ResearchView }) {
  const options = useHouse((s) => s.research);
  const focused = useFocused(frameId, RESEARCH_NODE);
  const [harness, setHarness] = useState<HarnessId>(research.harness);
  const [pick, setPick] = useState<ModelPick>({ model: research.model, effort: research.effort });
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const models = options?.models[harness];

  useEffect(() => {
    if (!options) void useHouse.getState().loadResearch().catch(() => undefined);
  }, [options]);

  useEffect(() => {
    setHarness(research.harness);
    setPick({ model: research.model, effort: research.effort });
  }, [research.harness, research.model, research.effort]);

  // models are each agent's own, so another agent starts on its default
  const choose = (id: HarnessId) => {
    if (id === harness) return;
    setHarness(id);
    setPick(DEFAULT_PICK);
  };

  const ask = async () => {
    const words = question.trim();
    if (!words || busy) return;
    setBusy(true);
    try {
      await api.ask(frameId, { question: words, harness, ...shownPick(models, pick) });
      setQuestion("");
    } catch (error) {
      say(error);
    } finally {
      setBusy(false);
    }
  };

  return (
    <article className="node research-node" data-node={RESEARCH_NODE} data-focus={focused || undefined} aria-label="Research">
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
        {research.repos?.slice(1).map(path => <p className="repo-line" key={path} title={path}><GitBranch size={13}/><span>{path.split("/").pop()}</span></p>)}
        {research.source_notes && <details><summary>Notes and prior research</summary><p className="source-words">{research.source_notes}</p></details>}
        <FileList files={research.files} title="Research files" />
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
        {offersPicks(models) && <AgentModel models={models ?? []} pick={pick} disabled={busy} onChange={setPick} />}
        <div className="ask-row">
          <Agents value={harness} onChange={choose} known={options?.harnesses} />
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
function Agents({ value, onChange, known, named, selectable }: { value: HarnessId; onChange: (id: HarnessId) => void; known?: Harness[]; named?: boolean; selectable?: boolean }) {
  return (
    <div className={`agents ${named ? "named" : ""}`} role="radiogroup" aria-label="Which agent answers">
      {AGENTS.map((id) => {
        const name = known?.find(h => h.id === id)?.title || AGENT_TITLES[id];
        const off = !selectable && known ? !known.find((h) => h.id === id)?.ready : false;
        return (
          <button
            type="button"
            role="radio"
            key={id}
            aria-checked={value === id}
            aria-label={name}
            disabled={off}
            title={off ? `${AGENT_TITLES[id]} isn't installed on this computer` : name}
            onClick={() => onChange(id)}
          >
            <AgentMark mark={id} size="sm" />
            {named && <span>{name}</span>}
          </button>
        );
      })}
    </div>
  );
}

// One conversation: its question, what the agent is doing, the start of its answer (a passage of
// which can be kept or explored), and a way into the whole of it: Open, or a click on the card.
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
  const focusOn = useHouse((s) => s.focusOn);
  const focused = useFocused(frameId, c.id);
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
  // Opened, the card is picked (its address links to it) and its chat is beside the canvas.
  const open = () => {
    focusOn({ task: frameId, node: c.id });
    void openThread(c.id);
  };
  // A click anywhere on the card opens it, unless it lands on one of the card's own controls or
  // ends a passage's selection (which gets Keep and Explore instead).
  const openFrom = (e: React.MouseEvent<HTMLElement>) => {
    const target = e.target as Element;
    if (e.detail > 1 || !e.currentTarget.contains(target) || target.closest("button, a")) return;
    if (!window.getSelection()?.isCollapsed) return;
    open();
  };
  return (
    <article
      className="node conv"
      data-node={c.id}
      data-status={c.status}
      data-focus={focused || undefined}
      aria-label={c.question}
      onClick={openFrom}
      onMouseEnter={() => onHot(c.id)}
      onMouseLeave={() => onHot(null)}
    >
      <header className="node-head">
        <AgentMark mark={c.harness} size="sm" />
        <b title={c.question}>{c.question}</b>
      </header>
      <div className="node-body">
        {c.quote && (
          <p className="conv-quote">
            <CornerDownRight size={13} />
            <span>“{c.quote}”</span>
          </p>
        )}
        {working && <ThinkingLoader className="conv-working" size="sm" phases={[c.step || "Starting"]} />}
        {c.answer && c.follow_up && (
          <p className="conv-follow" title={c.follow_up}>
            <MessageSquare size={13} />
            <span>{c.follow_up}</span>
          </p>
        )}
        {c.answer && (
          <div className="conv-answer rich" ref={answer} data-passage>
            <Rich text={c.answer} />
          </div>
        )}
        {c.answer && <Passage within={answer} frameId={frameId} conversationId={c.id} messageId={c.answer_id} agent={c} />}
        {c.problem && !working && <p className="node-line warn">{c.problem}</p>}
        <div className="conv-actions">
          <button type="button" className="btn" onClick={open}>
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

// A passage selected in an answer: keep it as a note, explore it in a new conversation that
// branches from this one (asked of the same agent on the model and effort picked here, at first
// what the conversation it branches from runs on), or reply about it in this conversation: the
// passage is quoted over the next question in its composer, its thread opened where it is not.
export function Passage({
  within,
  frameId,
  conversationId,
  messageId,
  agent,
}: {
  within: React.RefObject<HTMLElement | null>;
  frameId: string;
  conversationId: string;
  messageId: string;
  agent: { harness: HarnessId; model: string; effort: string };
}) {
  const [picked, setPicked] = useState<{ text: string; x: number; y: number } | null>(null);
  const [asking, setAsking] = useState(false);
  const [question, setQuestion] = useState("");
  const [pick, setPick] = useState<ModelPick>({ model: agent.model, effort: agent.effort });
  const models = useHouse((s) => s.research?.models[agent.harness]);
  const bar = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // A selection counts wherever the pointer or key that made it is let go, and only its part in
    // this answer does: one that starts on the time above it, or runs on past its end, still offers
    // the words it holds here. The answer it began in takes it, else the one it ended in.
    const read = () => {
      const el = within.current;
      const selection = window.getSelection();
      if (!el || !selection || selection.isCollapsed || !selection.rangeCount) return;
      if ((answerOf(selection.anchorNode) ?? answerOf(selection.focusNode)) !== el) return;
      const range = selection.getRangeAt(0).cloneRange();
      const whole = document.createRange();
      whole.selectNodeContents(el);
      if (range.compareBoundaryPoints(Range.START_TO_START, whole) < 0) range.setStart(whole.startContainer, whole.startOffset);
      if (range.compareBoundaryPoints(Range.END_TO_END, whole) > 0) range.setEnd(whole.endContainer, whole.endOffset);
      wholeWords(range);
      const text = range.toString().trim();
      if (text.length < 3) return;
      selection.removeAllRanges();
      selection.addRange(range);
      const r = range.getBoundingClientRect();
      setPicked({ text, x: r.left + r.width / 2, y: r.top });
      setAsking(false);
      setQuestion("");
    };
    document.addEventListener("mouseup", read);
    document.addEventListener("keyup", read);
    return () => {
      document.removeEventListener("mouseup", read);
      document.removeEventListener("keyup", read);
    };
  }, [within]);

  useEffect(() => {
    if (!picked) return;
    const onDown = (e: PointerEvent) => {
      if (e.defaultPrevented || !isWorkspaceTarget(e.target)) return;
      if (!bar.current?.contains(e.target as Node)) setPicked(null);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isWorkspaceTarget(e.target)) setPicked(null);
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
  const reply = () => {
    const state = useHouse.getState();
    useHouse.setState({ replying: { thread: conversationId, text: picked.text } });
    if (state.threadId !== conversationId) {
      state.focusOn({ task: frameId, node: conversationId });
      void state.openThread(conversationId);
    }
    done();
  };
  const explore = async () => {
    if (!question.trim()) return;
    try {
      await api.ask(frameId, { question: question.trim(), parent: conversationId, quote: picked.text, answer: messageId, harness: agent.harness, ...shownPick(models, pick) });
      done();
    } catch (error) {
      say(error);
    }
  };
  return createPortal(
    <div data-house-portal="" className="passage" ref={bar} style={{ left: picked.x, top: picked.y }} role="toolbar" aria-label="The selected passage">
      {asking ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void explore();
          }}
        >
          <div className="passage-ask">
            <input autoFocus value={question} placeholder="What should it find out about this?" aria-label="A question about the passage" onChange={(e) => setQuestion(e.target.value)} />
            <button type="submit" className="icon-btn send" aria-label="Ask" disabled={!question.trim()}>
              <ArrowUp />
            </button>
          </div>
          {offersPicks(models) && <AgentModel models={models ?? []} pick={pick} onChange={setPick} />}
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
          <button type="button" onClick={reply}>
            <Reply />
            Reply
          </button>
        </>
      )}
    </div>,
    document.body,
  );
}

// The answer a point of a selection is in, when it is one a passage can be taken from.
const answerOf = (node: Node | null) => (node instanceof Element ? node : node?.parentElement)?.closest("[data-passage]") ?? null;

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
  const openFiles = useHouse((s) => s.openFiles);
  const focused = useFocused(frameId, NOTES_NODE);
  const [draft, setDraft] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const asked = new Map(research.conversations.map((c) => [c.id, c]));
  // The notes as one page in the viewer, as the source's pages read: each under the question it
  // came from, with where that came from, as everything made from them is handed them.
  const page = `notes-${frameId}`;
  const read = () =>
    openFiles({
      files: [{ id: page, name: `${research.repo.name || "Research"} notes.md`, mime: "text/markdown", size: 0, origin: "notes", url: api.notesPage(frameId) }],
      at: page,
      title: "Notes",
    });
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
    <article
      className="node notes-node"
      data-node={NOTES_NODE}
      data-focus={focused || undefined}
      aria-label="Notes"
      onMouseEnter={() => onHot(NOTES_NODE)}
      onMouseLeave={() => onHot(null)}
    >
      <header className="node-head">
        <span className="node-icon">
          <NotebookPen size={16} />
        </span>
        <b>Notes</b>
        {research.notes.length > 0 && (
          <>
            <span className="chip">{research.notes.length}</span>
            <Tooltip content="Read them as one page" side="bottom">
              <button type="button" className="icon-btn" aria-label="Read the notes as one page" onClick={read}>
                <BookOpen />
              </button>
            </Tooltip>
          </>
        )}
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

// Starting research from the canvas: which repository, which agent on what model and effort, and
// the first question.
export function ResearchStart({ channelId, anchor, onClose, onStarted }: { channelId: string; anchor: HTMLElement; onClose: () => void; onStarted?: () => void }) {
  const options = useHouse((s) => s.research);
  const privateWorkspace = useHouse((s) => s.session?.authenticated);
  const [repoError, setRepoError] = useState(false);
  const listId = useId();
  const box = useRef<HTMLDivElement>(null);
  const search = useRef<HTMLInputElement>(null);
  const picker = useRef<HTMLDivElement>(null);
  const [selected, setSelected] = useState<RepoView[]>([]);
  const [listOpen, setListOpen] = useState(false);
  const [notes, setNotes] = useState("");
  const [files, setFiles] = useState<FileView[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);
  const channelTasks = useHouse(state => state.canvas[channelId]);
  const previous = (channelTasks ?? []).flatMap(task =>
    (task.research?.conversations ?? []).filter(c => c.answer).map(c => ({id:c.id, title:c.question, text:c.answer})));
  const [priorIds, setPriorIds] = useState<string[]>([]);
  const ask = useRef<HTMLTextAreaElement>(null);
  const [query, setQuery] = useState("");
  const [repo, setRepo] = useState("");
  const [harness, setHarness] = useState<HarnessId>("claude");
  const [pick, setPick] = useState<ModelPick>(DEFAULT_PICK);
  const models = options?.models[harness];
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [place, setPlace] = useState<{ top: number; left: number } | null>(null);

  useEffect(() => {
    void useHouse
      .getState()
      .loadResearch()
      .then((found) => {

        setHarness((h) => (found.harnesses.find((x) => x.id === h)?.ready ? h : (found.harnesses.find((x) => x.ready)?.id ?? h)));
      })
      .catch(() => setRepoError(true));
  }, []);

  // Keep the entire dialog inside the viewport as its contents change.
  useLayoutEffect(() => {
    const position = () => {
      const r = anchor.getBoundingClientRect();
      const width = box.current?.offsetWidth ?? 380;
      const height = box.current?.offsetHeight ?? 480;
      setPlace({
        top: Math.max(12, Math.min(r.bottom + 8, window.innerHeight - 12 - height)),
        left: Math.max(12, Math.min(window.innerWidth - width - 12, r.left)),
      });
    };
    position();
    const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(position) : null;
    if (box.current) observer?.observe(box.current);
    window.addEventListener("resize", position);
    return () => { observer?.disconnect(); window.removeEventListener("resize", position); };
  }, [anchor]);

  // The search takes the keyboard once, when the card is placed (a hidden field can't be focused).
  const placed = Boolean(place);
  useEffect(() => {
    if (placed) search.current?.focus();
  }, [placed]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && !e.defaultPrevented && isWorkspaceTarget(e.target) && onClose();
    const onDown = (e: PointerEvent) => {
      if (e.defaultPrevented || !isWorkspaceTarget(e.target)) return;
      const target = e.target as Node;
      if (!picker.current?.contains(target)) setListOpen(false);
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
  const discoveryOnly = options?.discovery_only === true;
  const shown = (options?.repos ?? []).filter(r => !selected.some(s => s.path === r.path) &&
    (r.name.toLowerCase().includes(wanted) || (privateWorkspace && r.path.toLowerCase().includes(wanted))));
  const folder = !privateWorkspace && /[/~]/.test(query);
  const active = shown.find((r) => r.path === repo) ?? shown[0];
  const provider = options?.harnesses.find(h => h.id === harness);
  const providerName = provider?.title || AGENT_TITLES[harness];
  const canStart = !!selected.length && !!question.trim() && !!provider?.ready && !discoveryOnly && !busy && !uploading;
  const choose = (item: RepoView) => {
    if (selected.length >= 8 || selected.some(r => r.path === item.path)) return;
    setSelected([...selected, item]);
    setQuery("");
    setRepo("");
    setListOpen(false);
    ask.current?.focus();
  };
  const attach = async (picked: File[]) => {
    if (!picked.length) return;
    if (files.length + picked.length > 10 || picked.some(f => f.size > 64000 || !/\.(txt|md|rst|csv|json|log)$/i.test(f.name))) {
      setError("Choose up to 10 text, Markdown, RST, CSV, JSON or log files, each up to 64 KB.");
      return;
    }
    setError("");
    setUploading(true);
    try {
      const uploaded = await api.upload(picked);
      setFiles(current => [...current, ...uploaded]);
    } catch (e) { setError((e as Error).message); }
    finally { setUploading(false); }
  };
  const start = async () => {
    if (!canStart) return;
    const material = [notes.trim(), ...previous.filter(p => priorIds.includes(p.id)).map(p => p.title + "\n" + p.text)].filter(Boolean).join("\n\n");
    if (material.length > 16000) { setError("Keep notes and prior research within 16,000 characters."); return; }
    setError("");
    setBusy(true);
    try {
      await api.openResearch(channelId, { repo: selected[0].path, repos: selected.map(r => r.path),
        harness, question: question.trim(), notes: material, files: files.map(f => f.id), ...shownPick(models, pick) });
      onStarted?.();
      onClose();
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return createPortal(
    <div
      data-house-portal=""
      className="pop research-start"
      ref={box}
      role="dialog"
      aria-label="Research a repository"
      style={place ? { top: place.top, left: place.left } : { visibility: "hidden", top: 0, left: 0 }}
    >
      <h3>Research a repository</h3>
      {selected.length > 0 && <div className="pending selected-repos" aria-label="Selected repositories">{selected.map(item =>
        <button type="button" className="chip green" key={item.path} title={item.path} aria-label={`Remove ${item.path}`}
          onClick={() => setSelected(selected.filter(r => r.path !== item.path))}><GitBranch aria-hidden="true" /><span>{item.name}</span><X aria-hidden="true" /></button>)}</div>}
      <div className="repo-picker" ref={picker}>
        <label className="repo-find">
          <Search size={14} />
          <input
            ref={search}
            value={query}
            placeholder={selected.length ? "Add another repository…" : "Find a repository"}
            aria-label="Find a repository"
            role="combobox"
            aria-autocomplete="list"
            aria-controls={listOpen ? listId : undefined}
            aria-expanded={listOpen}
            aria-activedescendant={listOpen && !folder && active ? `${listId}-${shown.indexOf(active)}` : undefined}
            disabled={selected.length >= 8 || busy}
            onClick={() => setListOpen(true)}
            onBlur={() => setListOpen(false)}
            onChange={(e) => {
              setListOpen(true);
              setQuery(e.target.value);
              setRepo("");
            }}
            onKeyDown={(e) => {
              if (listOpen && e.key === "Escape") {
                e.preventDefault();
                e.stopPropagation();
                setListOpen(false);
                return;
              }
              if (!listOpen && ["ArrowDown", "ArrowUp", "Enter"].includes(e.key)) { e.preventDefault(); setListOpen(true); return; }
              if ((e.key === "ArrowDown" || e.key === "ArrowUp") && active && !folder) {
                e.preventDefault();
                const next = (shown.indexOf(active) + (e.key === "ArrowDown" ? 1 : -1) + shown.length) % shown.length;
                setRepo(shown[next].path);
                document.getElementById(`${listId}-${next}`)?.scrollIntoView?.({block: "nearest"});
                return;
              }
              if (e.key !== "Enter") return;
              e.preventDefault();
              if (folder) choose({path:query.trim(), name:query.trim().split("/").filter(Boolean).pop() || query.trim(), branch:""});
              else if (active) choose(active);
            }}
          />
        </label>
        {listOpen && <div className="repo-list" onMouseDown={e => e.preventDefault()} id={listId} role="listbox" aria-label="Repositories">
          {!options && (repoError ? <p role="alert">Couldn’t load repositories.</p> : <Skeleton label="Loading repositories" />)}
          {options && !shown.length && !folder && (
            <p className="muted">{discoveryOnly || options.provider_api ? "No matching repositories." : privateWorkspace
              ? "Repository research is unavailable in private workspaces."
              : "No repository matches. Type a folder's path to research one inside a repository."}</p>
          )}
          {folder && (
            <button type="button" tabIndex={-1} role="option" aria-selected={repo === query.trim()} title={query.trim()} onClick={() => choose({path:query.trim(), name:query.trim().split("/").filter(Boolean).pop() || query.trim(), branch:""})}>
              <FolderOpen size={14} />
              <b>{query.trim().split("/").filter(Boolean).pop()}</b>
              <small>this folder</small>
            </button>
          )}
          {shown.map((r, index) => (
            <button type="button" tabIndex={-1} role="option" id={`${listId}-${index}`} aria-selected={!folder && active?.path === r.path} key={r.path} title={r.path} onClick={() => choose(r)}>
              <GitBranch size={14} />
              <b>{r.name}</b>
              <small>{discoveryOnly && r.path !== r.name ? r.path : r.branch}</small>
            </button>
          ))}
        </div>}
      </div>
      <div className="research-provider">
        <Agents
          value={harness}
          onChange={(id) => {
            setHarness(id);
            setPick(DEFAULT_PICK);
          }}
          known={options?.harnesses}
          named
          selectable
        />
        <AgentModel models={models ?? []} pick={pick} disabled={busy || !offersPicks(models)} onChange={setPick} />
        {options?.provider_api && !provider?.ready && <p className="pop-line">
          Configure {harness === "claude" ? "ANTHROPIC_API_KEY" : harness === "kimi" ? "MOONSHOT_API_KEY" : "OPENAI_API_KEY"} to run {providerName}.
        </p>}
      </div>
      <textarea
        ref={ask}
        rows={3}
        value={question}
        placeholder="What should it find out?"
        aria-label="The first question"
        onChange={(e) => setQuestion(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void start();
        }}
      />
      <textarea aria-label="Notes and prior research" placeholder="Notes or prior research (optional)" rows={4}
        maxLength={16000} value={notes} onChange={e => setNotes(e.target.value)} />
      {previous.length > 0 && <details><summary>Add previous research</summary>{previous.map(p => <label key={p.id} className="research-prior">
        <input type="checkbox" checked={priorIds.includes(p.id)} onChange={e => setPriorIds(e.target.checked ? [...priorIds,p.id] : priorIds.filter(id => id !== p.id))}/>{p.title}
      </label>)}</details>}
      <button type="button" className="btn" disabled={uploading || busy} onClick={() => fileInput.current?.click()}>
        <Paperclip size={14}/>{uploading ? "Uploading…" : "Attach files"}
      </button>
      <input type="file" hidden multiple ref={fileInput} aria-label="Attach research files" accept=".txt,.md,.rst,.csv,.json,.log"
        onChange={e => { const picked = Array.from(e.target.files ?? []); e.target.value = ""; void attach(picked); }} />
      {!!files.length && <div className="pending">{files.map(file => <button key={file.id} className="chip" type="button"
        aria-label={`Remove ${file.name}`} onClick={() => setFiles(files.filter(f => f.id !== file.id))}>{file.name}<X size={12}/></button>)}</div>}
      {error && <p role="alert">{error}</p>}
      <div className="pop-actions">
        <span className="faint">{discoveryOnly ? "Local discovery only. Research runs are disabled." : options?.provider_api ? `Sends committed excerpts and supporting material to ${providerName}.` : "Read-only, on this computer"}</span>
        <button type="button" className="btn primary" disabled={!canStart} onClick={() => void start()}>
          <Telescope />
          Start research
        </button>
      </div>
    </div>,
    document.body,
  );
}
