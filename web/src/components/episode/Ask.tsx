// The change bar: the one place to say, in words, what should change. It starts on what is
// picked (this line) and widens with a click to the line's picture, the chapter or the film.
// The writer makes the change. While it does, the bar says what was asked and for how long,
// can stop it, and still takes the next change, which waits its turn. When a change has landed
// the bar says what it did and takes it back; one that was taken back can be put back; one that
// stopped can be asked again in the same words.
import { ArrowUp, ChevronDown, CornerDownLeft, Redo2, RotateCcw, Square, Undo2, X } from "lucide-react";
import { useCallback, useEffect, useImperativeHandle, useLayoutEffect, useRef, useState, type Ref } from "react";
import { api, type AskScope, type EpisodeAsk, type EpisodeChange, type EpisodeView } from "../../api";
import { mmss } from "../../episode";
import { useHouse } from "../../store";
import { Kbd } from "../Kbd";
import { Popover } from "../Popover";
import { ShimmerText } from "../Shimmer";
import { Tooltip } from "../Tooltip";

// `label` is what the bar calls it while it is picked ("This line"); `name` says which one it
// is once that is no longer plain to see, as when it waits its turn ("Ch 3 · line 2").
export type AskTarget = { scope: AskScope; target?: string; label: string; name: string; hint: string; presets: string[] };
export type AskHandle = { open: (scope?: AskScope) => void };
// Every change goes to the server and comes back as the whole episode; true when it did.
export type Run = (call: () => Promise<EpisodeView>) => Promise<boolean>;
// Whether what the last change did is marked in the script, and the switch for it.
export type Marks = { on: boolean; set: (on: boolean) => void };

// The keys for taking a change back and putting it back, as this computer writes them.
const MAC = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);
const UNDO_KEYS = MAC ? "⌘Z" : "Ctrl+Z";
const REDO_KEYS = MAC ? "⇧⌘Z" : "Ctrl+Shift+Z";

const WORKING: Record<string, string> = {
  change: "Making your change",
  redo: "Planning a picture for this line",
  edit: "Fitting the picture to your words",
};

// Whether a turn of the writer's is under way on a plan that already stands.
export const turning = (view: EpisodeView) => view.status !== "planning" && (view.stage.state === "working" || view.stage.state === "reading");

function plural(n: number, one: string, many: string) {
  return `${n} ${n === 1 ? one : many}`;
}
const short = (text: string, most = 64) => (text.length > most ? `${text.slice(0, most - 1).trimEnd()}…` : text);

// What a change did, in a few words.
function did(change: EpisodeChange): string {
  const parts: string[] = [];
  if (change.lines.length) parts.push(`${plural(change.lines.length, "line", "lines")} changed`);
  if (change.added.length) parts.push(`${plural(change.added.length, "line", "lines")} added`);
  if (change.removed) parts.push(`${plural(change.removed, "line", "lines")} cut`);
  if (change.pictures?.length) parts.push(`${plural(change.pictures.length, "picture", "pictures")} planned again`);
  return parts.length ? parts.join(", ") : "Nothing in the plan changed";
}

// A change typed while the writer was busy with another: it waits, and is asked when that one lands.
export type Queued = EpisodeAsk & { id: number; label: string };
export type Waiting = {
  notes: Queued[];
  // The turn they waited behind stopped: they stay until the person sends them or lets them go.
  held: boolean;
  add: (note: Omit<Queued, "id">) => void;
  remove: (id: number) => void;
  send: () => void;
};

// The notes that wait belong to the studio, not to one bar: the bar changes with the line and
// the chapter that are open, and what was typed ahead must outlive that.
export function useWaiting(view: EpisodeView | null): Waiting {
  const [notes, setNotes] = useState<Queued[]>([]);
  // The stopped turn the person has sent the waiting notes past, and whether one was refused.
  const [past, setPast] = useState<number | null>(null);
  const [refused, setRefused] = useState(false);
  const next = useRef(1);
  const sending = useRef(false);
  const id = view?.id;
  const working = view ? turning(view) : false;
  const open = Boolean(view?.plan) && view?.status !== "planning" && view?.status !== "failed";
  // A turn that stopped holds what was typed behind it: it was written for a change that is
  // not there. Read from the episode as it stands, so nothing is sent in the moment between
  // the stop and the hold.
  const stoppedAt = view?.stage.state === "stopped" ? (view.stage.at ?? 0) : null;
  const held = notes.length > 0 && !working && (refused || (stoppedAt !== null && stoppedAt !== past));

  useEffect(() => {
    if (!id || !open || working || held || sending.current || notes.length === 0) return;
    const [first] = notes;
    sending.current = true;
    setNotes((all) => all.filter((n) => n.id !== first.id));
    api
      .askEpisode(id, { scope: first.scope, target: first.target, text: first.text })
      .then((landed) => useHouse.getState().setEpisode(landed))
      .catch((error: Error) => {
        // it could not be asked (its line is gone, say): the rest wait for the person
        useHouse.getState().say(error.message);
        setRefused(true);
      })
      .finally(() => {
        sending.current = false;
      });
  }, [id, open, working, held, notes]);

  const add = useCallback((note: Omit<Queued, "id">) => setNotes((all) => [...all, { ...note, id: next.current++ }]), []);
  const remove = useCallback((gone: number) => setNotes((all) => all.filter((n) => n.id !== gone)), []);
  const send = useCallback(() => {
    setRefused(false);
    setPast(stoppedAt);
  }, [stoppedAt]);
  return { notes, held, add, remove, send };
}

