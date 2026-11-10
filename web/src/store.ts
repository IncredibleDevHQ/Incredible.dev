// One store for the app: what the server said, plus where the person is looking. Live events
// from /api/stream are applied here, so every view follows the same state.
import { create } from "zustand";
import {
  actAs,
  api,
  type Asset,
  type Board,
  type BrandRead,
  type BrandSummary,
  type CanvasTask,
  type Catalog,
  type Channel,
  type FileView,
  type Message,
  type Person,
  type ResearchOptions,
  type ResearchView,
  type Session,
  type Thread,
  type ThreadDetail,
  type Work,
} from "./api";

export type Page = "channel" | "needs" | "brand" | "skills" | "computer";
export type Mode = "chat" | "canvas";
// The template picker on the canvas: open on the list, or on one template (started from an asset,
// or placed onto a research frame, made from its notes).
export type TemplatePick = { template?: string; from?: string; frame?: string };
// A Studio preview open over everything: where it loads, and the film it is the final look of.
export type OpenPreview = { url: string; title: string; threadId: string; assetId?: string };
// Finished files open over everything at full size: the set they came in (an asset's files, a
// message's attachments), the one shown, and what the set is called.
export type OpenFiles = { files: FileView[]; at: string; title?: string };

type State = {
  session: Session | null;
  catalog: Catalog;
  people: Record<string, Person>;
  channels: Channel[];
  page: Page;
  channelId: string | null;
  mode: Mode;
  threadId: string | null;
  frameId: string | null;
  focusBoard: string | null;
  roots: Record<string, Message[]>;
  threads: Record<string, Thread>;
  replies: Record<string, number>;
  turns: Record<string, Message>;
  details: Record<string, ThreadDetail>;
  canvas: Record<string, CanvasTask[]>;
  picking: TemplatePick | null;
  preview: OpenPreview | null;
  viewing: OpenFiles | null;
  // The coding agents on this computer and the repositories they can research.
  research: ResearchOptions | null;
  // The house's brands, and the reads from websites still running or just finished.
  brands: BrandSummary[];
  reads: BrandRead[];
  toast: string | null;
  boot: () => Promise<void>;
  switchPerson: (id: string) => Promise<void>;
  openPage: (page: Page) => void;
  openChannel: (id: string, mode?: Mode) => Promise<void>;
  setMode: (mode: Mode) => void;
  openThread: (id: string | null) => Promise<void>;
  openFrame: (frameId: string | null, boardId?: string | null) => void;
  refreshCanvas: (channelId: string) => Promise<void>;
  pickTemplate: (pick: TemplatePick | null) => void;
  openPreview: (preview: OpenPreview | null) => void;
  openFiles: (viewing: OpenFiles | null) => void;
  loadResearch: () => Promise<ResearchOptions>;
  loadBrands: () => Promise<void>;
  say: (text: string | null) => void;
  apply: (event: LiveEvent) => void;
};

export type LiveEvent = { type: string; seq: number } & Record<string, unknown>;

const upsert = <T extends { id: string }>(list: T[], item: T): T[] => {
  const index = list.findIndex((x) => x.id === item.id);
  if (index < 0) return [...list, item];
  const copy = list.slice();
  copy[index] = item;
  return copy;
};

const lastTurns = (messages: Message[]): Record<string, Message> => {
  const out: Record<string, Message> = {};
  for (const m of messages) if (m.kind === "turn") out[m.thread_id] = m;
  return out;
};

