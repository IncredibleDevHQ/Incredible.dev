// New episodes start from notes or a research frame. The sample writer is an explicit choice.
import { Paperclip, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, type ChannelVoice, type EpisodeOptions, type EpisodeSettings, type FileView, type WriterId } from "../../api";
import { keepWriter, lastWriter, LOOKS, mmss } from "../../episode";
import { useHouse, type EpisodeStart } from "../../store";
import { FileList } from "../../ui";
import { FileDrop } from "../FileDrop";
import { RangeSlider } from "../RangeSlider";
import { Select } from "../Select";
import { SegmentedControl } from "../SegmentedControl";
import { TextArea } from "../TextArea";
import { TextField } from "../TextField";
import { AgentModel, offersPicks, type ModelPick } from "./AgentModel";
import { ChannelVoices, CloneDialog } from "./Voice";

// What the notes can be read from, by name: a dragged Markdown file often says no type at all.
const TEXT_FILE = /\.(md|markdown|mdx|txt|rst|json|csv|html?)$/i;

export function NewEpisode({ start }: { start: EpisodeStart }) {
  const channelId = useHouse((s) => s.channelId);
  const startEpisode = useHouse((s) => s.startEpisode);
  const openEpisode = useHouse((s) => s.openEpisode);
  const [options, setOptions] = useState<EpisodeOptions | null>(null);
  const [title, setTitle] = useState(start.title ?? "");
  const [text, setText] = useState(start.notes ?? "");
  const [files, setFiles] = useState<FileView[]>([]);
  const [range, setRange] = useState<[number, number]>([300, 420]);
  const [auto, setAuto] = useState(false);
  const [presenter, setPresenter] = useState<"on" | "off">("on");
  const [theme, setTheme] = useState("corner-window");
  const [voice, setVoice] = useState<EpisodeSettings["voice"] | "clone" | null>(null);
  const [voiceLibrary, setVoiceLibrary] = useState<{ channel: string; voices: ChannelVoice[] } | null>(null);
  const [voiceId, setVoiceId] = useState<string>();
  const [voiceProblem, setVoiceProblem] = useState("");
  const [voiceRetry, setVoiceRetry] = useState(0);
  const [cloneOpen, setCloneOpen] = useState(false);
  const [writer, setWriter] = useState<WriterId | null>(null);
  // the model the writer runs on and how hard it thinks; neither picked is the writer's default
  const [pick, setPick] = useState<ModelPick>({ model: "", effort: "" });
  const [busy, setBusy] = useState(false);
  // The layout can be changed after planning.
  const [more, setMore] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const close = () => startEpisode(null);
  const clones = voiceLibrary?.channel === channelId ? voiceLibrary?.voices : undefined;
  const selectedClone = clones?.find((item) => item.id === voiceId);

  useEffect(() => {
    void api
      .episodeOptions()
      .then((o) => {
        setOptions(o);
        setRange(o.seconds.usual);
        setVoice(o.local_narrator ? "local" : "live");
        // the agent picked last on this computer, while it is ready; else the first that is
        const last = lastWriter();
        const writers = o.writers.filter((w) => w.ready && w.id !== "demo");
        setWriter(writers.find((w) => w.id === last)?.id ?? writers[0]?.id ?? null);
      })
      .catch((error: Error) => useHouse.getState().say(error.message));
  }, []);

  useEffect(() => {
    if (voice !== "clone" || !channelId || clones) return;
    let active = true;
    setVoiceProblem("");
    void api.channelVoices(channelId).then(
      ({ voices }) => { if (active) setVoiceLibrary({ channel: channelId, voices }); },
      (error: Error) => { if (active) setVoiceProblem(error.message); },
    );
    return () => { active = false; };
  }, [channelId, clones, voice, voiceRetry]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && !cloneOpen && startEpisode(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [cloneOpen, startEpisode]);

  const attach = async (picked: File[]) => {
    if (!picked.length) return;
    try {
      const added = await api.upload(picked);
      setFiles((f) => [...f, ...added]);
    } catch (error) {
      useHouse.getState().say((error as Error).message);
    }
  };

  const hasMaterial = Boolean(start.frame) || text.trim().length > 0 || files.length > 0;
  const plan = async () => {
    if (!channelId || !writer || !voice || !hasMaterial || (voice === "clone" && !selectedClone)) return;
    setBusy(true);
    keepWriter(writer);
    try {
      const view = await api.newEpisode(channelId, {
        title: title.trim(),
        text,
        files: files.map((f) => f.id),
        from_frame: start.frame,
        resolve_links: text !== start.notes,
        settings: {
          seconds: auto ? "auto" : range,
          presenter,
          theme: presenter === "off" ? "voice-only" : theme,
          writer,
          voice: voice === "clone" ? "narrator" : voice,
          ...(voice === "clone" && selectedClone ? { narrator: { id: selectedClone.id, name: selectedClone.name } } : {}),
          ...(pick.model || pick.effort ? { writer_model: pick.model, writer_effort: pick.effort } : {}),
        },
      });
      startEpisode(null);
      useHouse.getState().setMode("canvas");
      await openEpisode(view.id);
    } catch (error) {
      useHouse.getState().say((error as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const themes = options?.themes.filter((t) => t.presenter === "on") ?? [];
  const nobody = Boolean(options) && !options?.writers.some((w) => w.ready && w.id !== "demo");
  return (
    <div className="picker ep-new" role="dialog" aria-modal="true" aria-label="New episode">
      <FileDrop
        className="picker-panel"
        label="Drop your notes here"
        refusal="Notes are text: a Markdown, text, HTML, JSON or CSV file."
        disabled={Boolean(start.frame)}
        accepts={(file) => file.type.startsWith("text/") || TEXT_FILE.test(file.name)}
        onFiles={(dropped) => void attach(dropped)}
      >
        <header className="picker-head">
          <h2>New episode</h2>
          <button type="button" className="icon-btn" aria-label="Close" onClick={close}>
            <X />
          </button>
        </header>
        <p className="picker-lede">Choose who narrates your episode, then plan its chapters.</p>
        <div className="ep-new-grid">
          <section>
            <TextField label="Working title" optional value={title} onChange={(e) => setTitle(e.target.value)} placeholder="What it explains" />
            {start.frame ? (
              <p className="ep-new-from">Planned from the notes kept on this research frame.</p>
            ) : (
              <>
                <TextArea
                  label="Notes"
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  placeholder="Paste a post, docs or rough notes, or drop a file here. Links are read."
                  minRows={8}
                  maxRows={16}
                />
                <div className="ep-new-files">
                  <button type="button" className="btn" onClick={() => input.current?.click()}>
                    <Paperclip />
                    Add text files
                  </button>
                  <input ref={input} type="file" multiple accept=".md,.markdown,.txt,.rst,.json,.csv,.html,text/*" hidden onChange={(e) => void attach([...(e.target.files ?? [])])} />
                  {files.length > 0 && <FileList files={files} />}
                </div>
              </>
            )}
          </section>
          <section className="ep-new-facts">
            <div className="ep-new-row ep-new-length">
              <div className="ep-new-length-head">
                <span>
                  Length
                  {!auto && (
                    <b>
                      {mmss(range[0])} to {mmss(range[1])}
                    </b>
                  )}
                </span>
                <SegmentedControl
                  size="sm"
                  aria-label="Length"
                  value={auto ? "auto" : "range"}
                  onChange={(v) => setAuto(v === "auto")}
                  options={[
                    { value: "range", label: "Range" },
                    { value: "auto", label: "Auto" },
                  ]}
                />
              </div>
              {auto ? (
                <p className="ep-new-from">As long as your notes need.</p>
              ) : (
                <RangeSlider
                  min={options?.seconds.least ?? 240}
                  max={options?.seconds.most ?? 600}
                  step={30}
                  gap={options?.seconds.gap ?? 30}
                  value={range}
                  onChange={setRange}
                  labels={["Shortest length", "Longest length"]}
                  format={mmss}
                />
              )}
            </div>
            <div className="ep-new-row">
              <span>On camera</span>
              <SegmentedControl
                size="sm"
                value={presenter}
                onChange={setPresenter}
                options={[
                  { value: "on", label: "You present" },
                  { value: "off", label: "Voice only" },
                ]}
              />
            </div>
            <Select
              label="Narration voice"
              value={voice}
              placeholder="Loading voices…"
              disabled={!options}
              onChange={(value) => {
                if (value === "local" || value === "live" || value === "narrator" || value === "clone") setVoice(value);
              }}
              hint={voice === "local" ? "Reads unrecorded lines aloud on this computer." : voice === "live" ? "Record your chapters in Studio. Unrecorded lines will be silent." : voice === "narrator" ? "Choose an ElevenLabs voice in Studio before rendering." : undefined}
              options={[
                { value: "local", label: "Local narrator", description: options?.local_narrator ? "Offline speech" : "No speech engine installed", disabled: !options?.local_narrator },
                { value: "live", label: "Your recordings", description: "Use your own chapter takes" },
                { value: "narrator", label: "ElevenLabs", description: options?.narrator.ready ? "Use a library voice" : "Requires an ElevenLabs connection", disabled: !options?.narrator.ready },
                { value: "clone", label: "Cloned voice", description: options?.narrator.ready ? "Choose a channel voice or record a new one" : "Requires an ElevenLabs connection", disabled: !options?.narrator.ready || !channelId },
              ]}
            />
            {voice === "clone" && (clones ? (
              <ChannelVoices voices={clones} selected={selectedClone} busy={busy}
                onSelect={setVoiceId} onAdd={() => setCloneOpen(true)} addLabel="Add voice" />
            ) : voiceProblem ? (
              <div className="ep-new-row">
                <small data-tone="red" role="alert">{voiceProblem}</small>
                <button type="button" className="btn" onClick={() => setVoiceRetry(n => n + 1)}>Retry voice list</button>
              </div>
            ) : <p className="ep-new-from" role="status">Loading channel voices…</p>)}
            <Select
              label="Episode writer"
              value={writer}
              placeholder="Choose a writer"
              onChange={(id) => {
                setWriter(options?.writers.find((w) => w.id === id && w.ready)?.id ?? null);
                setPick({ model: "", effort: "" });
              }}
              options={(options?.writers ?? []).map((w) => ({value: w.id, label: w.title, disabled: !w.ready}))}
              hint={writer === "demo" ? "Uses the fixed HTTP caching example. Your notes are ignored." : writer ? "Uses your notes and the selected writer’s model allowance." : nobody ? "Set up a writer to plan from your notes." : undefined}
            />
            {writer && writer !== "demo" && offersPicks(options?.generation_models[writer]) && (
              <AgentModel models={options?.generation_models[writer] ?? []} pick={pick} onChange={setPick} />
            )}
            {presenter === "on" && (more ? (
              <div className="ep-new-row">
                <span>Look</span>
                <span className="ep-looks">
                  {themes.map((t) => (
                    <button type="button" key={t.id} aria-pressed={theme === t.id} title={t.stage} onClick={() => setTheme(t.id)}>
                      {LOOKS[t.id] ?? t.name}
                    </button>
                  ))}
                </span>
              </div>
            ) : (
              <p className="ep-new-rest">
                <span>{LOOKS[theme] ?? "The usual"} look</span>
                <button type="button" className="linkish" onClick={() => setMore(true)}>Change</button>
              </p>
            ))}
          </section>
        </div>
        <footer className="ep-new-foot">
          <button type="button" className="btn" onClick={close}>
            Cancel
          </button>
          <button type="button" className="btn primary" disabled={busy || !writer || !voice || !hasMaterial || (voice === "clone" && !selectedClone)} onClick={() => void plan()}>
            {writer === "demo" ? "Plan HTTP caching sample" : "Plan the episode"}
          </button>
        </footer>
      </FileDrop>
      {cloneOpen && channelId && <CloneDialog onDone={() => setCloneOpen(false)} onClone={async clone => {
        const saved = await api.cloneChannelVoice(channelId, clone);
        setVoiceLibrary({ channel: channelId, voices: [...(clones ?? []), saved] });
        setVoiceId(saved.id);
        return true;
      }} />}
    </div>
  );
}
