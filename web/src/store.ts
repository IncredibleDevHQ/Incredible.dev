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
  type EpisodeCard,
  type EpisodeView,
  type FileView,
  type Message,
  type Person,
  type ResearchOptions,
  type ResearchView,
  type Session,
  type Thread,
  type ThreadDetail,
  type Work,
  type WorkPulse,
  type ProductionView,
} from "./api";
import { NO_FILTER, type BoardFilter } from "./production";

export type Page = "channel" | "needs" | "production" | "brand" | "read-brand" | "skills" | "computer";
// Where an episode opens: one of its chapters, at one of its lines ("" for the chapter's first).
export type Landing = { chapter: string; line: string };
// The sheet an episode is started from: open, with the research frame its notes come from if any.
export type EpisodeStart = { frame?: string; title?: string; notes?: string };
export type Mode = "chat" | "canvas";
// The template picker on the canvas: open on the list, or on one template (started from an asset,
// or placed onto a research frame, made from its notes).
export type TemplatePick = { template?: string; from?: string; frame?: string };
// A Studio preview open over everything: where it loads, and the film it is the final look of.
export type OpenPreview = { url: string; title: string; threadId: string; assetId?: string };
// Finished files open over everything at full size: the set they came in (an asset's files, a
// message's attachments), the one shown, and what the set is called.
export type OpenFiles = { files: FileView[]; at: string; title?: string };
// What's picked on a channel's canvas: a task's frame (by its thread), or a card in it. Its address
// links to it; one arrived at by a link is brought into view (`reveal`) once it is on the canvas.
export type Focus = { task: string; node: string | null; reveal?: boolean };

