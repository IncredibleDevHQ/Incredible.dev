// Asking the writer at the caret: a prompt that opens under the line the caret is on. It asks
// about the line (or the words selected in it), the picture the line shows, the chapter or the
// whole film, each with a few changes to pick in one click. Enter asks, Escape puts the caret back
// where it was. While the writer is on another change, what is asked here waits its turn.
import { ArrowUp, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { AgentMark } from "../../ui";

// What a change can be about, from the caret outwards.
export type HereScope = "line" | "words" | "picture" | "chapter" | "film";
const SAID: Record<HereScope, { label: string; ask: string; presets: string[] }> = {
  words: { label: "These words", ask: "What should these words do?", presets: ["A simpler word", "Cut these words", "Say what it means"] },
  line: { label: "This line", ask: "What should change in this line?", presets: ["Shorter", "Plainer words", "Say it as a question"] },
  picture: { label: "Its picture", ask: "What should change in its picture?", presets: ["Simpler", "Larger text", "Show it another way"] },
  chapter: { label: "This chapter", ask: "What should change in this chapter?", presets: ["Shorter", "Add an example", "Open with a question"] },
  film: { label: "The film", ask: "What should change in the film?", presets: ["Make it shorter", "A stronger opening", "Plainer words"] },
};

export function AskHere({
  words,
  scopes,
  start,
  writer,
  mark,
  waits,
  onAsk,
  onClose,
}: {
  // the words selected in the line, or nothing for the whole line
  words: string;
  // what this line can ask about, nearest first, and the one the prompt opens on
  scopes: HereScope[];
  start: HereScope;
  // who will make the change, by name and by logo
  writer: string;
  mark?: string;
  // the writer is on another change: this one waits
  waits: boolean;
  onAsk: (text: string, scope: HereScope) => void;
  onClose: () => void;
}) {
  const [text, setText] = useState("");
  const [scope, setScope] = useState<HereScope>(scopes.includes(start) ? start : scopes[0]);
  const field = useRef<HTMLTextAreaElement>(null);
  // the caret comes here when it opens, and when the scope changes (a block, so the effect
  // returns nothing)
  useEffect(() => {
    field.current?.focus();
  }, [scope]);
  // the field is as tall as its words, up to four lines
  useEffect(() => {
    const el = field.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 96)}px`;
  }, [text]);
  const ask = (said: string) => {
    const t = said.trim();
    if (t) onAsk(t, scope);
  };
  const about = words.length > 40 ? `${words.slice(0, 38).trimEnd()}…` : words;
  return (
    <div className="ep-ai-ask" role="dialog" aria-label="Ask the writer for a change" contentEditable={false}>
      <div className="ep-ai-ask-head">
        <AgentMark mark={mark} size="sm" />
        <b>Ask {writer}</b>
        <span className="ep-ai-ask-scopes" role="radiogroup" aria-label="What the change is about">
          {scopes.map((s) => (
            <button key={s} type="button" role="radio" aria-checked={s === scope} title={s === "words" ? `“${about}”` : undefined} onClick={() => setScope(s)}>
              {SAID[s].label}
            </button>
          ))}
        </span>
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
          placeholder={SAID[scope].ask}
          aria-label={SAID[scope].ask}
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
        {SAID[scope].presets.map((p) => (
          <button key={p} type="button" onClick={() => ask(p)}>
            {p}
          </button>
        ))}
        {waits && <small>The writer is on another change: this one waits its turn.</small>}
      </div>
    </div>
  );
}