export const useHouse = create<State>((set, get) => ({
  session: null,
  catalog: { capabilities: [], templates: [] },
  people: {},
  channels: [],
  page: "channel",
  channelId: null,
  mode: "chat",
  threadId: null,
  frameId: null,
  focusBoard: null,
  roots: {},
  threads: {},
  replies: {},
  turns: {},
  details: {},
  canvas: {},
  picking: null,
  preview: null,
  viewing: null,
  research: null,
  brands: [],
  reads: [],
  toast: null,

  async boot() {
    const [session, channels, catalog] = await Promise.all([api.session(), api.channels(), api.catalog()]);
    const people = Object.fromEntries(session.people.map((p) => [p.id, p]));
    set({ session, people, channels, catalog });
    const first = get().channelId ?? channels[0]?.id ?? null;
    if (first) await get().openChannel(first, get().mode);
  },

  async switchPerson(id) {
    actAs(id);
    const session = await api.session();
    set({ session });
  },

  openPage(page) {
    set({ page, frameId: null });
  },

  async openChannel(id, mode) {
    // The rail only ever shows this channel's work: a thread open from another channel closes.
    set((s) => ({
      page: "channel",
      channelId: id,
      mode: mode ?? s.mode,
      frameId: null,
      threadId: s.threadId && s.threads[s.threadId]?.channel_id === id ? s.threadId : null,
    }));
    const listing = await api.channelMessages(id);
    set((s) => ({
      roots: { ...s.roots, [id]: listing.roots },
      threads: { ...s.threads, ...listing.threads },
      replies: { ...s.replies, ...listing.replies },
    }));
    if ((mode ?? get().mode) === "canvas") await get().refreshCanvas(id);
    // A task card shows its latest turn; read each task thread once.
    const tasks = Object.values(listing.threads).filter((t) => t.task);
    const details = await Promise.all(tasks.map((t) => api.thread(t.id)));
    set((s) => {
      const next = { ...s.details };
      let turns = { ...s.turns };
      for (const d of details) {
        next[d.thread.id] = d;
        turns = { ...turns, ...lastTurns(d.messages) };
      }
      return { details: next, turns };
    });
  },

  setMode(mode) {
    set({ mode });
    const id = get().channelId;
    if (mode === "canvas" && id) void get().refreshCanvas(id);
  },

  async openThread(id) {
    set({ threadId: id });
    if (!id) return;
    const detail = await api.thread(id);
    set((s) => ({
      details: { ...s.details, [id]: detail },
      threads: { ...s.threads, [id]: detail.thread },
      turns: { ...s.turns, ...lastTurns(detail.messages) },
    }));
  },

  openFrame(frameId, boardId = null) {
    set({ frameId, focusBoard: boardId ?? get().focusBoard });
  },

  async refreshCanvas(channelId) {
    const tasks = await api.canvas(channelId);
    set((s) => ({ canvas: { ...s.canvas, [channelId]: tasks } }));
  },

  pickTemplate(pick) {
    set({ picking: pick });
  },

  openPreview(preview) {
    set({ preview });
  },

  openFiles(viewing) {
    set({ viewing });
  },

  async loadBrands() {
    const { brands, reading } = await api.brands();
    set({ brands, reads: reading });
  },

  async loadResearch() {
    const research = await api.researchOptions();
    set({ research });
    return research;
  },

  say(text) {
    set({ toast: text });
  },

  apply(event) {
    const s = get();
    switch (event.type) {
      case "channel.created": {
        // A new channel, or one that changed (the brand it wears): its counts are kept.
        const channel = event.channel as Channel;
        const known = s.channels.find((c) => c.id === channel.id);
        set({ channels: upsert(s.channels, { ...known, ...channel }) });
        break;
      }
      case "thread.created":
      case "thread.updated": {
        const thread = event.thread as Thread;
        const detail = s.details[thread.id];
        const tasks = s.canvas[thread.channel_id];
        set({
          threads: { ...s.threads, [thread.id]: thread },
          details: detail ? { ...s.details, [thread.id]: { ...detail, thread } } : s.details,
          canvas: tasks
            ? {
                ...s.canvas,
                [thread.channel_id]: tasks.some((t) => t.thread.id === thread.id)
                  ? tasks.map((t) => (t.thread.id === thread.id ? { ...t, thread } : t))
                  : thread.task
                    ? [...tasks, { thread, material: { text: "", files: [], author_id: thread.started_by }, assets: [], boards: [], files: [], work: [] }]
                    : tasks,
              }
            : s.canvas,
          channels: s.channels.map((c) =>
            c.id === thread.channel_id ? { ...c, ...channelCounts(c.id, { ...s.threads, [thread.id]: thread }) } : c,
          ),
        });
        break;
      }
      case "message.created":
      case "message.updated": {
        const message = event.message as Message;
        const detail = s.details[message.thread_id];
        const isRoot = message.id === message.thread_id;
        const roots = s.roots[message.channel_id];
        const fresh = event.type === "message.created";
        set({
          details: detail
            ? { ...s.details, [message.thread_id]: { ...detail, messages: upsert(detail.messages, message) } }
            : s.details,
          // A task's first message is what it started from: the canvas draws it as the source.
          canvas: isRoot
            ? mapTask(s.canvas, message.thread_id, (t) => ({
                ...t,
                material: { text: message.text, files: message.data.files ?? [], author_id: message.author_id },
              }))
            : s.canvas,
          roots: isRoot && roots ? { ...s.roots, [message.channel_id]: upsert(roots, message) } : s.roots,
          turns: message.kind === "turn" ? { ...s.turns, [message.thread_id]: message } : s.turns,
          replies:
            fresh && !isRoot && (message.kind === "person" || message.kind === "agent")
              ? { ...s.replies, [message.thread_id]: (s.replies[message.thread_id] ?? 0) + 1 }
              : s.replies,
        });
        break;
      }
      case "work.updated": {
        const work = event.work as Work;
        const detail = s.details[work.thread_id];
        set({
          details: detail ? { ...s.details, [work.thread_id]: { ...detail, work: upsert(detail.work, work) } } : s.details,
          canvas: mapTask(s.canvas, work.thread_id, (t) => ({ ...t, work: upsert(t.work, work) })),
        });
        break;
      }
      case "board.updated": {
        const board = event.board as Board;
        const detail = s.details[board.thread_id];
        set({
          details: detail
            ? { ...s.details, [board.thread_id]: { ...detail, boards: upsert(detail.boards, board) } }
            : s.details,
          canvas: mapTask(s.canvas, board.thread_id, (t) => ({ ...t, boards: upsert(t.boards, board) })),
        });
        break;
      }
      case "asset.updated": {
        const asset = event.asset as Asset;
        const detail = s.details[asset.thread_id];
        set({
          details: detail
            ? { ...s.details, [asset.thread_id]: { ...detail, assets: upsert(detail.assets ?? [], asset) } }
            : s.details,
          canvas: mapTask(s.canvas, asset.thread_id, (t) => ({
            ...t,
            assets: upsert(t.assets, asset).sort((a, b) => a.position - b.position),
          })),
        });
        break;
      }
      case "files.delivered": {
        const threadId = event.thread_id as string;
        const files = event.files as FileView[];
        const detail = s.details[threadId];
        set({
          details: detail
            ? { ...s.details, [threadId]: { ...detail, files: files.reduce(upsert, detail.files) } }
            : s.details,
          canvas: mapTask(s.canvas, threadId, (t) => ({ ...t, files: files.reduce(upsert, t.files) })),
        });
        break;
      }
      case "brand.updated": {
        const read = event.read as BrandRead;
        // A brand that is made settles the reads that failed before it.
        const kept = s.reads.filter((r) => r.url !== read.url && (read.status !== "ready" || r.status === "reading"));
        set({ reads: [read, ...kept].slice(0, 6) });
        if (read.status === "ready") {
          void get().loadBrands();
          set({ toast: `${read.brand?.name ?? "The brand"} is ready.` });
        }
        if (read.status === "failed") set({ toast: read.message ?? "The read stopped." });
        break;
      }
      case "research.updated": {
        const research = event.research as ResearchView;
        set({ canvas: mapTask(s.canvas, event.thread_id as string, (t) => ({ ...t, research })) });
        break;
      }
      case "attention": {
        set({ toast: "The agent needs you in a thread." });
        break;
      }
    }
  },
}));

function channelCounts(channelId: string, threads: Record<string, Thread>) {
  const mine = Object.values(threads).filter((t) => t.channel_id === channelId);
  return {
    working: mine.filter((t) => t.status === "working").length,
    needs_you: mine.filter((t) => t.status === "needs_you").length,
  };
}

function mapTask(
  canvas: Record<string, CanvasTask[]>,
  threadId: string,
  change: (task: CanvasTask) => CanvasTask,
): Record<string, CanvasTask[]> {
  for (const [channelId, tasks] of Object.entries(canvas)) {
    if (tasks.some((t) => t.thread.id === threadId)) {
      return { ...canvas, [channelId]: tasks.map((t) => (t.thread.id === threadId ? change(t) : t)) };
    }
  }
  return canvas;
}

export const person = (id: string) => useHouse.getState().people[id];
