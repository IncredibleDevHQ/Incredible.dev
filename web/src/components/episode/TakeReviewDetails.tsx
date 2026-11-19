import { RotateCcw, Save } from "lucide-react";
import { mmss } from "../../episode";
import { TextField } from "../TextField";

export function TakeReviewDetails({ title, seconds, video, lines, label, onLabel, saving, problem, onSave, onAgain }: {
  title: string;
  seconds: number;
  video: boolean;
  lines: { id: string; vo: string }[];
  label: string;
  onLabel: (label: string) => void;
  saving: boolean;
  problem: string;
  onSave: () => void;
  onAgain: () => void;
}) {
  return <div className="ep-review-details">
    <header className="ep-review-heading">
      <span className="ep-review-status">Unsaved take</span>
      <h2>Review your take</h2>
      <p>{title}</p>
      <span className="ep-kicker">{mmss(seconds)} · {video ? "Video + audio" : "Audio only"} · {lines.length} {lines.length === 1 ? "line" : "lines"}</span>
    </header>
    <div className="ep-review-save">
      <TextField label="Version name" optional size="lg" maxLength={120} value={label} disabled={saving}
        onChange={event => onLabel(event.target.value)} placeholder="e.g. Calm delivery" />
      {problem && <p className="ep-notice" data-tone="red" role="alert">{problem}</p>}
      <div className="ep-review-actions">
        <button className="btn primary" type="button" disabled={saving} onClick={onSave}><Save />{saving ? "Saving…" : "Save take"}</button>
        <button className="btn" type="button" disabled={saving} onClick={onAgain}><RotateCcw />Record again</button>
      </div>
      <p className="faint">Save to keep this version in chapter history.</p>
    </div>
    <section className="ep-review-script" aria-label="Script reference">
      <h3>Chapter script</h3>
      <ol aria-label="Recorded script">{lines.map((line,index) => <li key={line.id}><span className="ep-kicker">Line {index + 1}</span><p>{line.vo}</p></li>)}</ol>
    </section>
  </div>;
}
