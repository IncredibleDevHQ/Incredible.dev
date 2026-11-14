// The sheet an episode starts from: the notes (or a research frame's), how long it runs, whether
// someone is on camera, the look, and who writes it: a coding agent on this computer or the
// built-in one. One button plans it.
import { Paperclip, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, type EpisodeOptions, type FileView, type WriterId } from "../../api";
import { LOOKS, mmss } from "../../episode";
import { useHouse, type EpisodeStart } from "../../store";
import { AgentMark, FileList } from "../../ui";
import { TextArea } from "../TextArea";
import { TextField } from "../TextField";

export function NewEpisode({ start }: { start: EpisodeStart }) {
  const channelId = useHouse((s) => s.channelId);
  const startEpisode = useHouse((s) => s.startEpisode);
  const openEpisode = useHouse((s) => s.openEpisode);
  const [options, setOptions] = useState<EpisodeOptions | null>(null);
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [files, setFiles] = useState<FileView[]>([]);
  const [seconds, setSeconds] = useState(360);
  const [presenter, setPresenter] = useState<"on" | "off">("on");
  const [theme, setTheme] = useState("corner-window");
  const [writer, setWriter] = useState<WriterId | null>(null);
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const close = () => startEpisode(null);

  useEffect(() => {
    void api
      .episodeOptions()
      .then((o) => {
        setOptions(o);
        setSeconds(o.seconds.usual);
        setWriter(o.writers.find((w) => w.ready)?.id ?? null);
      })
      .catch((error: Error) => useHouse.getState().say(error.message));
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && startEpisode(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [startEpisode]);

  const attach = async (picked: FileList | null) => {
    if (!picked?.length) return;
    try {
      const added = await api.upload([...picked]);
      setFiles((f) => [...f, ...added]);
    } catch (error) {
      useHouse.getState().say((error as Error).message);
    }
  };

  const hasMaterial = Boolean(start.frame) || text.trim().length > 0 || files.length > 0;
  const plan = async () => {
    if (!channelId || !writer || !hasMaterial) return;
    setBusy(true);
    try {
      const view = await api.newEpisode(channelId, {
        title: title.trim(),
        text,
        files: files.map((f) => f.id),
        from_frame: start.frame,
        settings: { seconds, presenter, theme: presenter === "off" ? "voice-only" : theme, writer },
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
  return (
    <div className="picker ep-new" role="dialog" aria-modal="true" aria-label="New episode">
      <div className="picker-panel">
        <header className="picker-head">
          <h2>New episode</h2>
          <button type="button" className="icon-btn" aria-label="Close" onClick={close}>
            <X />
          </button>
        </header>
        <p className="picker-lede">A presenter-led explainer of one idea. It is planned from your notes, then you record it chapter by chapter in its studio.</p>
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
                  placeholder="Paste a post, docs or rough notes. Links are read."
                  minRows={8}
                  maxRows={16}
                />
                <div className="ep-new-files">
                  <button type="button" className="btn" onClick={() => input.current?.click()}>
                    <Paperclip />
                    Add text files
                  </button>
                  <input ref={input} type="file" multiple accept=".md,.markdown,.txt,.rst,.json,.csv,.html,text/*" hidden onChange={(e) => void attach(e.target.files)} />
                  {files.length > 0 && <FileList files={files} />}
                </div>
              </>
            )}
          </section>
          <section className="ep-new-facts">
            <label className="ep-new-row">
              <span>
                Length <b>{mmss(seconds)}</b>
              </span>
              <input
                type="range"
                min={options?.seconds.least ?? 240}
                max={options?.seconds.most ?? 600}
                step={30}
                value={seconds}
                onChange={(e) => setSeconds(Number(e.target.value))}
              />
            </label>
            <div className="ep-new-row">
              <span>On camera</span>
              <span className="ep-seg" role="radiogroup" aria-label="On camera">
                <button type="button" role="radio" aria-checked={presenter === "on"} onClick={() => setPresenter("on")}>
                  You present
                </button>
                <button type="button" role="radio" aria-checked={presenter === "off"} onClick={() => setPresenter("off")}>
                  Voice only
                </button>
              </span>
            </div>
            {presenter === "on" && (
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
            )}
            <div className="ep-new-row">
              <span>Written by</span>
              <div className="agents named" role="radiogroup" aria-label="Who writes it">
                {options?.writers.map((w) => (
                  <button
                    type="button"
                    role="radio"
                    key={w.id}
                    aria-checked={writer === w.id}
                    disabled={!w.ready}
                    title={w.ready ? (w.local ? `${w.title}, on this computer, signed in as you are` : "The model this house is set up with") : `${w.title} isn't ready on this computer`}
                    onClick={() => setWriter(w.id)}
                  >
                    <AgentMark mark={w.local ? w.id : undefined} size="sm" />
                    <span>{w.title}</span>
                  </button>
                ))}
              </div>
            </div>
            {options && !options.writers.some((w) => w.ready) && <p className="ep-new-from">No writer is ready: install Claude Code, Codex or Kimi Code, or set a model for the built-in agent.</p>}
          </section>
        </div>
        <footer className="ep-new-foot">
          <button type="button" className="btn" onClick={close}>
            Cancel
          </button>
          <button type="button" className="btn primary" disabled={busy || !writer || !hasMaterial} onClick={() => void plan()}>
            Plan the episode
          </button>
        </footer>
      </div>
    </div>
  );
}
