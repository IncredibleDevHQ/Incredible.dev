// The line's words over the frame, as the film says them. While the line plays, the words said so
// far are lit, the one being said is marked and the rest are still to come; paused, the whole
// line stands. The moment each word falls is shared out by its length and by the pause a comma
// or a full stop makes, so the marks keep pace with a take, a picture's draft or the plan's own
// reading of the line.
import { useMemo } from "react";

// How long a word takes, in letters: its own, plus the pause after it.
const weight = (word: string) => word.length + 1 + (/[.!?]$/.test(word) ? 4 : /[,;:—–-]$/.test(word) ? 2 : 0);

export function Captions({ words, progress }: { words: string; progress: number | null }) {
  const parts = useMemo(() => {
    const list = words.split(/\s+/).filter(Boolean);
    let run = 0;
    const ends = list.map((w) => (run += weight(w)));
    return { list, ends, total: run || 1 };
  }, [words]);
  // the word being said: the first whose share of the line reaches this far in
  const at =
    progress === null
      ? -1
      : Math.min(
          parts.list.length - 1,
          parts.ends.findIndex((end) => end / parts.total >= progress),
        );
  return (
    <p className="ep-captions" aria-hidden="true" data-playing={progress !== null || undefined}>
      {parts.list.map((w, i) => (
        <span key={i} data-at={at < 0 ? undefined : i < at ? "said" : i === at ? "now" : "ahead"}>
          {w}{" "}
        </span>
      ))}
    </p>
  );
}
