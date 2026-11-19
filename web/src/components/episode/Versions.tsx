// A beat's versions, and its chapter's, as the editor's History tab lists them: the one being
// made, the one that stands now and the ones made before. The open beat's are cards, each a still
// over who made it on what, how, how long its build took and when; the chapter's are every beat's
// as small tiles, to find a version by eye. A press shows that version in the frame, where it
// plays as it was made; the frame says in its corner which version it shows while that is not
// the one that stands. A version made before, on show, can be put back: it stands again as it
// was made, and the one it replaces is kept. Nothing here draws a picture. Written for this house
// from notes on how lists of an agent's saved points behave; no other component's source is in it.
import { ArchiveRestore, History } from "lucide-react";
import { useState } from "react";
import { api, type EpisodeChapter, type EpisodeUnit, type EpisodeView, type FileView, type Level } from "../../api";
import { doingNow, LEVEL_NAMES, linesOf, pictureState } from "../../episode";
import { AgentMark } from "../../ui";
import { Clock } from "../agent/Clock";
import { took } from "../agent/format";
import { SegmentedControl } from "../SegmentedControl";
import type { Run } from "./Ask";
import { blockName, blocksOf, KindIcon, type Block } from "./Blocks";
import { writerTitle } from "./Film";
import { builtOn, madeOn } from "./models";
import { KindArt } from "./PictureArt";

// A version of a beat picked to look back at, shown in the frame in place of the one that
// stands: the beat, and the version's number.
export type Seen = { unit: string; n: number } | null;
// Shows a version of a beat in the frame (none: the one that stands), opening the beat at that
// line.
export type ShowVersion = (unit: string, n: number | null, frame: string) => void;

type Row = {
  n: number;
  state: "making" | "now" | "before";
  still?: FileView;
  builder: string;
  on: string;
  level: Level | "";
  seconds: number | null;
  at: number | null;
  // what a press shows: a kept version by its number, or the one that stands
  shows: number | null;
};

// A version as its row pictures it: the picture as it ends, on its last line's still.
const lastStill = (unit: EpisodeUnit, stills: Record<string, FileView>) => stills[unit.frames[unit.frames.length - 1]] ?? Object.values(stills).pop();

// A beat's versions, newest first: the one being made, the one that stands and the ones kept.
function rowsOf(view: EpisodeView, unit: EpisodeUnit): Row[] {
  const p = unit.picture;
  const making = pictureState(unit, view) === "making";
  const rows: Row[] = [];
  if (making) {
    // a build waiting its turn is still the last build's on record: what it will be is the beat's
    const waiting = p.status === "queued";
    const builder = waiting ? unit.builder : p.builder || unit.builder;
    rows.push({
      n: p.version,
      state: "making",
      builder,
      on: builtOn(view, unit, builder),
      level: p.level || unit.level,
      seconds: null,
      at: waiting ? null : (p.timing?.started_at ?? null),
      shows: null,
    });
  } else if (p.status === "made" || p.status === "go") {
    rows.push({
      n: p.version,
      state: "now",
      still: lastStill(unit, p.stills),
      builder: p.builder,
      on: madeOn(p.generation),
      level: p.level,
      seconds: p.timing?.seconds ?? null,
      at: p.timing?.ended_at ?? null,
      shows: null,
    });
  }
  p.versions.forEach((v, i) =>
    rows.push({
      n: v.n,
      // while the beat is made again, the version before it is the one that stands
      state: making && i === 0 ? "now" : "before",
      still: lastStill(unit, v.stills),
      builder: v.builder,
      on: madeOn(v.generation),
      level: v.level,
      seconds: v.seconds,
      at: v.made_at,
      shows: making && i === 0 ? null : v.n,
    }),
  );
  return rows;
}

// When a version was made: the time for one made today, else the day.
function when(at: number): string {
  const date = new Date(at * 1000);
  return date.toDateString() === new Date().toDateString()
    ? date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
    : date.toLocaleDateString([], { month: "short", day: "numeric" });
}

