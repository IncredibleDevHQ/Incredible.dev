// The engine's web API (src/design_agent/surfaces/web/app.py), typed.

export type Person = { id: string; name: string; initials: string; hue: number; agent: boolean };
export type Channel = {
  id: string;
  name: string;
  topic: string;
  // The brand pack its work wears (a slug under workspace/brands); empty for the configured one.
  brand?: string;
  created_at: number;
  working?: number;
  needs_you?: number;
};
export type FileView = { id: string; name: string; mime: string; size: number; origin: string; url: string };
export type StepStatus = "running" | "done" | "failed" | "pending";
export type Step = { id: string; title: string; status: StepStatus };
export type MessageKind = "person" | "agent" | "turn" | "notice" | "ask";
export type MessageData = {
  files?: FileView[];
  // A research question that branches from a passage of another answer: that passage.
  quote?: string;
  state?: "working" | "done" | "stopped" | "quiet" | "queued" | "taken" | "folded" | "stop";
  header?: string;
  steps?: Step[];
  notes?: string[];
  woken?: boolean;
  started_at?: number;
  ended_at?: number;
  mark?: string;
  kind?: string;
  // A question the engine waits on (a pipeline's), with the answers it takes.
  ask?: { question: string; options: string[]; source: string };
  answered?: { text: string; by: string };
};
export type Message = {
  id: string;
  channel_id: string;
  thread_id: string;
  author_id: string;
  kind: MessageKind;
  text: string;
  to_agent: boolean;
  data: MessageData;
  created_at: number;
  updated_at: number;
};
export type Footer = {
  live?: boolean;
  agents?: number;
  render?: { label: string; fraction: number | null; eta: number | null } | null;
  minutes?: number;
  usd?: number;
};
export type ThreadStatus = "idle" | "working" | "needs_you" | "failed";
export type Thread = {
  id: string;
  channel_id: string;
  task: boolean;
  title: string;
  kind: string;
  status: ThreadStatus;
  started_by: string;
  started_at: number;
  updated_at: number;
  footer: Footer;
};
export type Work = {
  id: string;
  thread_id: string;
  kind: "helper" | "render" | "pipeline";
  label: string;
  effort: string;
  status: string;
  fraction: number | null;
  phase: string;
  eta: number | null;
  note: string;
  steps: Step[];
  started_at: number;
  finished_at: number | null;
  updated_at: number;
};
export type Comment = {
  id: string;
  board_id: string;
  frame_id: string;
  parent_id: string;
  author_id: string;
  author: string;
  text: string;
  x: number | null;
  y: number | null;
  // The row of a plan's section the note is on; empty for a pin or a note on the whole frame.
  anchor: string;
  version: number;
  resolved: boolean;
  resolved_by: string;
  answered_in: number;
  created_at: number;
};
// One row of a brief's or a plan's section: a line of the brief, a claim in its ledger, a spine,
// or a chapter in the chapter list.
export type PlanRow = {
  id: string;
  label: string;
  text?: string;
  detail?: string;
  picked?: boolean;
  title?: string;
  time?: string;
  // Where it starts in the film, in seconds, worked out by the canvas.
  start?: number;
  seconds?: number;
  asks?: string;
  ends?: string;
  shape?: string;
  // Its share of the material: what it uses and what it leaves to the chapters beside it.
  covers?: string;
  cue?: string;
  handoff?: string;
  // The film's first spoken line and the kind of hook it is (the open's row), and its last with
  // how it lands the idea (the close's).
  first?: string;
  hook?: string;
  last?: string;
  landing?: string;
  // The one moment the film pivots on, on the row of the chapter that holds it.
  turn?: string;
  // A claim in the ledger: the fact as the film states it, the material's own words for it, and
  // whether the canvas found those words in the material.
  claim?: string;
  quote?: string;
  status?: "stated" | "illustrative" | "unconfirmed";
  found?: boolean;
};
// One frame of a beat (the plan's files call it a shot): a line of picture and script. `speaks`
// and `reads` are how long its line takes to say and its words on screen to read, in seconds.
export type PlanShot = {
  id: string;
  time: string;
  start: number;
  seconds: number;
  speaks: number;
  reads: number;
  move: string;
  shows: string;
  vo?: string;
  on?: string;
  at?: number;
  sound?: string;
};
// One beat of a chapter. Its frames are written from it afterwards, so it can stand without them;
// `stale` says its words changed since they were written. `says` is the passage the voice says
// over it, which its frames cut into lines; `technique` is how it makes its point land.
export type PlanBeat = {
  id: string;
  title: string;
  time: string;
  start: number;
  seconds: number;
  speaks: number;
  takeaway: string;
  technique?: string;
  says?: string;
  focal: string;
  demands: string[];
  change: string;
  result: string;
  enters: string;
  leaves: string;
  claim?: string;
  shots?: PlanShot[];
  stale?: boolean;
};
// One section of an episode's plan, as a plan board's frame carries it: the top layer's lists and
// tables, or a chapter's beats with their frames. The clock (`time`) and `words` are worked out by
// the canvas; `changed` names the rows whose words differ from the version before.
export type PlanSection = { changed?: string[] } & (
  | { section: "list" | "claims" | "spine" | "chapters"; layer: "top"; rows: PlanRow[] }
  | { section: "chapter"; layer: "chapter"; title: string; time: string; start: number; seconds: number; words?: string; beats: PlanBeat[] }
);
// One of a plan's checks, worked out from its sections: what it checks, what it found.
// `group` says what a check is about, so a long list reads in parts: time, structure, words.
export type PlanCheck = { id: string; label: string; rule: string; text: string; state: "pass" | "fail" | "wait"; group?: string };
export type FrameView = {
  id: string;
  name: string;
  note: string;
  position: number;
  verdict: "" | "approved" | "changes";
  verdict_by: string;
  version: number;
  versions: { v: number; url: string; at: number }[];
  // A plan board's frame: the section it holds, and as it was in the version before.
  data?: PlanSection | null;
  was?: PlanSection | null;
  comments: Comment[];
};
export type Board = {
  id: string;
  thread_id: string;
  project: string;
  title: string;
  kind: string;
  version: number;
  status: "review" | "approved" | "changes";
  created_at: number;
  updated_at: number;
  frames: FrameView[];
  // A brief's or a plan's checks, worked out from its sections as they stand.
  checks?: PlanCheck[];
  // The brief a plan is written from: its idea, where it stands, and the frame that opens it.
  brief?: { board_id: string; frame_id: string; status: string; idea: string };
};
// What the canvas can ask the engine for (src/design_agent/surfaces/web/catalog.py).
export type Capability = {
  id: string;
  title: string;
  line: string;
  asks: string;
  skill: string;
  review: string;
  makes: string;
  accepts: string[];
  takes: string[];
};
// One piece of a template: what it is, what it is made from, what the person gets, and the shape
// of each piece it makes ("16:9", "9:16", "210:297" for a page).
export type Slot = { key: string; kind: string; title: string; brief: string; sources: string[]; gate: boolean; gets: string; shape: string[] };
export type Template = { id: string; title: string; line: string; starts: string; starts_from: string[]; slots: Slot[] };
export type Catalog = { capabilities: Capability[]; templates: Template[] };
export type AssetStatus = "planned" | "making" | "review" | "changes" | "approved" | "done" | "blocked" | "skipped";
// A film before its render: the Studio preview on the thread's computer (opened through `url`)
// and the proof frames that came with it.
export type FilmPreview = { port: number; project: string; url: string; proofs: FileView[] };
// One piece of a task's work on the canvas: its review board, its finished files, its sources.
export type Asset = {
  id: string;
  thread_id: string;
  kind: string;
  title: string;
  brief: string;
  status: AssetStatus;
  sources: string[];
  gate: boolean;
  board_id: string;
  files: (FileView & { path: string })[];
  note: string;
  position: number;
  template: string;
  added_by: string;
  created_at: number;
  updated_at: number;
  preview: FilmPreview | null;
};
export type Material = { text: string; files: FileView[]; author_id: string };
export type ThreadDetail = {
  thread: Thread;
  messages: Message[];
  work: Work[];
  conversation?: ConversationRow | null;
  boards: Board[];
  files: FileView[];
  assets: Asset[];
};
// Research on this computer: a coding agent (Claude Code, Codex, Kimi Code) answering questions
// about one of your repositories, read-only, and the notes kept from its answers.
export type HarnessId = "claude" | "codex" | "kimi";
export type Harness = { id: HarnessId; title: string; ready: boolean };
export type RepoView = { name: string; path: string; branch: string; within?: string };
// Where a note came from, from the repository down to the conversation it was kept from.
export type LineageStep = { kind: "repo" | "conversation" | "follow_up"; label: string; detail?: string; harness?: HarnessId; id?: string };
export type ResearchOptions = { harnesses: Harness[]; repos: RepoView[] };
export type Conversation = {
  id: string;
  parent_id: string;
  quote: string;
  harness: HarnessId;
  question: string;
  status: ThreadStatus;
  answer: string;
  answer_id: string;
  follow_up: string;
  step: string;
  problem: string;
  asked: number;
  kept: number;
  created_at: number;
};
export type Note = {
  id: string;
  text: string;
  conversation_id: string;
  message_id: string;
  author_id: string;
  created_at: number;
  kind: "answer" | "passage" | "own";
  lineage: LineageStep[];
};
export type ResearchView = { repo: RepoView; harness: HarnessId; conversations: Conversation[]; notes: Note[] };
export type ConversationRow = { id: string; frame_id: string; parent_id: string; quote: string; harness: HarnessId; repo: string };
export type CanvasTask = {
  thread: Thread;
  material: Material;
  research?: ResearchView | null;
  assets: Asset[];
  boards: Board[];
  files: FileView[];
  work: Work[];
};
export type FolderFile = { path: string; size: number; modified: number };
export type Session = {
  me: string;
  people: Person[];
  agent: { mark: string; model: string };
  demo: boolean;
  sandbox: string | null;
};
export type ChannelMessages = {
  roots: Message[];
  threads: Record<string, Thread>;
  replies: Record<string, number>;
};
export type BrandView = {
  name: string;
  colors: { name: string; value: string }[];
  families: { family: string; styles: string[]; license: string; required: boolean }[];
  logos: string[];
  voice: string;
  graphic_language: string;
  sample: boolean;
};
export type SkillView = { name: string; description: string; vendored: boolean };
// The house's brands: the configured pack and those read from websites.
export type BrandSummary = {
  slug: string;
  name: string;
  colors: { name: string; value: string }[];
  logo: string;
  ground: string;
  source: string;
  read: string;
  sample: boolean;
  channels: string[];
};
// A read of a site's brand: where it is (`step`: open, colours, type, logo, pack, then done), the
// channel it was read for, and what it made or why it stopped.
export type BrandRead = { url: string; status: "reading" | "ready" | "failed"; step?: string; channel?: string; slug?: string; message?: string; brand?: BrandSummary };
export type ColourRole = "ground" | "ink" | "accent" | "muted" | "rule";
export type TypeRole = "display" | "text" | "mono";
export type BrandPackView = Omit<BrandView, "logos"> & {
  slug: string;
  logos: { name: string; url: string }[];
  source: string;
  read: string;
  reference: string;
  stand_ins?: Record<string, string>;
  description: string;
  voice_line: string;
  license_note: string;
  formats: { slug: string; width: number; height: number; label: string }[];
  roles: { role: ColourRole; name: string; value: string }[];
  palette: { name: string; value: string }[];
  series: string[];
  faces: { family: string; style: string; weight: string; file: string; url: string }[];
  stacks: Partial<Record<TypeRole, string[]>>;
  shape: { radius: string[]; pill: string; stroke: string; space: string; weights: Partial<Record<"display" | "text" | "strong", string>>; tracking: string };
  rules: string[];
  banned: string[];
};
export type ComputerView = {
  sandbox: string | null;
  image: string;
  vcpus: number;
  mem_gib: number;
  network: string[];
  pinned: Record<string, string>;
  keys_inside: boolean;
};

