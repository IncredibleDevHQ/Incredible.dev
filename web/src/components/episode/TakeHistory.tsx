import { useState } from "react";
import { api, type EpisodeChapter, type EpisodeView } from "../../api";
import { linesOf, mmss } from "../../episode";
import type { Run } from "./Ask";

export function TakeHistory({ view, chapter, run, busy }: {
  view: EpisodeView; chapter: EpisodeChapter; run: Run; busy: boolean;
}) {
  const [preview, setPreview] = useState<string | null>(null);
  const takes = view.takes.filter(take => take.chapter === chapter.id).slice().reverse();
  const lines = linesOf(chapter);
  if (!takes.length) return <p className="faint">No recordings yet. Record this chapter to keep and compare takes here.</p>;
  return <ol className="ep-take-history" aria-label="Recording versions">
    {takes.map(take => {
      const name = take.label || `Take ${take.n}`;
      const shown = preview === take.id;
      const index = lines.findIndex(line => line.id === take.frame);
      const scope = take.frame ? index < 0 ? "Earlier line" : `Line ${index + 1}` : "Chapter";
      return <li key={take.id} data-kept={take.kept || undefined}>
        <div className="ep-version-top"><b>{name}</b>{take.kept && <em data-now>In use</em>}</div>
        <small>{scope} · {mmss(take.seconds)} · Take {take.n}</small>
        <time dateTime={new Date(take.created_at * 1000).toISOString()}>{new Date(take.created_at * 1000).toLocaleString([], {month:"short",day:"numeric",hour:"numeric",minute:"2-digit"})}</time>
        {(take.video || take.audio) && <button type="button" className="btn" aria-pressed={shown} onClick={() => setPreview(shown ? null : take.id)}>{shown ? "Close preview" : `Preview ${name}`}</button>}
        {shown && (take.video
          ? <video controls playsInline preload="metadata" src={take.video.url} aria-label={`Recording preview: ${name}`} />
          : <audio controls preload="metadata" src={take.audio!.url} aria-label={`Recording preview: ${name}`} />)}
        {shown && !take.kept && <button type="button" className="btn primary" disabled={busy} onClick={() => void run(() => api.keepTake(view.id, take.id))}>Use this take</button>}
      </li>;
    })}
  </ol>;
}