export type State = {
  session: Session | null;
  catalog: Catalog;
  people: Record<string, Person>;
  channels: Channel[];
  page: Page;
  channelId: string | null;
  mode: Mode;
  focus: Focus | null;
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
  // The episode whose studio is open over the channel, and everything that studio draws.
  episodeId: string | null;
  episode: EpisodeView | null;
  // Where the open episode is to land once its plan is in (asked for once, by a link or the
  // board), the chapter it is on now (its address says so), and whether it is open as a peek:
  // over the page it was opened from, which Escape goes back to.
  landing: Landing | null;
  episodeChapter: string;
  episodePeek: boolean;
  // What each turn under way is doing between its steps, by episode and lane ("<episode>:plan",
  // "<episode>:picture:<unit>"): told a second apart while a model thinks, so it is kept beside
  // the episodes and only what shows it draws again.
  pulses: Record<string, WorkPulse>;
  // The production board: every job of every episode, and what the board is narrowed to.
  production: ProductionView | null;
  board: BoardFilter;
  startingEpisode: EpisodeStart | null;
  // The coding agents on this computer and the repositories they can research.
  research: ResearchOptions | null;
  // The house's brands, and the reads from websites still running or just finished.
  brands: BrandSummary[];
  reads: BrandRead[];
  // The channel a brand being read from a website is for, which wears it once it is made.
  brandFor: string | null;
  // The kit the Brands page shows; another page can send you to one.
  brandSlug: string;
  toast: string | null;
  boot: () => Promise<void>;
  switchPerson: (id: string) => Promise<void>;
  openPage: (page: Page) => void;
  readBrandFor: (channelId: string | null) => void;
  openBrand: (slug: string) => void;
  openChannel: (id: string, mode?: Mode) => Promise<void>;
  setMode: (mode: Mode) => void;
  focusOn: (focus: Focus | null) => void;
  openThread: (id: string | null) => Promise<void>;
  openFrame: (frameId: string | null, boardId?: string | null) => void;
  refreshCanvas: (channelId: string) => Promise<void>;
  pickTemplate: (pick: TemplatePick | null) => void;
  openPreview: (preview: OpenPreview | null) => void;
  openFiles: (viewing: OpenFiles | null) => void;
  openEpisode: (id: string | null, landing?: Landing | null, peek?: boolean) => Promise<void>;
  setEpisode: (episode: EpisodeView) => void;
  // `quiet` for a read nobody asked for (the sidebar's count): one that fails says nothing
  loadProduction: (quiet?: boolean) => Promise<void>;
  setBoard: (filter: Partial<BoardFilter>) => void;
  startEpisode: (start: EpisodeStart | null) => void;
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
  focus: null,
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
  episodeId: null,
  episode: null,
  landing: null,
  episodeChapter: "",
  episodePeek: false,
  pulses: {},
  production: null,
  board: NO_FILTER,
  startingEpisode: null,
  research: null,
  brands: [],
  reads: [],
  brandFor: null,
  brandSlug: "default",
  toast: null,

  // Who's here and what the house has; where to look comes from the address (route.ts).
  async boot() {
    const [session, channels, catalog] = await Promise.all([api.session(), api.channels(), api.catalog()]);
    const people = Object.fromEntries(session.people.map((p) => [p.id, p]));
    set({ session, people, channels, catalog });
    void get().loadProduction(true);
  },

  async switchPerson(id) {
    actAs(id);
    const session = await api.session();
    set({ session });
  },

  openPage(page) {
    set({ page, frameId: null });
    if (page === "production") void get().loadProduction();
  },

  readBrandFor(channelId) {
    set({ page: "read-brand", brandFor: channelId, frameId: null });
  },

  openBrand(slug) {
    set({ page: "brand", brandSlug: slug, frameId: null });
  },

  async openChannel(id, mode) {
    // The rail only ever shows this channel's work: a thread open from another channel closes,
    // and what was picked on another channel's canvas is let go.
    set((s) => ({
      page: "channel",
      channelId: id,
      mode: mode ?? s.mode,
      focus: s.channelId === id ? s.focus : null,
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

  focusOn(focus) {
    set({ focus });
  },

  async openThread(id) {
    // A conversation's card is picked while its chat is open: closing the chat lets go of it.
    set((s) => ({ threadId: id, focus: !id && s.threadId && s.focus?.node === s.threadId ? null : s.focus }));
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

  async openEpisode(id, landing = null, peek = false) {
    if (!id) {
      const peeked = get().episodePeek;
      set({ episodeId: null, episode: null, landing: null, episodeChapter: "", episodePeek: false });
      // what was done in the peek shows on the board it was opened from
      if (peeked) void get().loadProduction();
      return;
    }
    const kept = get().episode;
    set({ episodeId: id, episode: kept?.id === id ? kept : null, landing, episodePeek: peek });
    try {
      const episode = await api.episode(id);
      if (get().episodeId === id) set({ episode });
    } catch (error) {
      set({ episodeId: null, episode: null, landing: null, episodePeek: false, toast: (error as Error).message });
    }
  },

  async loadProduction(quiet = false) {
    try {
      set({ production: await api.production() });
    } catch (error) {
      if (!quiet) set({ toast: (error as Error).message });
    }
  },

  setBoard(filter) {
    const board = { ...get().board, ...filter };
    // a chapter is one episode's: another episode, or none, lets it go
    if (filter.episode !== undefined && filter.episode !== get().board.episode && filter.chapter === undefined) board.chapter = "";
    set({ board });
  },

  setEpisode(episode) {
    if (get().episodeId === episode.id) set({ episode });
  },

  startEpisode(start) {
    set({ startingEpisode: start });
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
        // The read's own page says why it stopped; anywhere else, a toast does.
        if (read.status === "failed" && s.page !== "read-brand") set({ toast: read.message ?? "The read stopped." });
        break;
      }
      case "episode.updated": {
        const card = event.card as EpisodeCard;
        set({
          canvas: mapTask(s.canvas, event.thread_id as string, (t) => ({
            ...t,
            episodes: upsert(t.episodes ?? [], card),
          })),
        });
        // The open studio follows: its progress at once, everything else read again soon.
        if (s.episodeId === card.id) {
          if (s.episode) set({ episode: { ...s.episode, ...card } });
          refreshEpisode(card.id);
        }
        refreshProduction(s.page === "production");
        break;
      }
      case "episode.pulse": {
        const { lane, ...pulse } = event.pulse as WorkPulse & { lane: string };
        set({ pulses: { ...s.pulses, [`${event.id as string}:${lane}`]: pulse } });
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

// The production board, read again after a change to any episode: a moment after the last one
// while the board is open, and seldom while it is not (the sidebar's count is all that shows).
let productionTimer = 0;
let productionRead = 0;
function refreshProduction(open: boolean) {
  if (!open && (productionTimer || Date.now() - productionRead < 20_000)) return;
  window.clearTimeout(productionTimer);
  productionTimer = window.setTimeout(
    () => {
      productionTimer = 0;
      productionRead = Date.now();
      void useHouse.getState().loadProduction(!open);
    },
    open ? 500 : 2000,
  );
}

// The open studio's episode, read again a moment after the last change to it.
let episodeTimer = 0;
function refreshEpisode(id: string) {
  window.clearTimeout(episodeTimer);
  episodeTimer = window.setTimeout(() => {
    void api
      .episode(id)
      .then((episode) => useHouse.getState().setEpisode(episode))
      .catch(() => undefined);
  }, 350);
}

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

// Whether a task's frame (no node) or one of its cards is what's picked on the canvas.
export const useFocused = (task: string, node: string | null) => useHouse((s) => s.focus?.task === task && s.focus.node === node);
