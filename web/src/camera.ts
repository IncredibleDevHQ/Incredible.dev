// A camera's clips and a recording coming in, in words and numbers (CameraFile.tsx draws them).
import type { CameraClip, EpisodeImport, EpisodeTake, EpisodeView } from "./api";

export const gb = (bytes: number) => (bytes >= 1e9 ? `${(bytes / 1e9).toFixed(1)} GB` : `${Math.max(1, Math.round(bytes / 1e6))} MB`);

export function when(seconds: number): string {
  if (!seconds) return "";
  const date = new Date(seconds * 1000);
  const today = new Date().toDateString() === date.toDateString();
  return today
    ? date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
    : date.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

// When a take was recorded: as the studio said, or, for an older one, from when it was saved.
const recordedAt = (take: EpisodeTake) => take.recording.at ?? take.created_at - take.seconds;

// The clip a take was most likely recorded with: the one whose time overlaps the take's most. A
// camera's clock can be off by a few minutes, so a little either side still counts.
export function clipOf(clips: CameraClip[], take?: EpisodeTake): CameraClip | undefined {
  if (!take) return undefined;
  const from = recordedAt(take) - 300;
  const to = recordedAt(take) + take.seconds + 300;
  const overlap = (c: CameraClip) => Math.min(to, c.recorded_at + c.seconds) - Math.max(from, c.recorded_at);
  const best = clips.filter((c) => c.recorded_at && overlap(c) > 0).sort((a, b) => overlap(b) - overlap(a))[0];
  return best;
}

// How far a recording coming in has come, in words.
export function importWords(coming: EpisodeImport, view: EpisodeView): string {
  const guide = view.takes.find((t) => t.id === coming.guide);
  if (coming.state === "copying") {
    return coming.total ? `Copying · ${gb(coming.done ?? 0)} of ${gb(coming.total)}` : "Copying";
  }
  if (coming.state === "matching") return `Matching its sound to ${guide ? guide.label || `Take ${guide.n}` : "the take"}`;
  if (coming.state === "cutting") return `Making its copies · ${Math.round(100 * (coming.fraction ?? 0))}%`;
  if (coming.state === "saving") return "Saving its copies";
  return coming.failure || "It couldn't be brought in.";
}

