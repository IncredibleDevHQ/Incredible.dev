// The menu a slash opens in a chapter's script: the blocks a chapter can be given, each by its
// icon, its name and what it is in a line, with the keys that make one where there are some;
// under them, asking the writer for a change. What is typed after the slash narrows it, the arrow
// keys move through it, and Enter picks.
import { Sparkles, User } from "lucide-react";
import { useEffect, useRef } from "react";
import type { LineKind, PictureKind } from "../../api";
import { PICTURES } from "../../episode";
import { Kbd } from "../Kbd";
import { KIND_ICONS } from "./Blocks";

export type SlashItem = { kind: LineKind | "ask"; title: string; note: string; keys?: string; group: "add" | "ask"; words: string[] };
export type SlashState = { items: SlashItem[]; at: number; rect: DOMRect | null; choose: (item: SlashItem) => void };

export const PICTURE_KINDS: PictureKind[] = ["diagram", "list", "typeset-code", "chips", "illustration", "slide"];
// What a kind is also called, for the search.
const ALSO: Record<string, string[]> = {
  camera: ["camera", "talk", "person", "face", "say", "speak"],
  diagram: ["diagram", "flow", "arrows", "boxes", "pipeline"],
  list: ["list", "bullets", "points", "items"],
  "typeset-code": ["code", "snippet", "source"],
  chips: ["chips", "tags", "labels", "cards"],
  illustration: ["illustration", "image", "picture", "drawing", "metaphor"],
  slide: ["slide", "heading", "title"],
};
// The keys that make a block on a new line, as in markdown.
export const SHORTCUTS: Record<string, string> = { list: "- ", "typeset-code": "```" };
const GROUPS = { add: "Add a block", ask: "Ask the writer" } as const;

export function slashItems(query: string, pictures: { id: string; means: string }[]): SlashItem[] {
  const all: SlashItem[] = [
    { kind: "camera", title: "To camera", note: "A line you say to the camera.", group: "add", words: ALSO.camera },
    ...PICTURE_KINDS.map((k) => ({
      kind: k,
      title: PICTURES[k] ?? k,
      note: pictures.find((p) => p.id === k)?.means ?? "",
      keys: SHORTCUTS[k]?.trim(),
      group: "add" as const,
      words: ALSO[k] ?? [],
    })),
    { kind: "ask", title: "Ask for a change", note: "The writer changes this line, or more of the film.", group: "ask", words: ["ask", "change", "writer", "rewrite"] },
  ];
  const q = query.trim().toLowerCase();
  return q ? all.filter((i) => i.title.toLowerCase().includes(q) || i.words.some((w) => w.startsWith(q))) : all;
}

export function SlashMenu({ state, onAt }: { state: SlashState; onAt: (at: number) => void }) {
  const box = useRef<HTMLDivElement>(null);
  // the picked item stays in sight (a block, so the effect returns nothing)
  useEffect(() => {
    box.current?.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: "nearest" });
  }, [state.at]);
  const rect = state.rect;
  if (!rect) return null;
  // under the caret, or over it where the window has no room below
  const below = window.innerHeight - rect.bottom > 360;
  const left = Math.max(12, Math.min(rect.left - 8, window.innerWidth - 348));
  const style = below ? { left, top: rect.bottom + 6 } : { left, bottom: window.innerHeight - rect.top + 6 };
  let n = -1;
  return (
    // a press here keeps the caret in the script, so the line it is on is not left
    <div ref={box} className="ep-slash" role="listbox" aria-label="Add a block" style={style} onMouseDown={(e) => e.preventDefault()}>
      {state.items.length === 0 ? (
        <p className="ep-slash-none">Nothing by that name</p>
      ) : (
        (["add", "ask"] as const).map((group) => {
          const items = state.items.filter((i) => i.group === group);
          if (!items.length) return null;
          return (
            <div key={group} className="ep-slash-group" role="group" aria-label={GROUPS[group]}>
              <small>{GROUPS[group]}</small>
              {items.map((item) => {
                n += 1;
                const at = n;
                const Icon = item.kind === "ask" ? Sparkles : item.kind === "camera" ? User : (KIND_ICONS[item.kind] ?? Sparkles);
                return (
                  <button key={item.kind} type="button" role="option" aria-selected={at === state.at} className="ep-slash-item" onMouseEnter={() => onAt(at)} onClick={() => state.choose(item)}>
                    <span className="ep-slash-tile" aria-hidden="true">
                      <Icon />
                    </span>
                    <span className="ep-slash-words">
                      <b>{item.title}</b>
                      {item.note && <small>{item.note}</small>}
                    </span>
                    {item.keys && <Kbd keys={item.keys} size="sm" />}
                  </button>
                );
              })}
            </div>
          );
        })
      )}
    </div>
  );
}
