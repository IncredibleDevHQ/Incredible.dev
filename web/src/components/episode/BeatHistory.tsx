import { History } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../../api";
import { Popover } from "../Popover";
import { Changed } from "./Diff";

type Entries = Awaited<ReturnType<typeof api.lineHistory>>["entries"];

export function BeatHistory({ episode, frame, beat }: { episode: string; frame: string; beat: number }) {
  const anchor = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [entries, setEntries] = useState<Entries | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!open) return;
    let active = true;
    api.lineHistory(episode, frame).then(
      result => { if (active) setEntries(result.entries); },
      () => { if (active) setFailed(true); },
    );
    return () => { active = false; };
  }, [open, episode, frame]);
  return <div contentEditable={false}>
    <button className="btn ep-history-trigger" type="button" ref={anchor} aria-expanded={open} aria-haspopup="dialog"
      aria-label={`History for beat ${beat}`} onClick={() => { setEntries(null); setFailed(false); setOpen(!open); }}>
      <History aria-hidden="true" />History
    </button>
    <Popover open={open} onClose={() => setOpen(false)} anchor={anchor} title={`Beat ${beat} history`} width={450}>
      <div className="ep-history-list">
        {failed ? <p role="alert">Couldn’t load this beat’s history. Close and reopen to retry.</p> :
          !entries ? <p role="status">Loading changes…</p> :
          !entries.length ? <p>No changes to this beat in the retained episode history.</p> :
          entries.map((entry, index) => <details key={entry.id} open={index === 0}>
            <summary><strong>{entry.reason}</strong><time dateTime={new Date(entry.at * 1000).toISOString()}>{new Date(entry.at * 1000).toLocaleString()}</time></summary>
            {entry.changes.map(change => <section key={change.label}><strong>{change.label}</strong>
              <p><span className="sr-only">Before: {change.before || "Empty"}. After: {change.after || "Empty"}.</span>
                <span aria-hidden="true"><Changed was={change.before} now={change.after} /></span></p>
            </section>)}
          </details>)}
      </div>
    </Popover>
  </div>;
}
