// How an agent's run went, once it is over: how long it took and a bar of its stages, each as
// wide as its time; opened, each stage with its time, what the agent said when it looked its work
// over, and the notes the person left it. Pointing at a stage, in the bar or the list, lights it
// in both and dims the rest. Written for this house from notes on how run summaries behave; no
// other component's source is in it.
import { ChevronRight } from "lucide-react";
import { useId, useState } from "react";
import { took } from "./format";
import "./agent.css";

export type SummaryStage = { id: string; label: string; seconds: number };

export function RunSummary({
  stages,
  reviewed = "",
  notes = [],
  title = "How it was made",
  seconds = null,
}: {
  stages: SummaryStage[];
  // what the agent said when it looked its work over
  reviewed?: string;
  notes?: { id: string; text: string }[];
  title?: string;
  // how long the whole run took, where it was kept (the stages' times summed when it was not)
  seconds?: number | null;
}) {
  const [open, setOpen] = useState(false);
  const [lit, setLit] = useState<string | null>(null);
  const body = useId();
  const summed = stages.reduce((sum, s) => sum + s.seconds, 0);
  const total = seconds ?? summed;
  if (!stages.length || summed < 1) return null;
  const dim = (id: string) => (lit !== null && lit !== id) || undefined;
  return (
    <div className="ag-summary" data-open={open || undefined} onPointerLeave={() => setLit(null)}>
      <button type="button" className="ag-summary-head" aria-expanded={open} aria-controls={body} onClick={() => setOpen((o) => !o)}>
        <ChevronRight className="ag-chevron" aria-hidden="true" />
        <span>{title}</span>
        <span className="ag-summary-total">{took(total)}</span>
      </button>
      <div className="ag-bar" role="img" aria-label={stages.map((s) => `${s.label}, ${took(s.seconds)}`).join("; ")}>
        {stages.map((s) => (
          <span
            key={s.id}
            data-stage={s.id}
            data-dim={dim(s.id)}
            style={{ flexGrow: s.seconds }}
            title={`${s.label} · ${took(s.seconds)}`}
            onPointerEnter={() => setLit(s.id)}
          />
        ))}
      </div>
      <div id={body} className="ag-summary-body" hidden={!open}>
        <ol>
          {stages.map((s) => (
            <li key={s.id} data-dim={dim(s.id)} onPointerEnter={() => setLit(s.id)}>
              <i data-stage={s.id} aria-hidden="true" />
              <span>{s.label}</span>
              <span className="ag-took">{took(s.seconds)}</span>
            </li>
          ))}
        </ol>
        {reviewed && (
          <p className="ag-reviewed">
            <b>When it looked it over</b>
            <q>{reviewed}</q>
          </p>
        )}
        {notes.length > 0 && (
          <div className="ag-summary-notes">
            <b>Your notes it took in</b>
            <ul>
              {notes.map((n) => (
                <li key={n.id}>
                  <q>{n.text}</q>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}