// How long the turn has run, counted from when the house began it. It ticks on its own, so
// nothing around it is drawn again, and it is never read aloud.
export function Elapsed({ since }: { since: number }) {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    const tick = window.setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => window.clearInterval(tick);
  }, []);
  return (
    <time className="ep-elapsed" aria-hidden="true">
      {mmss(Math.max(0, now - since))}
    </time>
  );
}

export function Ask({
  view,
  targets,
  run,
  busy,
  ref,
  slash,
  waiting,
  marks,
}: {
  view: EpisodeView;
  targets: AskTarget[];
  run: Run;
  busy: boolean;
  ref?: Ref<AskHandle>;
  slash?: boolean;
  waiting: Waiting;
  marks?: Marks;
}) {
  const [scope, setScope] = useState<AskScope>(targets[0].scope);
  const [text, setText] = useState("");
  const [focused, setFocused] = useState(false);
  const [menu, setMenu] = useState(false);
  // What the bar last did, for a screen reader: said once, when it happens.
  const [told, setTold] = useState("");
  // The turn whose stop the person has read and closed.
  const [closed, setClosed] = useState<number | null>(null);
  const field = useRef<HTMLTextAreaElement>(null);
  const chip = useRef<HTMLButtonElement>(null);
  const at = targets.find((t) => t.scope === scope) ?? targets[0];
  const working = turning(view);
  const stage = view.stage;
  // A turn that ended without a change says why: it stopped (in red), or the writer changed nothing.
  const stopped = stage.state === "stopped" && Boolean(WORKING[stage.name ?? ""]);
  const ended = (stopped || (stage.state === "done" && Boolean(stage.said))) && closed !== (stage.at ?? 0);
  const asked = stage.asked ?? null;
  const change = view.last_change;
  const undone = view.undone;

  // What is picked changed (another line, another chapter): the bar goes back to its first scope
  // unless the one it had still exists there.
  const first = targets[0].scope;
  const has = targets.some((t) => t.scope === scope);
  useEffect(() => {
    if (!has) setScope(first);
  }, [has, first]);

  useImperativeHandle(ref, () => ({
    open: (to) => {
      if (to && targets.some((t) => t.scope === to)) setScope(to);
      requestAnimationFrame(() => field.current?.focus());
    },
  }));

  // The field is as tall as its words, up to five lines.
  useLayoutEffect(() => {
    const el = field.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 118)}px`;
  }, [text]);

  const send = (words: string) => {
    const said = words.trim();
    if (!said) return;
    if (working) {
      // the writer is on another change: this one waits behind it
      waiting.add({ scope: at.scope, target: at.target, text: said, label: at.name });
      setText("");
      setTold(`Asked next: ${said}`);
      return;
    }
    if (busy) return;
    // the words stay in the field until the change is taken, so one that is refused is not lost
    void run(() => api.askEpisode(view.id, { scope: at.scope, target: at.target, text: said })).then((taken) => taken && setText(""));
  };
  const act = (call: () => Promise<EpisodeView>, say: string) => void run(call).then((done) => done && setTold(say));

  return (
    <form
      className="ep-ask"
      onSubmit={(e) => {
        e.preventDefault();
        send(text);
      }}
    >
      {working ? (
        <div className="ep-ask-working">
          <p aria-live="polite">
            <span className="spin" />
            {asked ? (
              // a person's own words say what is being made better than a label does
              <>
                <span className="sr-only">{WORKING.change}:</span>
                <q title={asked.text}>{asked.text}</q>
              </>
            ) : (
              <>
                <ShimmerText>{WORKING[stage.name ?? ""] ?? "Working"}</ShimmerText>
                {stage.said && stage.said !== "Getting ready" && <span className="faint">{stage.said}</span>}
              </>
            )}
          </p>
          {stage.at && <Elapsed since={stage.at} />}
          <button type="button" className="btn" onClick={() => void api.stopEpisode(view.id).catch((e: Error) => useHouse.getState().say(e.message))}>
            <Square />
            Stop
          </button>
        </div>
      ) : ended ? (
        <p className="ep-ask-note" data-tone={stopped ? "red" : undefined} role="status">
          <span>{stage.said}</span>
          {asked && (
            <Tooltip content={`Asks again: “${short(asked.text)}”`} side="top" align="end">
              <button type="button" className="linkish" disabled={busy} onClick={() => void run(() => api.askEpisode(view.id, asked))}>
                <RotateCcw />
                Try again
              </button>
            </Tooltip>
          )}
          <button type="button" className="icon-btn" aria-label="Close this note" onClick={() => setClosed(stage.at ?? 0)}>
            <X />
          </button>
        </p>
      ) : undone ? (
        <p className="ep-ask-note" role="status">
          <span>Taken back</span>
          {change && (
            <Tooltip content={`Takes back “${short(change.why)}” too`} shortcut={UNDO_KEYS} side="top" align="end">
              <button type="button" className="linkish" disabled={busy} onClick={() => act(() => api.undoEpisode(view.id), "Taken back.")}>
                <Undo2 />
                Undo more
              </button>
            </Tooltip>
          )}
          <Tooltip content={`Puts back “${short(undone.why)}”`} shortcut={REDO_KEYS} side="top" align="end">
            <button type="button" className="linkish" disabled={busy} onClick={() => act(() => api.redoEpisode(view.id), "Put back.")}>
              <Redo2 />
              Put it back
            </button>
          </Tooltip>
        </p>
      ) : (
        change && (
          <p className="ep-ask-note" role="status">
            <span>{did(change)}</span>
            {marks && (Object.keys(change.was ?? {}).length > 0 || (change.cut?.length ?? 0) > 0) && (
              <button type="button" className="linkish" aria-pressed={marks.on} onClick={() => marks.set(!marks.on)}>
                {marks.on ? "Hide" : "Show"}
              </button>
            )}
            <Tooltip content={`Takes back “${short(change.why)}”${change.earlier ? `. ${plural(change.earlier, "change", "changes")} before it can go too.` : ""}`} shortcut={UNDO_KEYS} side="top" align="end">
              <button type="button" className="linkish" disabled={busy} onClick={() => act(() => api.undoEpisode(view.id), "Taken back.")}>
                <Undo2 />
                Undo
              </button>
            </Tooltip>
          </p>
        )
      )}
      {waiting.notes.length > 0 && (
        <ol className="ep-ask-next" aria-label="Asked next">
          {waiting.notes.map((note, i) => (
            <li key={note.id}>
              <small>{i === 0 ? (waiting.held ? "Waiting" : "Next") : "Then"}</small>
              <span title={note.text}>
                <b>{note.label}</b> {note.text}
              </span>
              {i === 0 && waiting.held && !working && (
                <button type="button" className="linkish" onClick={waiting.send}>
                  Send
                </button>
              )}
              <button type="button" className="icon-btn" aria-label={`Don't ask: ${note.text}`} onClick={() => waiting.remove(note.id)}>
                <X />
              </button>
            </li>
          ))}
        </ol>
      )}
      <div className="ep-ask-box" data-focus={focused || undefined}>
        {targets.length > 1 && (
          <span className="ep-ask-scope">
            <button ref={chip} type="button" aria-haspopup="menu" aria-expanded={menu} onClick={() => setMenu((m) => !m)}>
              {at.label}
              <ChevronDown />
            </button>
            <Popover open={menu} onClose={() => setMenu(false)} anchor={chip} side="top" align="start" offset={6} width={200} className="ep-ask-menu">
              <div role="menu" aria-label="What the change is about">
                {targets.map((t) => (
                  <button
                    type="button"
                    role="menuitemradio"
                    aria-checked={t.scope === at.scope}
                    key={t.scope}
                    onClick={() => {
                      setScope(t.scope);
                      setMenu(false);
                      field.current?.focus();
                    }}
                  >
                    {t.label}
                  </button>
                ))}
              </div>
            </Popover>
          </span>
        )}
        <textarea
          ref={field}
          rows={1}
          value={text}
          placeholder={working ? "Next change. It waits its turn." : at.hint}
          aria-label={working ? "Ask for the next change" : at.hint}
          onChange={(e) => setText(e.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              send(text);
            } else if (e.key === "Escape") {
              // the first Escape lets the words go, the next one leaves the field
              e.stopPropagation();
              if (text) setText("");
              else e.currentTarget.blur();
            }
          }}
        />
        {slash && !focused && !text ? (
          // the key that brings the caret here, shown until it is used
          <Kbd keys="/" size="sm" className="ep-ask-key" />
        ) : (
          <button type="submit" className="ep-ask-send" data-next={working || undefined} aria-label={working ? "Ask for it next" : "Ask for it"} disabled={(busy && !working) || !text.trim()}>
            {working ? <CornerDownLeft /> : <ArrowUp />}
          </button>
        )}
      </div>
      {focused && !text && !working && (
        <div className="ep-ask-presets">
          {at.presets.map((p) => (
            // mouse down, so the field's blur does not take the chips away before the click lands
            <button type="button" key={p} onMouseDown={(e) => e.preventDefault()} onClick={() => send(p)}>
              {p}
            </button>
          ))}
        </div>
      )}
      <span className="sr-only" role="status">
        {told}
      </span>
    </form>
  );
}
