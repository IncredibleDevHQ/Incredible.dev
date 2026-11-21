// A camera's own recording of a chapter, brought in from its card where it is (no upload, any
// size) or as a file. Matched to the take recorded at the same moment, it is found in that take
// by sound and takes the take's marks: every line starts where it was said. While it comes in,
// the chapter says how far it has come; one that can't be used says why, and the take stays.
import { Camera, RefreshCw, Upload, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, type CameraClip, type EpisodeTake, type EpisodeView } from "../../api";
import { clipOf, gb, importWords, when } from "../../camera";
import { mmss } from "../../episode";
import { Popover } from "../Popover";
import { Tooltip } from "../Tooltip";
import type { Run } from "./Ask";

export function CameraFile({ view, chapter, guide, run, disabled, label, icon }: {
  view: EpisodeView; chapter: string; guide?: EpisodeTake; run: Run; disabled?: boolean; label?: string;
  // drawn as an icon in a toolbar, named by its tooltip
  icon?: boolean;
}) {
  const trigger = useRef<HTMLButtonElement>(null);
  const file = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [clips, setClips] = useState<CameraClip[] | null>(null);
  const [folders, setFolders] = useState<string[]>([]);
  const [problem, setProblem] = useState("");
  const [picked, setPicked] = useState("");
  const [looking, setLooking] = useState(false);
  const best = clipOf(clips ?? [], guide);
  const look = async () => {
    setLooking(true);
    setProblem("");
    try {
      const listed = await api.cameraClips();
      setClips(listed.clips);
      setFolders(listed.folders);
      setPicked((was) => (listed.clips.some((c) => c.path === was) ? was : (clipOf(listed.clips, guide) ?? listed.clips[0])?.path ?? ""));
    } catch (error) {
      setProblem((error as Error).message);
    } finally {
      setLooking(false);
    }
  };
  // the card is read each time the dialog opens: one may have been put in meanwhile
  const opened = useRef(look);
  opened.current = look;
  useEffect(() => {
    if (open) void opened.current();
  }, [open]);
  const chosen = clips?.find((c) => c.path === picked);
  const bring = async (call: () => Promise<EpisodeView>) => {
    if (await run(call)) setOpen(false);
  };
  const title = guide ? "Use the camera's file" : "Bring a recording";
  const description = guide
    ? `It is matched to ${guide.label || `Take ${guide.n}`} by sound, so each line starts where you said it.`
    : "It becomes this chapter's take, its lines spread at the plan's pace.";
  return (
    <>
      {icon ? (
        <Tooltip content="Bring a recording of this chapter: a clip from the camera's card or a file, or drop one on the frame" side="bottom">
          <button ref={trigger} type="button" className="icon-btn" aria-label="Bring a recording of this chapter" aria-haspopup="dialog" aria-expanded={open} disabled={disabled} onClick={() => setOpen(!open)}>
            <Upload />
          </button>
        </Tooltip>
      ) : (
        <Tooltip content={guide ? "Your camera's recording of this take, from its card: matched by sound" : "A clip from the camera's card, or a file"} side="bottom" align="end">
          <button ref={trigger} type="button" className="btn" aria-haspopup="dialog" aria-expanded={open} disabled={disabled} onClick={() => setOpen(!open)}>
            <Camera aria-hidden="true" />
            {label ?? (guide ? "Camera file" : "Bring a recording")}
          </button>
        </Tooltip>
      )}
      <Popover open={open} onClose={() => setOpen(false)} anchor={trigger} align="end" width={440} className="ep-edit-picker ep-camera" title={title} description={description}>
        {problem ? (
          <p className="ep-notice" data-tone="red" role="alert">{problem}</p>
        ) : clips === null ? (
          <p className="ep-notice" role="status"><span className="spin" /> Looking for a camera card…</p>
        ) : clips.length === 0 ? (
          <div className="ep-camera-none">
            <p>No camera card is in this computer.</p>
            <small>Put the card in, then look again. Looked in {folders.join(", ") || "no folders"}.</small>
          </div>
        ) : (
          <ul className="ep-camera-clips" role="radiogroup" aria-label="Clips on the card">
            {clips.map((clip) => (
              <li key={clip.path}>
                <button type="button" role="radio" aria-checked={clip.path === picked}
                  aria-label={[clip.name, when(clip.recorded_at) && `recorded ${when(clip.recorded_at)}`, mmss(clip.seconds), gb(clip.size), clip === best && "recorded with this take"].filter(Boolean).join(", ")}
                  onClick={() => setPicked(clip.path)} onDoubleClick={() => void bring(() => api.cameraTake(view.id, { chapter, path: clip.path, guide: guide?.id }))}>
                  <b>{clip.name}</b>
                  <span>{[when(clip.recorded_at), mmss(clip.seconds), gb(clip.size)].filter(Boolean).join(" · ")}</span>
                  {clip === best && <em>Recorded with this take</em>}
                  <small>{clip.card}</small>
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="ep-provider-footer">
          <button type="button" className="btn" disabled={looking} onClick={() => void look()}>
            <RefreshCw aria-hidden="true" />
            Look again
          </button>
          <button type="button" className="btn" onClick={() => file.current?.click()}>
            <Upload aria-hidden="true" />
            Pick a file
          </button>
          <button type="button" className="btn primary" disabled={!chosen} onClick={() => chosen && void bring(() => api.cameraTake(view.id, { chapter, path: chosen.path, guide: guide?.id }))}>
            {chosen ? `Use ${chosen.name}` : "Use the clip"}
          </button>
        </div>
        <input ref={file} type="file" accept="video/*,audio/*" hidden onChange={(e) => {
          const picked = e.target.files?.[0];
          e.target.value = "";
          if (picked) void bring(() => api.addTake(view.id, { chapter, marks: [], file: picked, name: picked.name, guide: guide?.id }));
        }} />
      </Popover>
    </>
  );
}

// A chapter's recording coming in, or the one that couldn't be, with why and the way to put it away.
export function ImportLine({ view, chapter, run }: { view: EpisodeView; chapter: string; run: Run }) {
  const coming = view.imports.find((i) => i.chapter === chapter);
  if (!coming) return null;
  if (coming.state === "failed") {
    return (
      <p className="ep-notice ep-import" data-tone="red" role="alert">
        <span><b>{coming.name}</b> wasn't brought in: {coming.failure || "it couldn't be read."}</span>
        <button type="button" className="icon-btn" aria-label="Dismiss" onClick={() => void run(() => api.forgetImport(view.id, chapter))}>
          <X />
        </button>
      </p>
    );
  }
  const percent = Math.round(100 * (coming.fraction ?? 0));
  return (
    <div className="ep-notice ep-import" role="status">
      <span><b>{coming.name}</b> · {importWords(coming, view)}</span>
      <progress aria-label={`Bringing ${coming.name} in`} max={100} value={coming.state === "matching" ? undefined : percent} />
    </div>
  );
}

// Where the chapter's take came from, when it is a camera's file: matched to which take, what the
// house noticed of it, and the studio's take one press away.
export function TakeOrigin({ view, take, run, busy }: { view: EpisodeView; take?: EpisodeTake; run: Run; busy: boolean }) {
  const recording = take?.recording;
  if (!take || !recording || recording.kind === "studio" || !recording.kind) return null;
  const guide = recording.matched ? view.takes.find((t) => t.id === recording.matched!.take) : undefined;
  return (
    <>
      <p className="ep-notice ep-take-origin">
        <span>
          {recording.name ?? "A file"}
          {take.uhd ? " · 4K" : ""}
          {recording.matched ? ` · matched to ${guide ? guide.label || `Take ${guide.n}` : "a take"} by sound` : " · lines at the plan's pace"}
        </span>
        {guide && !guide.kept && (
          <button type="button" className="linkish" disabled={busy} onClick={() => void run(() => api.keepTake(view.id, guide.id))}>
            Undo
          </button>
        )}
      </p>
      {recording.note && <p className="ep-notice" data-tone="amber">{recording.note}</p>}
    </>
  );
}
