// The engine's web API (src/design_agent/surfaces/web/app.py), typed.

export type Person = { avatar_file?: string; id: string; name: string; initials: string; hue: number; agent: boolean };
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
  state?: "working" | "done" | "failed" | "stopped" | "quiet" | "queued" | "taken" | "folded" | "stop";
  header?: string;
  steps?: Step[];
  notes?: string[];
  // A research turn, as its trail draws it: its steps, its own words and its longer stretches
  // of thinking, newest last, and whether its agent says what its model is doing between them.
  events?: WorkEvent[];
  tells?: boolean;
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
// What can be asked, of what: each agent, the models and efforts each one that is ready offers
// (its own default first), and the repositories on this computer.
export type ResearchOptions = { harnesses: Harness[]; models: Partial<Record<HarnessId, ModelOption[]>>; repos: RepoView[] };
export type Conversation = {
  id: string;
  parent_id: string;
  quote: string;
  harness: HarnessId;
  // what it runs on (empty for the agent's own default): where a branch from it starts
  model: string;
  effort: string;
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
// A research frame. `harness`, `model` and `effort` are what its node asks its next question of:
// the last it asked (an empty model or effort is the agent's own default).
export type ResearchView = { repo: RepoView; harness: HarnessId; model: string; effort: string; conversations: Conversation[]; notes: Note[] };
export type ConversationRow = { id: string; frame_id: string; parent_id: string; quote: string; harness: HarnessId; model: string; effort: string; repo: string };
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
export type PictureGeneration = {provider: string; model: string; effort: string; clip_lines?: Record<string, [number, number]>};
export type ModelOption = { id: string; name: string; efforts: string[]; default_effort?: string; resolves?: string };
export type PicturePick = { level?: Level; builder?: WriterId | null; component?: string | null; variant?: string | null; direction?: string; model?: string; effort?: string };
export type EpisodeOptions = {
  components: Record<string,{purpose:string; layouts:string[]}>;
  picture_writers: {id:WriterId; title:string; ready:boolean; provider:string}[];
  // What each agent can run on. The first row is the agent's own default: where the agent says
  // which model that is and how hard it thinks unasked, the row does too.
  generation_models: Record<string, ModelOption[]>;
  writers: { id: WriterId; title: string; ready: boolean; local: boolean }[];
  // A look, with its layouts and who has the frame in each: one picker covers both.
  themes: { id: string; name: string; presenter: "on" | "off"; stage: string; kit: { layout: string; presence: Presence }[] }[];
  // The lengths a person can ask for: the limits, the range the sheet opens on, and how far apart its ends stay.
  seconds: { least: number; most: number; usual: [number, number]; gap: number };
  // Who reads the plan's words: Jev, or the writer's own model.
  reader: "jev" | "writer" | "demo";
  // Whether a narrator can speak here (ElevenLabs has a key), and whether the house has a voice of its own for one.
  narrator: { ready: boolean; usual: boolean };
  local_narrator: boolean;
  geometry: { frame: [number, number]; layouts: Record<string, LayoutSpot> };
  // What a person may pick for the line that brings a picture in: each kind with what it is, each way in with how long it takes.
  pictures: { id: string; means: string }[];
  transitions: { id: string; seconds: number }[];
};
// How long it may run: the least and the most, in seconds, or "auto" when the material decides.
export type EpisodeLength = [number, number] | "auto";
// The voice picked to narrate an episode. `verify`: ElevenLabs wants its speaker verified on its site before it speaks.
export type Narrator = { id: string; name: string; verify?: boolean };
export type ChannelVoice = Narrator & { preview?: string };
export type VoiceCloneInput = { name: string; consent: boolean; file?: File };
// A voice the ElevenLabs account can speak in: one made in it (a clone), and the house's own.
export type Voice = { id: string; name: string; own: boolean; usual: boolean; preview?: string };
export type BackgroundTexture = "solid" | "dots" | "grid" | "diagonal";
export type EpisodeSettings = {
  background_color?: string;
  portrait?: string;
  background_texture?: BackgroundTexture;
  seconds: EpisodeLength;
  presenter: "on" | "off";
  theme: string;
  voice: "live" | "narrator" | "local";
  narrator?: Narrator;
  cloned_voice?: Narrator;
  level: Level;
  writer: WriterId;
  // The model the film's agent runs on and how hard it thinks; neither is the agent's default.
  writer_model?: string;
  writer_effort?: string;
};
export type EpisodeCue = { at: string; object: string; does: string; move?: string; t?: number };
export type EpisodeObject = { id: string; what: string; words?: string; state?: string; type?: string };
export type EpisodeFrame = {
  has_history?: boolean;
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
  picked?: { picture?: string; transition?: string; window_size?: number | "small" | "large"; window_shape?: string };
  window?: { box: Box; radius: number };
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
// A plan written as a spec also says how each shot is framed and how the view moves (`camera`),
// what fills a stretch its cues leave quiet (`between`), the treatments weighed (the picked one
// first), and the look, the objects, the motion and what is banned, as numbers.
export type MotionShot = { frame: string; shot: string; opens_on: string; hero: string; others: string; still: string; camera?: string; between?: string };
export type Motion = { device: string; world: string; shots: MotionShot[]; treatments?: string[]; look?: string; objects?: string; motion?: string; banned?: string };
export type EpisodeUnit = {
  visual: {component:string; suggested:string; variant_pick:string | null; variant:string; direction:string; automatic:boolean; options:Record<string,string[]>};
  generation: PictureGeneration;
  builder_pick: WriterId | null;
  model_pick: {model:string; effort:string};
  // What it is built on: its own pick, else the film's while the film's agent builds it.
  model_now: { model: string; effort: string; from: "beat" | "film" | "" };
  id: string;
  chapter: string;
  kind: "picture" | "undesigned";
  frames: string[];
  canvas: [number, number];
  layout: string;
  shows: string;
  kind_of_picture: string;
  start: number;
  seconds: number;
  level: Level;
  // Whose the level is: the person's pick for this picture, or the film's.
  level_by: "person" | "film";
  suggest: Level;
  // Who builds it: the agent picked for this picture, else the film's writer.
  builder: WriterId;
  // `status` is "none" until the picture is asked for. `level` and `builder` are what it was
  // built as and by whom (empty for one made before they were kept), `motion` a rich one's
  // plan, `doing` the step its builder is on while it is being made and `live` that turn as
  // it happens: its newest steps and notes, as the plan's trail has the writer's.
  picture: {
    status: PictureStatus;
    generation?: PictureGeneration | null;
    level: Level | "";
    builder: string;
    motion: Motion | null;
    stills: Record<string, FileView>;
    clip: FileView | null;
    stale: boolean;
    // made for words its lines no longer say (it may still fit), and what each changed line
    // said when it was made
    reworded: boolean;
    made_for: Record<string, string>;
    failure: string;
    note: string;
    doing: string;
    live: LiveTurn | null;
    // its latest build stage by stage, what its builder said when it reviewed it, and the notes
    // the person left the builder while it worked: waiting for its next turn, or taken in; and
    // whether a note would still reach it (a motion-graphics picture before its review)
    stages: BuildStage[];
    // how long the build has taken in all: while it runs, when it began; once it ends, as the
    // beat's record keeps it (null before a build, or for one the house did not date)
    timing: BuildTiming | null;
    // which version it is (or will be, while it is made), counting up from 1, and the ones it
    // stood as before, the one it last stood as first, to look back at and to put back
    version: number;
    versions: PictureVersion[];
    reviewed: string;
    queued: SteerNote[];
    steered: SteerNote[];
    steerable: boolean;
  };
};
export type BuildTiming = { started_at: number | null; ended_at: number | null; seconds: number | null };
// A version of a picture kept to look back at and to put back: its number, its stills and clip,
// how and by whom it was made, when its build ended and how long that took.
export type PictureVersion = {
  n: number;
  stills: Record<string, FileView>;
  clip: FileView | null;
  level: Level | "";
  builder: string;
  generation: PictureGeneration | null;
  made_at: number | null;
  seconds: number | null;
};
// One stage of a picture's build: the builder's turns (plan, draw, review), the stills the house
// takes between the drawing and the review, and a motion-graphics picture's go, which is the
// person's. Times are seconds since the epoch.
export type BuildStageId = "motion" | "draw" | "pose" | "review" | "go";
export type BuildStage = {
  id: BuildStageId;
  state: "pending" | "running" | "done" | "failed" | "waiting";
  started_at: number | null;
  ended_at: number | null;
};
// A note a person left a picture's builder while it worked; one taken in says the stage it went to.
export type SteerNote = { id: string; text: string; at: number; stage?: BuildStageId; given_at?: number };
// What a take's recording was: the studio's own take, a file brought in, or a camera's clip (its
// name, when it was recorded, its height and frame rate, a line of what the house noticed, and,
// matched to a studio take by sound, which take and where it began in the clip).
export type TakeRecording = {
  kind?: "studio" | "file" | "camera";
  name?: string;
  at?: number;
  height?: number;
  fps?: number;
  note?: string;
  matched?: { take: string; n: number; score: number; start: number };
};
export type EpisodeTake = {
  id: string;
  label?: string;
  chapter: string;
  frame: string;
  n: number;
  seconds: number;
  marks: { frame: string; t: number }[];
  kept: boolean;
  video: FileView | null;
  audio: FileView | null;
  // its copy for a film in 4K, when it was recorded taller than the film's frame
  uhd: FileView | null;
  recording: TakeRecording;
  // where the recording is kept as it arrived (a folder, or s3://)
  kept_at: string;
  created_at: number;
};
// A recording being brought in for a chapter, while it is, or one that couldn't be (`failed`).
export type EpisodeImport = {
  chapter: string;
  take: string;
  name: string;
  guide: string;
  state: "copying" | "matching" | "cutting" | "saving" | "failed";
  done?: number;
  total?: number;
  fraction?: number;
  failure?: string;
  started_at?: number;
  ended_at?: number;
};
// A clip on a camera's card in this computer, read where it is.
export type CameraClip = { path: string; name: string; card: string; size: number; seconds: number; recorded_at: number; look: string; fps: string };
export type FilmSize = "hd" | "4k";
export type EpisodeLine = { audio_url?: string; frame: string; chapter: string; start: number; seconds: number; source: { kind: "take" | "voice" | "plan"; take?: string; offset?: number } };
// `marks` are what the film shows that no line says: its title before the first line, a chapter's
// card over its first words, the end card after the last line.
export type EpisodeClock = {
  total: number;
  chapters: { id: string; start: number; seconds: number }[];
  lines: EpisodeLine[];
  cues: Record<string, number>;
  marks: { mark: "title-sting" | "chapter-card" | "end-card"; start: number; seconds: number; chapter?: string }[];
};
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
  film: { status?: "rendering" | "done" | "failed"; fraction?: number; failure?: string; seconds?: number; size?: FilmSize | null; making?: FilmSize | null; poster?: FileView | null };
};
export type EpisodeCheck = { group: string; rule: string; level: "must" | "look"; where: string; text: string };
export type EpisodeRun = { id: string; lane: string; harness: string; state: string; asked: string; said: string; steps: number; started_at: number; ended_at: number | null };
// One stage of the plan as its page times it: from when the house moved to it until the next
// began (checking the plan runs from the writer's last turn). Times are seconds since the epoch.
export type PlanStage = { id: string; state: "pending" | "running" | "done" | "failed"; started_at: number | null; ended_at: number | null };
export type EpisodeView = EpisodeCard & {
  background: {color: string; brand_color: string; textures: Record<BackgroundTexture, [string, string]>};
  channel_id: string;
  settings: EpisodeSettings;
  channel_voices: ChannelVoice[];
  steps: { id: string; label: string }[];
  // the plan's stages with their times; none for a plan written before the house dated them
  plan_stages: PlanStage[];
  plan: EpisodePlan | null;
  // What the writer has put down so far, shown while the plan is still being written.
  sample_notes?: string | null;
  written: { material: number; idea: string; chapters: { id: string; question: string; beats: number }[] };
  clock: EpisodeClock | null;
  units: EpisodeUnit[];
  takes: EpisodeTake[];
  imports: EpisodeImport[];
  // `size` is the rendered film's; `making`, the size asked for last; `upscaled`, how many takes
  // a film in 4K showed from their HD copy
  film_state: { started_at?: number; ended_at?: number; phase?: string; frames_done?: number; frames_total?: number; blocked?: string; status?: "rendering" | "done" | "failed"; fraction?: number; failure?: string; file?: FileView | null; stale?: boolean; seconds?: number; size?: FilmSize; making?: FilmSize; upscaled?: number };
  checks: EpisodeCheck[];
  // Who builds each chapter's pictures: the agent picked for the chapter, else the film's writer.
  builders: Record<string, WriterId>;
  // What the person's picks leave the writer (a line that now needs a picture), waiting for
  // them to apply their changes: nothing is planned or drawn until they do.
  // What the person's changes leave the writer, run when they apply them: a line given a picture
  // by a pick, a line they added with one, or a line whose new words a picture's step no longer finds.
  waiting: { line: string; do: string; kind: "pick" | "added" | "words" }[];
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
  working: LiveTurn | null;
};
// A step an agent took, its own words, or a stretch of thinking that ended (`seconds` long,
// `text` its summary where the agent gives one).
export type WorkEvent = { kind: "step" | "note" | "thought"; text: string; at: number; seconds?: number };
// What a turn's model is doing between two of its steps, as the agent's own stream says it:
// "thinking" (`text` the newest words of the thought, `amount` its tokens so far), "writing" its
// own words, or "step" for a tool call it is writing (`text` the step it will be, `amount` the
// characters so far). `at` is when the turn was last heard from, `since` when it began this.
export type WorkPulse = { at: number; since: number; doing: "" | "thinking" | "writing" | "step"; text: string; amount: number };
// A turn under way: who runs it, since when, its newest events and its pulse. `tells` is
// whether this agent says what its model is doing as it goes (a long silence from one that
// does means something is wrong; the others say nothing while they think).
export type LiveTurn = { harness: string; since: number; tells: boolean; pulse: WorkPulse | null; events: WorkEvent[] };
// The production board: every job of every episode in one read. A job is a picture to draw (a
// run of beats of one chapter) or an episode's script. `state` is where it stands: "todo" (its
// lines are written and it was never asked for, or it is made and out of date, `stale`),
// "waiting" its turn, "running", "go" (it waits on the person: a go on its stills, a plan to
// approve), "failed" or "done". `agent`, `model` and `effort` are who it is set to, or who made
// it. While its turn runs it carries that turn's liveness as a trail does (`LiveTurn`).
export type JobState = "todo" | "waiting" | "running" | "go" | "failed" | "done";
export type ProductionJob = {
  id: string;
  what: "picture" | "script";
  episode: string;
  unit: string;
  chapter: string;
  kind: string;
  shows: string;
  says: string;
  beats: number[];
  lines: number;
  level: Level;
  state: JobState;
  stale: boolean;
  agent: string;
  model: string;
  effort: string;
  picked: boolean;
  failure: string;
  stage: string;
  doing: string;
  asked_at: number | null;
  started_at: number | null;
  ended_at: number | null;
  seconds: number | null;
  still: string | null;
  tells: boolean;
  heard_at: number | null;
  pulse: WorkPulse | null;
};
// An agent the board hands work to: whether it is ready on this computer, what it can run on, how
// many of its jobs run and wait across the house, and how long its pictures have taken (the mean
// of its last builds, where it has made any).
export type ProductionAgent = { id: string; title: string; ready: boolean; models: ModelOption[]; running: number; waiting: number; seconds: number | null };
export type ProductionEpisode = { id: string; title: string; channel_id: string; channel: string; status: string; writer: string; chapters: { id: string; n: number; question: string }[] };
export type ProductionView = { agents: ProductionAgent[]; episodes: ProductionEpisode[]; jobs: ProductionJob[] };
export type HandOver = { jobs: { episode: string; unit: string }[]; agent: string; model: string; effort: string; start: boolean };
export type HandedOver = { started: string[]; refused: { episode: string; reason: string }[] };
export type AskScope = "film" | "chapter" | "line" | "picture";
// What a line a person adds is: more of its block, said to camera, or a picture of a type.
export type PictureKind = "diagram" | "list" | "typeset-code" | "chips" | "illustration" | "slide";
export type LineKind = "more" | "camera" | PictureKind;
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
  window_size?: number | "small" | "large" | null;
  window_shape?: string | null;
  presence?: Presence | null;
  layout?: string | null;
  layouts?: Partial<Record<Presence, string | null>>;
  picture?: string | null;
  transition?: string | null;
};
export type EpisodeChoices = {
  settings?: Partial<Omit<EpisodeSettings, "narrator">> & { narrator?: Narrator | null };
  frames?: Record<string, EpisodePick>;
  chapters?: Record<string, EpisodePick>;
  all?: EpisodePick;
  clear?: string[];
  // A picture's level, and who builds it (null gives it back to its chapter's agent).
  units?: Record<string, PicturePick>;
  // Who builds a chapter's pictures, by chapter (null gives them back to the film's writer).
  builders?: Record<string, WriterId | null>;
};
export type Session = {
  projectId?: string;
  projectUrl?: string;
  email?: string | null;
  organizationName?: string;
  authenticated?: boolean;
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

const person = "you";
export const actingAs = () => person;

async function request(method: string, path: string, body?: unknown): Promise<Response> {
  const response = await fetch(path, {
    method,
    headers: { "X-Person": person, ...(body instanceof FormData || body === undefined ? {} : { "Content-Type": "application/json" }) },
    body: body instanceof FormData ? body : body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    if (response.status === 401) window.dispatchEvent(new Event("incredible:signout"));
    let detail = response.statusText;
    try {
      detail = (await response.json()).detail ?? detail;
    } catch {
      /* not JSON */
    }
    throw new Error(typeof detail === "string" ? detail : "Request failed");
  }
  return response;
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  return (await (await request(method, path, body)).json()) as T;
}

export type UsagePeriod = "today" | "week" | "month";
export type UsageCounts = {calls: number; input_tokens: number; output_tokens: number; usd: number; unpriced: number};
export type UsageReport = {
  totals: UsageCounts;
  series: (UsageCounts & {at: number})[];
  models: (UsageCounts & {model: string})[];
};
export type ChatDefaults = { options: { id:string; provider:string; name:string; default_effort?:string; efforts:string[] }[]; default:string; model:string; effort:string };
export type Organization = { name: string; website: string; description: string };

function voiceCloneForm(clone: VoiceCloneInput): FormData {
  const form = new FormData();
  form.append("name", clone.name);
  form.append("consent", String(clone.consent));
  if (clone.file) form.append("file", clone.file, clone.file.name);
  return form;
}

export type VoiceTestClip = {text?: string | null; id: string; name: string; expires_at: number};

export type AccountDetails = {first_name?:string; last_name?:string; username?:string | null};
export type Team = {project:string; personal_url:string; owner:string; can_manage:boolean; members:{id:string;email:string;member:string|null;invite_url?:string}[];
  incoming:{id:string;email:string;owner:string;member:string|null;url:string}[]};
export type ActivityLog = {actors:{actor:string;email:string}[]; events:{id:string;duration_ms?:number|null;member_email?:string|null;actor:string;actor_email:string;action:string;happened:number;status:number}[];more:boolean};

export const api = {
  accountDetails: () => call<AccountDetails>("GET","/api/account/details"),
  saveAccountDetails: (body:AccountDetails) => call<AccountDetails>("PUT","/api/account/details",body),
  team: () => call<Team>("GET","/api/team"),
  invite: (email:string) => call<{id:string;invite_url:string;email_sent:boolean}>("POST","/api/team/invite",{email}),
  removeMember: (id:string) => call("DELETE","/api/team/"+encodeURIComponent(id)),
  previewInvitation: (id:string) => call<{organization:string;accepted:boolean}>("GET","/api/team/"+encodeURIComponent(id)),
  enterProject: (id:string) => call<{url:string}>("POST","/api/team/"+encodeURIComponent(id)+"/accept"),
  logInteraction: (action:string) => call("POST","/api/activity/interaction",{action}),
  activity: (actor:string,before?:number) => call<ActivityLog>("GET","/api/activity?actor_id="+encodeURIComponent(actor)+(before ? "&before="+before : "")),
  voiceTests: (episode: string) => call<{clips: VoiceTestClip[]}>("GET", `/api/episodes/${episode}/voice-tests`),
  createVoiceTest: (episode: string, clone: VoiceCloneInput & {file: File; text?: string}) => {
    const form = voiceCloneForm(clone);
    if (clone.text !== undefined) form.append("text", clone.text);
    return call<VoiceTestClip>("POST", `/api/episodes/${episode}/voice-tests`, form);
  },
  voiceTestAudio: async (episode: string, id: string, kind: "original" | "clone") =>
    (await request("GET", `/api/episodes/${episode}/voice-tests/${id}/${kind}`)).blob(),
  usageReport: (period: UsagePeriod) => call<UsageReport>("GET", "/api/usage/report?period=" + period),
  uploadAvatar: (file: File) => {
    const body = new FormData();
    body.append("file", file);
    return call<Person>("POST", "/api/profile/avatar", body);
  },
  saveProfile: (name: string, hue: number) => call<Person>("PUT", "/api/profile", {name, hue}),
  modelDefaults: () => call<ChatDefaults>("GET", "/api/preferences/model"),
  saveModelDefaults: (model:string, effort:string) => call<{model:string; effort:string}>("PUT", "/api/preferences/model", {model,effort}),
  passwordState: () => call<{user: {has_password: boolean}}>("GET", "/api/auth/session"),
  verifyPassword: (password:string) => call<{verified:boolean}>("POST", "/api/auth/password/verify", {password}),
  savePassword: (password: string, current_password?: string) => call<{has_password: boolean}>("POST", "/api/auth/password", {password,current_password}),
  organization: () => call<Organization>("GET", "/api/organization"),
  saveOrganization: (profile: Organization) => call<Organization>("PUT", "/api/organization", profile),
  usage: () => call<{calls: number; input_tokens: number; output_tokens: number; usd: number; unpriced: number}>("GET", "/api/usage"),
  session: () => call<Session>("GET", "/api/session"),
  channels: () => call<Channel[]>("GET", "/api/channels"),
  addChannel: (name: string, topic = "") => call<Channel>("POST", "/api/channels", { name, topic }),
  channelMessages: (id: string) => call<ChannelMessages>("GET", `/api/channels/${id}/messages`),
  startThread: (channelId: string, body: { text: string; to_agent: boolean; files: string[]; kind?: string }) => call<Message>("POST", `/api/channels/${channelId}/messages`, body),
  thread: (id: string) => call<ThreadDetail>("GET", `/api/threads/${id}`),
  // `quote`: a passage of the answer a research follow-up asks about
  reply: (threadId: string, body: { text: string; to_agent: boolean; files: string[]; answers?: string; quote?: string }) => call<Message>("POST", `/api/threads/${threadId}/messages`, body),
  pickLook: (boardId: string, frameId: string, reason: string) => call<Message>("POST", `/api/boards/${boardId}/pick`, { frame_id: frameId, reason }),
  stop: (threadId: string) => call<{ ok: boolean }>("POST", `/api/threads/${threadId}/stop`),
  cancelWork: (threadId: string, workId: string) => call<{ said: string }>("POST", `/api/threads/${threadId}/work/${workId}/cancel`),
  upload: (files: File[]) => {
    const form = new FormData();
    for (const file of files) form.append("files", file);
    return call<FileView[]>("POST", "/api/uploads", form);
  },
  canvas: (channelId: string) => call<CanvasTask[]>("GET", `/api/channels/${channelId}/canvas`),
  catalog: () => call<Catalog>("GET", "/api/catalog"),
  renderFilm: (assetId: string) => call<Message>("POST", `/api/assets/${assetId}/render`),
  approveDraft: (assetId: string) => call<Message>("POST", `/api/assets/${assetId}/approve`),
  addAsset: (threadId: string, body: { kind: string; sources: string[]; note: string }) => call<Asset>("POST", `/api/threads/${threadId}/assets`, body),
  placeTemplate: (channelId: string, body: { template: string; text: string; files: string[]; from_asset: string; from_frame?: string }) =>
    call<Message>("POST", `/api/channels/${channelId}/templates`, body),
  episodeOptions: () => call<EpisodeOptions>("GET", "/api/episodes/options"),
  newEpisode: (channelId: string, body: { title: string; text: string; files: string[]; from_frame?: string; resolve_links?: boolean; settings: Partial<EpisodeSettings> }) =>
    call<EpisodeView>("POST", `/api/channels/${channelId}/episodes`, body),
  episode: (id: string) => call<EpisodeView>("GET", `/api/episodes/${id}`),
  production: () => call<ProductionView>("GET", "/api/production"),
  handOver: (body: HandOver) => call<HandedOver>("POST", "/api/production/assign", body),
  approveEpisode: (id: string) => call<EpisodeView>("POST", `/api/episodes/${id}/approve`),
  chooseEpisode: (id: string, body: EpisodeChoices) => call<EpisodeView>("POST", `/api/episodes/${id}/choices`, body),
  // A change asked for in words; the writer makes it (a note on how a picture is drawn goes to its builder).
  askEpisode: (id: string, ask: EpisodeAsk) => call<EpisodeView>("POST", `/api/episodes/${id}/ask`, ask),
  lineHistory: (id: string, frame: string) => call<{entries: {id: number; at: number; reason: string; changes: {label: string; before: string; after: string}[]}[]}>("GET", `/api/episodes/${id}/lines/${encodeURIComponent(frame)}/history`),
  editLine: (id: string, frame: string, text: string) => call<EpisodeView>("POST", `/api/episodes/${id}/lines/${encodeURIComponent(frame)}`, { text }),
  // A line a person adds after another (or first in a chapter, by the chapter's id): going on in
  // its block, said to camera, or bringing in a picture of a type. `keep` is what the line it
  // was split from keeps.
  addLine: (id: string, line: { after: string; text: string; kind: LineKind; keep?: string }) => call<EpisodeView>("POST", `/api/episodes/${id}/lines`, line),
  // Lines a person cuts; with `join`, the one line's words go on at the end of the line before it
  // (as `words`, when the person changed that line's words too).
  cutLines: (id: string, frames: string[], join = false, words?: string) => call<EpisodeView>("POST", `/api/episodes/${id}/cut`, { frames, join, words }),
  // Pictures made for words their lines no longer say: the writer fits them to the new words,
  // then they are drawn again.
  replanPictures: (id: string, units: string[]) => call<EpisodeView>("POST", `/api/episodes/${id}/replan`, { units }),
  // A version of a picture made before, put back: it stands again as it was made, and the one
  // that stood is kept in its place. A build under way for the picture is stopped.
  putVersionBack: (id: string, unit: string, n: number) =>
    call<EpisodeView>("POST", `/api/episodes/${id}/pictures/${encodeURIComponent(unit)}/versions/${n}/use`),
  // A picture made for other words, kept as it is for the words its lines say now.
  keepPicture: (id: string, unit: string) => call<EpisodeView>("POST", `/api/episodes/${id}/pictures/${encodeURIComponent(unit)}/keep`),
  // a note for a picture's builder while it works, for its next turn, and taking one back
  steerPicture: (id: string, unit: string, text: string) =>
    call<EpisodeView>("POST", `/api/episodes/${id}/pictures/${encodeURIComponent(unit)}/steer`, { text }),
  unsteerPicture: (id: string, unit: string, note: string) =>
    call<EpisodeView>("DELETE", `/api/episodes/${id}/pictures/${encodeURIComponent(unit)}/steer/${encodeURIComponent(note)}`),
  undoEpisode: (id: string) => call<EpisodeView>("POST", `/api/episodes/${id}/undo`),
  redoEpisode: (id: string) => call<EpisodeView>("POST", `/api/episodes/${id}/redo`),
  planAgain: (id: string, writer: WriterId | "" = "", pick?: { model: string; effort: string }) =>
    call<EpisodeView>("POST", `/api/episodes/${id}/again`, { writer, ...pick }),
  // Stops everything under way for the episode, or the one picture named.
  stopEpisode: (id: string, unit = "") => call<{ ok: boolean }>("POST", `/api/episodes/${id}/stop`, { unit }),
  // Runs what the picks and changes wait on: the writer's part, then the pictures out of date.
  applyEpisode: (id: string) => call<EpisodeView>("POST", `/api/episodes/${id}/apply`),
  // Asks for pictures: the ones named, a chapter's, or with neither the ones that stopped.
  // with a level, the pictures named are made again that way (the person's yes to switching them)
  previewVoice: (id: string, chapter: string) => call<EpisodeView>("POST", `/api/episodes/${id}/chapters/${chapter}/preview-voice`, {}),
  previewPicture: (id: string, unit: string) => call<FileView>("POST", `/api/episodes/${id}/pictures/${unit}/preview`, {}),
  makePictures: (id: string, which: { units?: string[]; chapter?: string; level?: Level } = {}) => call<EpisodeView>("POST", `/api/episodes/${id}/pictures`, which),
  regenerateChapter: (id: string, chapter: string, generation?: { provider: Exclude<WriterId, "demo">; model: string }) =>
    call<EpisodeView>("POST", `/api/episodes/${id}/chapters/${encodeURIComponent(chapter)}/regenerate`, generation ?? {}),
  pictureGo: (id: string, unit: string) => call<EpisodeView>("POST", `/api/episodes/${id}/pictures/${encodeURIComponent(unit)}/go`),
  pictureNote: (id: string, unit: string, text: string) => call<EpisodeView>("POST", `/api/episodes/${id}/pictures/${encodeURIComponent(unit)}/note`, { text }),
  // A take: one recorded in the studio (with its marks) is cut while this waits; a file brought
  // with none, or a camera's file to match to a take by sound (`guide`), comes in meanwhile.
  addTake: (id: string, take: { label?: string; chapter: string; frame?: string; marks: { frame: string; t: number }[]; file: Blob; name: string; guide?: string; startedAt?: number }) => {
    const form = new FormData();
    form.append("file", take.file, take.name);
    form.append("chapter", take.chapter);
    form.append("label", take.label ?? "");
    form.append("frame", take.frame ?? "");
    form.append("marks", JSON.stringify(take.marks));
    if (take.guide) form.append("guide", take.guide);
    if (take.startedAt) form.append("started_at", String(take.startedAt));
    return call<EpisodeView>("POST", `/api/episodes/${id}/takes`, form);
  },
  cameraClips: () => call<{ clips: CameraClip[]; folders: string[] }>("GET", "/api/camera"),
  // A card's clip brought in where it is: no upload, whatever its size.
  cameraTake: (id: string, take: { chapter: string; path: string; guide?: string }) =>
    call<EpisodeView>("POST", `/api/episodes/${id}/takes/camera`, take),
  forgetImport: (id: string, chapter: string) => call<EpisodeView>("DELETE", `/api/episodes/${id}/imports/${encodeURIComponent(chapter)}`),
  voices: () => call<{ voices: Voice[] }>("GET", "/api/voices"),
  channelVoices: (channel: string) => call<{ voices: ChannelVoice[] }>("GET", `/api/channels/${channel}/voices`),
  cloneChannelVoice: (channel: string, clone: VoiceCloneInput & { file: File }) =>
    call<ChannelVoice>("POST", `/api/channels/${channel}/voices`, voiceCloneForm(clone)),
  previewChannelVoice: (episode: string, voice: string) =>
    call<{ url: string }>("POST", `/api/episodes/${episode}/voice/${encodeURIComponent(voice)}/preview`, {}),
  // A clone of the person's voice, from this episode's takes or from a recording they bring. `consent` is theirs to give.
  cloneVoice: (id: string, clone: VoiceCloneInput) =>
    call<EpisodeView>("POST", `/api/episodes/${id}/voice`, voiceCloneForm(clone)),
  keepTake: (id: string, take: string) => call<EpisodeView>("POST", `/api/episodes/${id}/takes/${take}/keep`, { keep: true }),
  dropTake: (id: string, take: string) => call<EpisodeView>("DELETE", `/api/episodes/${id}/takes/${take}`),
  // With no size, the film is rendered in the size asked for last (HD at first).
  renderEpisode: (id: string, size?: FilmSize) => call<EpisodeView>("POST", `/api/episodes/${id}/film`, size ? { size } : {}),
  researchOptions: () => call<ResearchOptions>("GET", "/api/research"),
  openResearch: (channelId: string, body: { repo: string; harness: HarnessId; question: string; model?: string; effort?: string }) =>
    call<{ thread: Thread; conversation: ConversationRow }>("POST", `/api/channels/${channelId}/research`, body),
  ask: (frameId: string, body: { question: string; harness?: HarnessId | ""; model?: string; effort?: string; parent?: string; quote?: string; answer?: string }) =>
    call<ConversationRow>("POST", `/api/research/${frameId}/conversations`, body),
  // The frame's notes as one page, as everything made from them is handed them.
  notesPage: (frameId: string) => `/api/research/${frameId}/notes.md`,
  keepNote: (frameId: string, body: { text: string; conversation_id?: string; message_id?: string }) => call<Note>("POST", `/api/research/${frameId}/notes`, body),
  editNote: (noteId: string, text: string) => call<Note>("PATCH", `/api/notes/${noteId}`, { text }),
  dropNote: (noteId: string) => call<{ ok: boolean }>("DELETE", `/api/notes/${noteId}`),
  folder: (threadId: string) => call<FolderFile[]>("GET", `/api/threads/${threadId}/folder`),
  folderUrl: (threadId: string, path: string) => `/api/threads/${threadId}/folder/file?path=${encodeURIComponent(path)}`,
  comment: (frameId: string, body: { text: string; x?: number | null; y?: number | null; parent_id?: string }) => call<Comment>("POST", `/api/frames/${frameId}/comments`, body),
  resolve: (commentId: string, resolved: boolean) => call<{ ok: boolean }>("POST", `/api/comments/${commentId}/resolve`, { resolved }),
  verdict: (frameId: string, verdict: "" | "approved" | "changes") => call<{ ok: boolean }>("POST", `/api/frames/${frameId}/verdict`, { verdict }),
  sendBoard: (boardId: string, approve: boolean) => call<Message>("POST", `/api/boards/${boardId}/send`, { approve }),
  brand: () => call<BrandView>("GET", "/api/brand"),
  brands: () => call<{ brands: BrandSummary[]; reading: BrandRead[] }>("GET", "/api/brands"),
  brandPack: (slug: string) => call<BrandPackView>("GET", `/api/brands/${slug}`),
  readBrand: (url: string, channel = "") => call<BrandRead>("POST", "/api/brands", { url, channel }),
  wearBrand: (channelId: string, brand: string) => call<Channel>("PATCH", `/api/channels/${channelId}`, { brand }),
  skills: () => call<SkillView[]>("GET", "/api/skills"),
  computer: () => call<ComputerView>("GET", "/api/computer"),
};
