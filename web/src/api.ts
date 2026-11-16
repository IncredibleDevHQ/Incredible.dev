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
  version: number;
  resolved: boolean;
  resolved_by: string;
  answered_in: number;
  created_at: number;
};
export type FrameView = {
  id: string;
  name: string;
  note: string;
  position: number;
  verdict: "" | "approved" | "changes";
  verdict_by: string;
  version: number;
  versions: { v: number; url: string; at: number }[];
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
  // Made in a studio of its own (an episode), never by asking the agent for it in a thread.
  studio?: boolean;
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
  // The episodes in this task, each as its card shows it.
  episodes?: EpisodeCard[];
  assets: Asset[];
  boards: Board[];
  files: FileView[];
  work: Work[];
};
export type FolderFile = { path: string; size: number; modified: number };

// -- episodes: a planned explainer, recorded and rendered in its studio (episode_desk.py) --------
export type Presence = "person" | "both" | "content";
export type Level = "simple" | "rich";
export type WriterId = HarnessId | "builtin" | "demo";
export type Box = [number, number, number, number];
export type LayoutSpot = { person: Box | null; picture: Box | null; person_radius: number; picture_radius: number; glass: boolean; zoom: number };
export type EpisodeOptions = {
  writers: { id: WriterId; title: string; ready: boolean; local: boolean }[];
  // A look, with its layouts and who has the frame in each: one picker covers both.
  themes: { id: string; name: string; presenter: "on" | "off"; stage: string; kit: { layout: string; presence: Presence }[] }[];
  // The lengths a person can ask for: the limits, the range the sheet opens on, and how far apart its ends stay.
  seconds: { least: number; most: number; usual: [number, number]; gap: number };
  // Who reads the plan's words: Jev, or the writer's own model.
  reader: "jev" | "writer" | "demo";
  // Whether a narrator can speak here (ElevenLabs has a key), and whether the house has a voice of its own for one.
  narrator: { ready: boolean; usual: boolean };
  geometry: { frame: [number, number]; layouts: Record<string, LayoutSpot> };
  // What a person may pick for the line that brings a picture in: each kind with what it is, each way in with how long it takes.
  pictures: { id: string; means: string }[];
  transitions: { id: string; seconds: number }[];
};
// How long it may run: the least and the most, in seconds, or "auto" when the material decides.
export type EpisodeLength = [number, number] | "auto";
// The voice picked to narrate an episode. `verify`: ElevenLabs wants its speaker verified on its site before it speaks.
export type Narrator = { id: string; name: string; verify?: boolean };
// A voice the ElevenLabs account can speak in: one made in it (a clone), and the house's own.
export type Voice = { id: string; name: string; own: boolean; usual: boolean };
export type EpisodeSettings = {
  seconds: EpisodeLength;
  presenter: "on" | "off";
  theme: string;
  voice: "live" | "narrator";
  narrator?: Narrator;
  level: Level;
  writer: WriterId;
};
export type EpisodeCue = { at: string; object: string; does: string; move?: string; t?: number };
export type EpisodeObject = { id: string; what: string; words?: string; state?: string; type?: string };
export type EpisodeFrame = {
  id: string;
  vo: string;
  presence: Presence;
  layout: string;
  options?: { layout: string; presence: Presence; p: number }[];
  shows?: string;
  hold?: boolean;
  start: number;
  seconds: number;
  words: number;
  objects?: EpisodeObject[];
  cues?: EpisodeCue[];
  picture?: string;
  transition?: string;
  // What the person picked over the plan's reading, for the line that brings a picture in.
  picked?: { picture?: string; transition?: string };
  // The person's own words are on this line: what the writer had, and when they changed it.
  by_person?: { was: string; at: number };
  // A pick of who has the frame or its layout: the line's own, or one set for its chapter or the film.
  override?: { presence: Presence; layout: string; reason: string; scope?: "chapter" | "film" };
};
export type EpisodeBeat = { id: string; says: string; subtype?: string; type?: string; frames: EpisodeFrame[] };
export type EpisodeChapter = { id: string; question: string; type?: string; part?: string; beats: EpisodeBeat[]; start: number; seconds: number; words: number };
export type EpisodePlan = {
  title: string;
  brief: { idea?: string; gap?: string; for?: string; seconds?: [number, number]; presenter?: string; theme?: string };
  chapters: EpisodeChapter[];
  totals: { seconds: number; words: number; chapters: number; beats: number; frames: number; cues: number };
};
export type PictureStatus = "none" | "queued" | "making" | "posing" | "go" | "made" | "failed";
// A rich picture's motion plan, written by its builder before it is drawn: how the picture
// carries its idea, where it happens, and for each of its lines what it opens on, the one move
// the line is about, how the rest lands and what the line's still shows.
// `shot` is the shot in one short sentence, for a person; the rest is the builder's detail.
export type MotionShot = { frame: string; shot: string; opens_on: string; hero: string; others: string; still: string };
export type Motion = { device: string; world: string; shots: MotionShot[] };
export type EpisodeUnit = {
  id: string;
  chapter: string;
  kind: "picture" | "undesigned";
  frames: string[];
  canvas: [number, number];
  layout: string;
  shows: string;
  kind_of_picture: string;
  seconds: number;
  level: Level;
  // Whose the level is: the person's pick for this picture, or the film's.
  level_by: "person" | "film";
  suggest: Level;
  // Who builds it: the agent picked for this picture, else the film's writer.
  builder: WriterId;
  // `status` is "none" until the picture is asked for. `level` and `builder` are what it was
  // built as and by whom (empty for one made before they were kept), `motion` a rich one's
  // plan, `doing` the step its builder is on while it is being made.
  picture: {
    status: PictureStatus;
    level: Level | "";
    builder: string;
    motion: Motion | null;
    stills: Record<string, FileView>;
    clip: FileView | null;
    stale: boolean;
    failure: string;
    note: string;
    doing: string;
  };
};
export type EpisodeTake = {
  id: string;
  chapter: string;
  frame: string;
  n: number;
  seconds: number;
  marks: { frame: string; t: number }[];
  kept: boolean;
  video: FileView | null;
  audio: FileView | null;
  created_at: number;
};
export type EpisodeLine = { frame: string; chapter: string; start: number; seconds: number; source: { kind: "take" | "voice" | "plan"; take?: string; offset?: number } };
export type EpisodeClock = { total: number; chapters: { id: string; start: number; seconds: number }[]; lines: EpisodeLine[]; cues: Record<string, number> };
export type EpisodeCard = {
  id: string;
  thread_id: string;
  asset_id: string;
  title: string;
  status: "planning" | "plan" | "studio" | "failed";
  approved: boolean;
  stage: { name?: string; state?: string; said?: string; round?: number };
  writer: WriterId;
  chapters: number;
  recorded: number;
  pictures: { made: number; go: number; making: number; failed: number };
  film: { status?: "rendering" | "done" | "failed"; fraction?: number; failure?: string };
};
export type EpisodeCheck = { group: string; rule: string; level: "must" | "look"; where: string; text: string };
export type EpisodeRun = { id: string; lane: string; harness: string; state: string; asked: string; said: string; steps: number; started_at: number; ended_at: number | null };
export type EpisodeView = EpisodeCard & {
  channel_id: string;
  settings: EpisodeSettings;
  steps: { id: string; label: string }[];
  plan: EpisodePlan | null;
  // What the writer has put down so far, shown while the plan is still being written.
  written: { material: number; idea: string; chapters: { id: string; question: string; beats: number }[] };
  clock: EpisodeClock | null;
  units: EpisodeUnit[];
  takes: EpisodeTake[];
  film_state: { status?: "rendering" | "done" | "failed"; fraction?: number; failure?: string; file?: FileView | null; stale?: boolean; seconds?: number };
  checks: EpisodeCheck[];
  // Who builds each chapter's pictures: the agent picked for the chapter, else the film's writer.
  builders: Record<string, WriterId>;
  // What the person's picks leave the writer (a line that now needs a picture), waiting for
  // them to apply their changes: nothing is planned or drawn until they do.
  waiting: { line: string; do: string }[];
  runs: EpisodeRun[];
  options: EpisodeOptions;
  // The turn under way or last made: when it began, and a person's own words when they asked for it.
  stage: EpisodeCard["stage"] & { at?: number; asked?: EpisodeAsk | null };
  // The last change to the plan that stands (a person's words, or what the writer did when asked): what it did, what
  // each changed line said before, the lines it cut, and how many changes before it can also be taken back.
  last_change: (EpisodeChange & { at: number; earlier?: number }) | null;
  // The change that was last taken back, while it can still be put back.
  undone: EpisodeChange | null;
  // Lines reworded after they were recorded: the take still says the old words.
  rerecord: string[];
  // The writer's turn on the plan while it works: its steps and its own notes, newest last.
  working: { harness: string; since: number; events: WorkEvent[] } | null;
};
export type WorkEvent = { kind: "step" | "note"; text: string; at: number };
export type AskScope = "film" | "chapter" | "line" | "picture";
export type EpisodeAsk = { scope: AskScope; target?: string; text: string };
export type EpisodeChange = {
  why: string;
  lines: string[];
  was?: Record<string, string>;
  added: string[];
  removed: number;
  cut?: { says: string; chapter: string; after: string }[];
  pictures?: string[];
};
// A pick for a line, a chapter or the film. null takes that pick back and leaves the others.
export type EpisodePick = {
  presence?: Presence | null;
  layout?: string | null;
  layouts?: Partial<Record<Presence, string | null>>;
  picture?: string | null;
  transition?: string | null;
};
export type EpisodeChoices = {
  settings?: Partial<EpisodeSettings>;
  frames?: Record<string, EpisodePick>;
  chapters?: Record<string, EpisodePick>;
  all?: EpisodePick;
  clear?: string[];
  // A picture's level, and who builds it (null gives it back to its chapter's agent).
  units?: Record<string, { level?: Level; builder?: WriterId | null }>;
  // Who builds a chapter's pictures, by chapter (null gives them back to the film's writer).
  builders?: Record<string, WriterId | null>;
};
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
  episodeOptions: () => call<EpisodeOptions>("GET", "/api/episodes/options"),
  newEpisode: (channelId: string, body: { title: string; text: string; files: string[]; from_frame?: string; settings: Partial<EpisodeSettings> }) =>
    call<EpisodeView>("POST", `/api/channels/${channelId}/episodes`, body),
  episode: (id: string) => call<EpisodeView>("GET", `/api/episodes/${id}`),
  approveEpisode: (id: string) => call<EpisodeView>("POST", `/api/episodes/${id}/approve`),
  chooseEpisode: (id: string, body: EpisodeChoices) => call<EpisodeView>("POST", `/api/episodes/${id}/choices`, body),
  // A change asked for in words; the writer makes it (a note on how a picture is drawn goes to its builder).
  askEpisode: (id: string, ask: EpisodeAsk) => call<EpisodeView>("POST", `/api/episodes/${id}/ask`, ask),
  editLine: (id: string, frame: string, text: string) => call<EpisodeView>("POST", `/api/episodes/${id}/lines/${encodeURIComponent(frame)}`, { text }),
  undoEpisode: (id: string) => call<EpisodeView>("POST", `/api/episodes/${id}/undo`),
  redoEpisode: (id: string) => call<EpisodeView>("POST", `/api/episodes/${id}/redo`),
  planAgain: (id: string, writer: WriterId | "" = "") => call<EpisodeView>("POST", `/api/episodes/${id}/again`, { writer }),
  // Stops everything under way for the episode, or the one picture named.
  stopEpisode: (id: string, unit = "") => call<{ ok: boolean }>("POST", `/api/episodes/${id}/stop`, { unit }),
  // Runs what the picks and changes wait on: the writer's part, then the pictures out of date.
  applyEpisode: (id: string) => call<EpisodeView>("POST", `/api/episodes/${id}/apply`),
  // Asks for pictures: the ones named, a chapter's, or with neither the ones that stopped.
  makePictures: (id: string, which: { units?: string[]; chapter?: string } = {}) => call<EpisodeView>("POST", `/api/episodes/${id}/pictures`, which),
  pictureGo: (id: string, unit: string) => call<EpisodeView>("POST", `/api/episodes/${id}/pictures/${encodeURIComponent(unit)}/go`),
  pictureNote: (id: string, unit: string, text: string) =>
    call<EpisodeView>("POST", `/api/episodes/${id}/pictures/${encodeURIComponent(unit)}/note`, { text }),
  addTake: (id: string, take: { chapter: string; frame?: string; marks: { frame: string; t: number }[]; file: Blob; name: string }) => {
    const form = new FormData();
    form.append("file", take.file, take.name);
    form.append("chapter", take.chapter);
    form.append("frame", take.frame ?? "");
    form.append("marks", JSON.stringify(take.marks));
    return call<EpisodeView>("POST", `/api/episodes/${id}/takes`, form);
  },
  voices: () => call<{ voices: Voice[] }>("GET", "/api/voices"),
  // A clone of the person's voice, from this episode's takes or from a recording they bring. `consent` is theirs to give.
  cloneVoice: (id: string, clone: { name: string; consent: boolean; file?: File }) => {
    const form = new FormData();
    form.append("name", clone.name);
    form.append("consent", String(clone.consent));
    if (clone.file) form.append("file", clone.file, clone.file.name);
    return call<EpisodeView>("POST", `/api/episodes/${id}/voice`, form);
  },
  keepTake: (id: string, take: string) => call<EpisodeView>("POST", `/api/episodes/${id}/takes/${take}/keep`, { keep: true }),
  dropTake: (id: string, take: string) => call<EpisodeView>("DELETE", `/api/episodes/${id}/takes/${take}`),
  renderEpisode: (id: string) => call<EpisodeView>("POST", `/api/episodes/${id}/film`),
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
  comment: (frameId: string, body: { text: string; x?: number | null; y?: number | null; parent_id?: string }) =>
    call<Comment>("POST", `/api/frames/${frameId}/comments`, body),
  resolve: (commentId: string, resolved: boolean) =>
    call<{ ok: boolean }>("POST", `/api/comments/${commentId}/resolve`, { resolved }),
  verdict: (frameId: string, verdict: "" | "approved" | "changes") =>
    call<{ ok: boolean }>("POST", `/api/frames/${frameId}/verdict`, { verdict }),
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
