// A note for an agent while it works, without stopping it: the note waits for the agent's next
// turn and goes in with it, and can be taken back until then. Enter queues a note, Shift+Enter
// starts a new line, Escape clears what is typed. Written for this house from notes on how
// steering components behave; no other component's source is in it.
import { ArrowUp, X } from "lucide-react";
import { useId, useRef, useState, type KeyboardEvent } from "react";
import { Kbd } from "../Kbd";
import "./agent.css";

export type QueuedNote = { id: string; text: string };

// The field grows with what is typed up to this many pixels (three lines), then scrolls.
const TALLEST = 72;

export function Steer({
  queued,
  reaches,
  onQueue,
  onTakeBack,
}: {
  queued: QueuedNote[];
  // when a note reaches the agent, in a few words ("Claude Code as it starts drawing")
  reaches: string;
  // each says whether it went through; a refusal is shown by whoever runs the call
  onQueue: (text: string) => Promise<boolean>;
  onTakeBack: (id: string) => Promise<boolean>;
}) {
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [heard, setHeard] = useState("");
  const area = useRef<HTMLTextAreaElement>(null);
  const hint = useId();

  const fit = (el: HTMLTextAreaElement | null) => {
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, TALLEST)}px`;
  };
  const send = async () => {
    const said = text.trim();
    if (!said || sending) return;
    setSending(true);
    const ok = await onQueue(said);
    setSending(false);
    if (!ok) return;
    setText("");
    setHeard(`Queued for its next turn: ${said}`);
    requestAnimationFrame(() => fit(area.current));
  };
  const keys = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void send();
    } else if (e.key === "Escape" && text) {
      // a draft is cleared first; an empty field lets Escape go on to whatever holds it
      e.preventDefault();
      e.stopPropagation();
      setText("");
      requestAnimationFrame(() => fit(area.current));
    }
  };

  return (
    <div className="ag-steer">
      {queued.length > 0 && (
        <div className="ag-queue">
          <span className="ag-queue-head">
            Waiting for its next turn <b>{queued.length}</b>
          </span>
          <ul>
            {queued.map((note) => (
              <li key={note.id}>
                <span>{note.text}</span>
                <button
                  type="button"
                  aria-label={`Take back “${note.text}”`}
                  title="Take it back"
                  onClick={() => void onTakeBack(note.id).then((ok) => ok && setHeard("Note taken back"))}
                >
                  <X />
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      <div
        className="ag-field"
        onMouseDown={(e) => {
          // a press on the field's own padding puts the caret in it, without scrolling the page
          if (e.target !== e.currentTarget) return;
          e.preventDefault();
          area.current?.focus({ preventScroll: true });
        }}
      >
        <textarea
          ref={area}
          rows={1}
          value={text}
          maxLength={600}
          placeholder="Add a note for it, without stopping it"
          aria-label="A note for its next turn"
          aria-describedby={hint}
          onChange={(e) => {
            setText(e.target.value);
            fit(e.target);
          }}
          onKeyDown={keys}
        />
        <button type="button" className="ag-send" aria-label="Queue the note" disabled={!text.trim() || sending} onClick={() => void send()}>
          <ArrowUp />
        </button>
      </div>
      <small id={hint} className="ag-hint">
        <Kbd keys="enter" size="sm" /> queues it. It reaches {reaches}.
      </small>
      <span className="sr-only" role="status" aria-live="polite">
        {heard}
      </span>
    </div>
  );
}
