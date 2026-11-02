// A film's Studio preview over everything: the film plays, and anything in it can be edited right
// here (the engine's own editor, on the thread's computer; edits save to the project). The render
// waits for the team's sign-off, which can be given from here too.
import { Check, ExternalLink, X } from "lucide-react";
import { useEffect, useState } from "react";
import { api, type Asset } from "../api";
import { useHouse } from "../store";

export function PreviewDialog() {
  const preview = useHouse((s) => s.preview);
  const openPreview = useHouse((s) => s.openPreview);
  const film = useHouse((s) => findAsset(s, s.preview?.assetId, s.preview?.threadId));
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!preview) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && openPreview(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [preview, openPreview]);

  if (!preview) return null;
  const render = async () => {
    if (!film) return;
    setBusy(true);
    try {
      await api.renderFilm(film.id);
      openPreview(null);
    } catch (error) {
      useHouse.getState().say((error as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="studio" role="dialog" aria-modal="true" aria-label={`${preview.title}: preview`}>
      <header className="studio-bar">
        <h2>{preview.title}</h2>
        {film?.status === "review" && (
          <button type="button" className="btn primary" disabled={busy} onClick={() => void render()}>
            <Check />
            Render it
          </button>
        )}
        <a className="btn" href={preview.url} target="_blank" rel="noreferrer">
          <ExternalLink />
          New tab
        </a>
        <button type="button" className="icon-btn" aria-label="Close preview" onClick={() => openPreview(null)}>
          <X />
        </button>
      </header>
      <iframe src={preview.url} title={`${preview.title}: preview`} allow="autoplay; fullscreen; clipboard-read; clipboard-write" />
    </div>
  );
}

type Views = Pick<ReturnType<typeof useHouse.getState>, "details" | "canvas">;

// The film a preview belongs to, from whichever view of its task is loaded.
export function findAsset({ details, canvas }: Views, assetId?: string, threadId?: string): Asset | undefined {
  if (!assetId || !threadId) return undefined;
  const fromThread = details[threadId]?.assets?.find((a) => a.id === assetId);
  if (fromThread) return fromThread;
  for (const tasks of Object.values(canvas)) {
    const found = tasks.find((t) => t.thread.id === threadId)?.assets.find((a) => a.id === assetId);
    if (found) return found;
  }
  return undefined;
}
