// What changed in a line, word by word: the words that went are struck, the new ones are marked,
// and the rest reads as it does now. The studio's own comparison. Words are compared whole and
// by what is said, so a capital or a comma is not a change; when little of the old line is left
// the two are shown one after the other, because a line with a mark on every other word cannot
// be read.
import { Fragment, useMemo } from "react";

export type Piece = { kind: "same" | "cut" | "new"; text: string };

const words = (text: string) => text.trim().split(/\s+/).filter(Boolean);
// A word as it is said: no capitals, and none of the punctuation at its ends.
const said = (word: string) => word.toLowerCase().replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu, "") || word;

export function wordDiff(was: string, now: string): Piece[] {
  const a = words(was);
  const b = words(now);
  const ka = a.map(said);
  const kb = b.map(said);
  // shared[i][j]: how many words, in order, a from i and b from j have in common
  const shared = Array.from({ length: a.length + 1 }, () => new Uint16Array(b.length + 1));
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      shared[i][j] = ka[i] === kb[j] ? shared[i + 1][j + 1] + 1 : Math.max(shared[i + 1][j], shared[i][j + 1]);
    }
  }
  if (shared[0][0] * 3 < Math.max(a.length, b.length)) {
    // said another way altogether
    return [
      { kind: "cut" as const, text: a.join(" ") },
      { kind: "new" as const, text: b.join(" ") },
    ].filter((p) => p.text);
  }
  // Walk both: a word they share stays (as it is written now); between two shared words, what
  // went comes first and what came in follows it.
  const pieces: Piece[] = [];
  let cut: string[] = [];
  let fresh: string[] = [];
  const settle = () => {
    if (cut.length) pieces.push({ kind: "cut", text: cut.join(" ") });
    if (fresh.length) pieces.push({ kind: "new", text: fresh.join(" ") });
    cut = [];
    fresh = [];
  };
  let i = 0;
  let j = 0;
  while (i < a.length || j < b.length) {
    const both = i < a.length && j < b.length && ka[i] === kb[j];
    // Inside a change, a shared word that could as well be matched later is left to it, so the
    // change reads as one stretch and not as scraps around a stray "the".
    if (both && cut.length && shared[i + 1][j] === shared[i][j]) {
      cut.push(a[i++]);
    } else if (both && fresh.length && shared[i][j + 1] === shared[i][j]) {
      fresh.push(b[j++]);
    } else if (both) {
      settle();
      const last = pieces[pieces.length - 1];
      if (last?.kind === "same") last.text += ` ${b[j]}`;
      else pieces.push({ kind: "same", text: b[j] });
      i++;
      j++;
    } else if (j >= b.length || (i < a.length && shared[i + 1][j] >= shared[i][j + 1])) {
      cut.push(a[i++]);
    } else {
      fresh.push(b[j++]);
    }
  }
  settle();
  return pieces;
}

// A line as it reads now, with what it said before laid into it.
export function Changed({ was, now }: { was: string; now: string }) {
  const pieces = useMemo(() => wordDiff(was, now), [was, now]);
  return (
    <span className="ep-diff">
      {pieces.map((p, i) =>
        p.kind === "cut" ? (
          // what went is for the eye; read aloud, the line is the line as it stands
          <del key={i} aria-hidden="true">
            {p.text}{" "}
          </del>
        ) : p.kind === "new" ? (
          <ins key={i}>{p.text} </ins>
        ) : (
          <Fragment key={i}>{p.text} </Fragment>
        ),
      )}
    </span>
  );
}