export function HistoryPanel({
  view,
  chapter,
  unit,
  shownVersion,
  onShow,
  run,
  busy,
}: {
  view: EpisodeView;
  chapter: EpisodeChapter;
  // the open line's picture, if it has one
  unit?: EpisodeUnit;
  // the kept version of that picture picked to be shown, by its number; none while the frame
  // shows the one that stands
  shownVersion: number | null;
  onShow: ShowVersion;
  run: Run;
  busy: boolean;
}) {
  const [scope, setScope] = useState<"beat" | "chapter">("beat");
  const lines = linesOf(chapter);
  const beats = blocksOf(view, lines).filter((b): b is Block & { unit: EpisodeUnit } => b.unit?.kind === "picture");
  const listed = scope === "beat" ? beats.filter((b) => b.unit.id === unit?.id) : beats;
  const said = (b: Block) => {
    const from = lines.indexOf(b.lines[0]) + 1;
    return b.lines.length === 1 ? `line ${from}` : `lines ${from} to ${from + b.lines.length - 1}`;
  };
  // a version made before stands again, and the frame shows it as the one that stands
  const putBack = (of: EpisodeUnit, n: number) =>
    run(() => api.putVersionBack(view.id, of.id, n)).then((ok) => ok && onShow(of.id, null, of.frames[0]));
  return (
    <>
      <h3>History</h3>
      <SegmentedControl<"beat" | "chapter">
        size="sm"
        fullWidth
        aria-label="Whose versions are listed"
        value={scope}
        onChange={setScope}
        options={[
          { value: "beat", label: "Beat" },
          { value: "chapter", label: "Chapter" },
        ]}
      />
      {listed.length === 0 && <small>{scope === "beat" ? "This line has no picture, so it has no versions." : "This chapter has no pictures."}</small>}
      {listed.map((b) => {
        const rows = rowsOf(view, b.unit);
        const open = b.unit.id === unit?.id;
        return (
          <div key={b.unit.id} className="ep-version-beat" role="group" aria-label={`${blockName(b)}, ${said(b)}`}>
            {scope === "chapter" && (
              <h4 data-open={open || undefined}>
                <KindIcon block={b} />
                <b>{blockName(b)}</b>
                <span>{said(b)}</span>
              </h4>
            )}
            {rows.length === 0 ? (
              <small>Not made yet.</small>
            ) : (
              <ol className="ep-version-list" data-compact={scope === "chapter" || undefined}>
                {rows.map((row) => {
                  // the row on show: in the open beat, the kept version picked or the one that stands
                  const shown = open && row.state !== "making" && row.shows === shownVersion;
                  return (
                    <li key={`${row.state}-${row.n}`}>
                      <VersionRow view={view} unit={b.unit} row={row} compact={scope === "chapter"} shown={shown} onShow={() => onShow(b.unit.id, row.shows, b.unit.frames[0])} />
                      {shown && row.state === "before" && scope === "beat" && (
                        <button type="button" className="btn ep-version-use" disabled={busy} onClick={() => void putBack(b.unit, row.n)}>
                          <ArchiveRestore aria-hidden="true" />
                          {/* the beat being made again is stopped for it, so the press says so */}
                          {pictureState(b.unit, view) === "making" ? "Stop and use this" : "Use this version"}
                        </button>
                      )}
                    </li>
                  );
                })}
              </ol>
            )}
            {rows.length === 1 && rows[0].state !== "making" && scope === "beat" && <small>Made once. When it is made again, the version before is kept here.</small>}
          </div>
        );
      })}
    </>
  );
}

// One version: a card with its facts under its still, or (`compact`) a tile that keeps them for
// whoever points at it.
function VersionRow({ view, unit, row, compact, shown, onShow }: { view: EpisodeView; unit: EpisodeUnit; row: Row; compact: boolean; shown: boolean; onShow: () => void }) {
  const who = [writerTitle(row.builder), row.on].filter(Boolean).join(" · ");
  const how = [row.level && LEVEL_NAMES[row.level], took(row.seconds)].filter(Boolean).join(" · ");
  const doing = row.state === "making" ? doingNow(unit, view) : "";
  const made = row.state !== "making" && row.at ? when(row.at) : "";
  const body = (
    <>
      <span className="ep-version-pic" aria-hidden="true">
        {row.still ? <img src={row.still.url} alt="" loading="lazy" /> : <KindArt kind={unit.kind_of_picture} />}
      </span>
      <span className="ep-version-words">
        <span className="ep-version-top">
          <b>Version {row.n}</b>
          {row.state === "now" && <em data-now>Now</em>}
          {row.state === "making" ? (
            <em data-making>
              <i className="ep-working" aria-hidden="true" />
              {!compact && doing}
              {!compact && row.at && <Clock since={row.at} />}
            </em>
          ) : (
            !compact && made && <time dateTime={new Date((row.at ?? 0) * 1000).toISOString()}>{made}</time>
          )}
        </span>
        {!compact && (
          // the agent by its mark, then what it ran on (its name where the record names no model)
          <span className="ep-version-who" title={who}>
            <AgentMark mark={row.builder} size="sm" />
            <span>{row.on || writerTitle(row.builder)}</span>
          </span>
        )}
        {!compact && how && <small>{how}</small>}
      </span>
    </>
  );
  const facts = [who, how, made].filter(Boolean).join(", ");
  if (row.state === "making")
    return (
      <div className="ep-version" data-making role="status" title={compact ? `${doing} · ${who}` : undefined} aria-label={`Version ${row.n} is being made: ${doing}. ${facts}`}>
        {body}
      </div>
    );
  return (
    <button
      type="button"
      className="ep-version"
      aria-pressed={shown}
      title={compact ? facts : undefined}
      aria-label={`Version ${row.n}${row.state === "now" ? ", the one now" : ""}: ${facts}. Show it in the frame`}
      onClick={() => !shown && onShow()}
    >
      {body}
    </button>
  );
}

// Over the frame's corner while it shows a version kept from before: which one, and the way back
// to the one that stands.
export function VersionChip({ n, standing, onBack }: { n: number; standing: number; onBack: () => void }) {
  return (
    <div className="ep-versions" role="group" aria-label={`The frame shows version ${n}`}>
      <span>
        <History aria-hidden="true" />
        Version {n}
      </span>
      <button type="button" onClick={onBack}>
        Back to version {standing}
      </button>
    </div>
  );
}
