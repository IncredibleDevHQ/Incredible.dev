// Asking the writer at the caret: a prompt that opens under the line the caret is on, about the
// whole line or the words selected in it, with a few changes to pick in one click. Enter asks,
// Escape puts the caret back where it was. While the writer is on another change, what is asked
// here waits its turn, as it does in the change bar.
import { ArrowUp, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { AgentMark } from "../../ui";

// What a person most often wants of a line, or of a few words in it.
const FOR_LINE = ["Shorter", "Plainer words", "Say it as a question"];
const FOR_WORDS = ["A simpler word", "Cut these words", "Say what it means"];

export function AskHere({
  words,
  writer,
  mark,
  waits,
  onAsk,
  onClose,
}: {
  // the words selected in the line, or nothing for the whole line
  words: string;
  // who will make the change, by name and by logo
  writer: string;
  mark?: string;
  // the writer is on another change: this one waits
  waits: boolean;
  onAsk: (text: string) => void;
  onClose: () => void;
}) {
  const [text, setText] = useState("");
  const field = useRef<HTMLTextAreaElement>(null);
  // the caret comes here when it opens (a block, so the effect returns nothing)
  useEffect(() => {
    field.current?.focus();
  }, []);
  // the field is as tall as its words, up to four lines
  useEffect(() => {
    const el = field.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 96)}px`;
  }, [text]);
  const ask = (said: string) => {
    const t = said.trim();
    if (t) onAsk(t);
  };
  const about = words.length > 48 ? `${words.slice(0, 46).trimEnd()}…` : words;
  return (
    <div className="ep-ai-ask" role="dialog" aria-label={words ? "Ask the writer about these words" : "Ask the writer about this line"} contentEditable={false}>
      <div className="ep-ai-ask-head">
        <AgentMark mark={mark} size="sm" />
        <b>Ask {writer}</b>
        <span>{words ? <>about “{about}”</> : "to change this line"}</span>
        <button type="button" className="icon-btn" aria-label="Close" onClick={onClose}>
          <X />
        </button>
      </div>
      <form
        className="ep-ai-ask-field"
        onSubmit={(e) => {
          e.preventDefault();
          ask(text);
        }}
      >
        <textarea
          ref={field}
          rows={1}
          value={text}
          placeholder={words ? "What should these words do?" : "What should change in this line?"}
          aria-label="What should change"
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              ask(text);
            } else if (e.key === "Escape") {
              e.preventDefault();
              e.stopPropagation();
              onClose();
            }
          }}
        />
        <button type="submit" className="ep-ai-ask-send" aria-label={waits ? "Ask for it next" : "Ask for it"} disabled={!text.trim()}>
          <ArrowUp />
        </button>
      </form>
      <div className="ep-ai-ask-presets" role="group" aria-label="Changes to pick">
        {(words ? FOR_WORDS : FOR_LINE).map((p) => (
          <button key={p} type="button" onClick={() => ask(p)}>
            {p}
          </button>
        ))}
        {waits && <small>The writer is on another change: this one waits its turn.</small>}
      </div>
    </div>
  );
}