let person = localStorage.getItem("house:person") || "you";
export const actingAs = () => person;
export function actAs(id: string) {
  person = id;
  try {
    localStorage.setItem("house:person", id);
  } catch {
    /* storage unavailable */
  }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: { "X-Person": person, ...(body instanceof FormData || body === undefined ? {} : { "Content-Type": "application/json" }) },
    body: body instanceof FormData ? body : body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      detail = (await response.json()).detail ?? detail;
    } catch {
      /* not JSON */
    }
    throw new Error(typeof detail === "string" ? detail : "Request failed");
  }
  return (await response.json()) as T;
}

export const api = {
  session: () => call<Session>("GET", "/api/session"),
  channels: () => call<Channel[]>("GET", "/api/channels"),
  addChannel: (name: string, topic = "") => call<Channel>("POST", "/api/channels", { name, topic }),
  channelMessages: (id: string) => call<ChannelMessages>("GET", `/api/channels/${id}/messages`),
  startThread: (channelId: string, body: { text: string; to_agent: boolean; files: string[]; kind?: string }) =>
    call<Message>("POST", `/api/channels/${channelId}/messages`, body),
  thread: (id: string) => call<ThreadDetail>("GET", `/api/threads/${id}`),
  reply: (threadId: string, body: { text: string; to_agent: boolean; files: string[]; answers?: string }) =>
    call<Message>("POST", `/api/threads/${threadId}/messages`, body),
  pickLook: (boardId: string, frameId: string, reason: string) =>
    call<Message>("POST", `/api/boards/${boardId}/pick`, { frame_id: frameId, reason }),
  stop: (threadId: string) => call<{ ok: boolean }>("POST", `/api/threads/${threadId}/stop`),
  cancelWork: (threadId: string, workId: string) =>
    call<{ said: string }>("POST", `/api/threads/${threadId}/work/${workId}/cancel`),
  upload: (files: File[]) => {
    const form = new FormData();
    for (const file of files) form.append("files", file);
    return call<FileView[]>("POST", "/api/uploads", form);
  },
  canvas: (channelId: string) => call<CanvasTask[]>("GET", `/api/channels/${channelId}/canvas`),
  catalog: () => call<Catalog>("GET", "/api/catalog"),
  renderFilm: (assetId: string) => call<Message>("POST", `/api/assets/${assetId}/render`),
  approveDraft: (assetId: string) => call<Message>("POST", `/api/assets/${assetId}/approve`),
  addAsset: (threadId: string, body: { kind: string; sources: string[]; note: string }) =>
    call<Asset>("POST", `/api/threads/${threadId}/assets`, body),
  placeTemplate: (channelId: string, body: { template: string; text: string; files: string[]; from_asset: string; from_frame?: string }) =>
    call<Message>("POST", `/api/channels/${channelId}/templates`, body),
  researchOptions: () => call<ResearchOptions>("GET", "/api/research"),
  openResearch: (channelId: string, body: { repo: string; harness: HarnessId; question: string }) =>
    call<{ thread: Thread; conversation: ConversationRow }>("POST", `/api/channels/${channelId}/research`, body),
  ask: (frameId: string, body: { question: string; harness?: HarnessId | ""; parent?: string; quote?: string; answer?: string }) =>
    call<ConversationRow>("POST", `/api/research/${frameId}/conversations`, body),
  keepNote: (frameId: string, body: { text: string; conversation_id?: string; message_id?: string }) =>
    call<Note>("POST", `/api/research/${frameId}/notes`, body),
  editNote: (noteId: string, text: string) => call<Note>("PATCH", `/api/notes/${noteId}`, { text }),
  dropNote: (noteId: string) => call<{ ok: boolean }>("DELETE", `/api/notes/${noteId}`),
  folder: (threadId: string) => call<FolderFile[]>("GET", `/api/threads/${threadId}/folder`),
  folderUrl: (threadId: string, path: string) => `/api/threads/${threadId}/folder/file?path=${encodeURIComponent(path)}`,
  comment: (frameId: string, body: { text: string; x?: number | null; y?: number | null; parent_id?: string; anchor?: string }) =>
    call<Comment>("POST", `/api/frames/${frameId}/comments`, body),
  resolve: (commentId: string, resolved: boolean) =>
    call<{ ok: boolean }>("POST", `/api/comments/${commentId}/resolve`, { resolved }),
  verdict: (frameId: string, verdict: "" | "approved" | "changes") =>
    call<{ ok: boolean }>("POST", `/api/frames/${frameId}/verdict`, { verdict }),
  // One part of a plan rewritten and nothing else: a section, or one row of it.
  refinePlan: (boardId: string, body: { frame_id: string; text: string; row?: string }) =>
    call<Message>("POST", `/api/boards/${boardId}/refine`, body),
  // One chapter of a plan written in full ahead of the rest.
  writeChapter: (boardId: string, name: string) => call<Message>("POST", `/api/boards/${boardId}/write`, { name }),
  sendBoard: (boardId: string, approve: boolean) =>
    call<Message>("POST", `/api/boards/${boardId}/send`, { approve }),
  brand: () => call<BrandView>("GET", "/api/brand"),
  brands: () => call<{ brands: BrandSummary[]; reading: BrandRead[] }>("GET", "/api/brands"),
  brandPack: (slug: string) => call<BrandPackView>("GET", `/api/brands/${slug}`),
  readBrand: (url: string, channel = "") => call<BrandRead>("POST", "/api/brands", { url, channel }),
  wearBrand: (channelId: string, brand: string) => call<Channel>("PATCH", `/api/channels/${channelId}`, { brand }),
  skills: () => call<SkillView[]>("GET", "/api/skills"),
  computer: () => call<ComputerView>("GET", "/api/computer"),
};
