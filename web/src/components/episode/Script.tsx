// A chapter's script as one document, written the way a text is. It reads in blocks: one for
// each picture with the lines it is shown on, one for each run of lines said to camera. Words are
// typed where they are read, and kept when the caret leaves the line. Enter starts the next line
// of a block (in the middle of a line it splits it, as one change), Backspace at the start of a
// line joins it to the line before it in its block, and a slash opens the blocks a chapter can
// be given: a line to camera, or a picture of one of the kinds the writer designs.
//
// Nothing typed or added here runs an agent. A line to camera is ready at once; a picture a new
// line asks for, and one whose lines changed, wait for the person to apply their changes.
//
// The server holds the plan. The document is the person's working copy of one chapter: a line
// they have not kept yet lives only here, and every view that comes back is laid over it without
// taking their unsaved words away.
import { Extension, Node, type Editor, type JSONContent } from "@tiptap/core";
import type { Node as PMNode } from "@tiptap/pm/model";
import { Plugin, PluginKey, TextSelection, type EditorState, type Transaction } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";
import { EditorContent, NodeViewContent, NodeViewWrapper, ReactNodeViewRenderer, useEditor, type ReactNodeViewProps } from "@tiptap/react";
import Suggestion, { type SuggestionKeyDownProps, type SuggestionProps } from "@tiptap/suggestion";
import { Mic, Trash2, Undo2 } from "lucide-react";
import { createContext, useContext, useEffect, useImperativeHandle, useMemo, useRef, useState, type Ref } from "react";
import { api, type EpisodeChapter, type EpisodeFrame, type EpisodeTake, type EpisodeUnit, type EpisodeView, type LineKind } from "../../api";
import { pictureState, PICTURES, PRESENCE, unitOf } from "../../episode";
import { useHouse } from "../../store";
import { Tooltip } from "../Tooltip";
import type { Run } from "./Ask";
import { BlockHead, blocksOf, KIND_ICONS, type Block } from "./Blocks";
import { wordDiff } from "./Diff";
import { AgentMark } from "../../ui";
import { AskHere, type HereScope } from "./AskHere";
import { WRITERS } from "./Film";
import { PictureCard } from "./Picture";
import { SHORTCUTS, SlashMenu, slashItems, type SlashItem, type SlashState } from "./Slash";

// -- the document ------------------------------------------------------------------------------

// A line in the document: `uid` is its identity here, `id` the plan's (empty until it is kept),
// `base` the words the plan has for it, `kind` what it was added as, and `split` the line it was
// split from, whose first half is kept with it as one change.
type LineAttrs = { uid: string; id: string; base: string; kind: LineKind; split: string };
// A block: `unit` is its picture's, and `kind` says what a block the person added is asking for.
type BlockAttrs = { key: string; unit: string; kind: "" | LineKind };
type Here = LineAttrs & { text: string; block: BlockAttrs; pos: number; blockPos: number; blockIndex: number; index: number; count: number };

// Changes the document's shape (a line or a block added, split, joined or gone, or a view laid
// over it). Anything else that would change its shape, such as typing over two lines at once, is
// refused: the plan has no way to say it.
const SCRIPT = "episode-script";

let made = 0;
const fresh = () => `new-${++made}`;
const words = (text: string) => text.replace(/\s+/g, " ").trim();
// A line's words as they are kept: a slash and what was typed after it, left at the end when the
// menu closed without a pick, is not part of them.
const kept = (text: string) => words(text.replace(/(^|\s)\/[\p{L}\p{N}-]*$/u, ""));

function linesIn(doc: PMNode): Here[] {
  const out: Here[] = [];
  doc.forEach((block, blockPos, blockIndex) => {
    block.forEach((line, offset, index) => {
      out.push({ ...(line.attrs as LineAttrs), text: line.textContent, block: block.attrs as BlockAttrs, pos: blockPos + 1 + offset, blockPos, blockIndex, index, count: block.childCount });
    });
  });
  return out;
}

// The line the caret is in.
function lineAt(state: EditorState): Here | undefined {
  const at = state.selection.$from;
  if (at.depth < 2) return undefined;
  const uid = (at.node(2).attrs as LineAttrs).uid;
  return linesIn(state.doc).find((l) => l.uid === uid);
}

// A shape for comparing two documents: what is in them, not how it is held.
const shapeOf = (doc: JSONContent) => JSON.stringify((doc.content ?? []).map((b) => [b.attrs, (b.content ?? []).map((l) => [l.attrs, (l.content ?? []).map((t) => t.text ?? "").join("")])]));

const attrsOf = (l: LineAttrs): LineAttrs => ({ uid: l.uid, id: l.id, base: l.base, kind: l.kind, split: l.split });
const lineNode = (attrs: LineAttrs, text: string): JSONContent => ({ type: "scriptLine", attrs, content: text ? [{ type: "text", text }] : [] });
const blockNode = (attrs: BlockAttrs, lines: JSONContent[]): JSONContent => ({ type: "scriptBlock", attrs, content: lines });

// The document a chapter's blocks make, with the person's unsaved work laid in where it was: a
// line they changed keeps their words, and a line they have not kept yet stays after the line it
// followed (in that line's block, or as a block of its own after it).
function layout(blocks: Block[], doc: PMNode | null): JSONContent {
  const here = doc ? linesIn(doc) : [];
  const byId = new Map(here.filter((l) => l.id).map((l) => [l.id, l]));
  const after = new Map<string, Here[]>();
  let last = "";
  for (const l of here) {
    if (l.id) last = l.id;
    else after.set(last, [...(after.get(last) ?? []), l]);
  }
  const used = new Set<string>();
  const content: JSONContent[] = [];
  const own = (pending: Here[]) => {
    // the person's blocks, each kept whole, in the order they were in
    const groups: Here[][] = [];
    for (const p of pending) {
      const open = groups[groups.length - 1];
      if (open && open[0].block.key === p.block.key) open.push(p);
      else groups.push([p]);
    }
    for (const g of groups) {
      g.forEach((p) => used.add(p.uid));
      content.push(
        blockNode(
          g[0].block,
          g.map((p) => lineNode(attrsOf(p), p.text)),
        ),
      );
    }
  };
  own((after.get("") ?? []).filter((p) => p.block.kind));
  let prev = "";
  for (const b of blocks) {
    const lines: JSONContent[] = [];
    const trailing: Here[] = [];
    for (const s of b.lines) {
      let mine = byId.get(s.id);
      if (!mine) {
        // a line the person added that the plan now has: the one they sent, in the same place
        mine = (after.get(prev) ?? []).find((p) => !used.has(p.uid) && words(p.text) === words(s.vo));
      }
      prev = s.id;
      if (mine) used.add(mine.uid);
      const dirty = mine !== undefined && mine.id === s.id && words(mine.text) !== words(mine.base);
      lines.push(lineNode({ uid: mine?.uid ?? s.id, id: s.id, base: s.vo, kind: "more", split: "" }, dirty ? mine!.text : s.vo));
      for (const p of after.get(s.id) ?? []) {
        if (used.has(p.uid)) continue;
        if (p.block.kind) trailing.push(p);
        else {
          used.add(p.uid);
          lines.push(lineNode(attrsOf(p), p.text));
        }
      }
    }
    content.push(blockNode({ key: b.key, unit: b.unit?.id ?? "", kind: "" }, lines));
    own(trailing.filter((p) => !used.has(p.uid)));
  }
  // a line whose place went (the line it followed was cut): it stays, at the end
  own(here.filter((l) => !l.id && !used.has(l.uid)));
  return { type: "doc", content };
}

// -- what the node views read ------------------------------------------------------------------

type Ctx = {
  view: EpisodeView;
  chapter: EpisodeChapter;
  byId: Map<string, EpisodeFrame>;
  lines: EpisodeFrame[];
  current: string;
  recording: boolean;
  said: number;
  solo: string | null;
  take: EpisodeTake | undefined;
  marked: boolean;
  was: Record<string, string>;
  changed: Set<string>;
  cuts: Map<string, string[]>;
  run: Run;
  busy: boolean;
  onPick: (frame: string) => void;
  onOpen: (unit: EpisodeUnit) => void;
  onReword: (frame: string, text: string) => void;
  onRecordLine: (frame: string) => void;
  onCutBlock: (uid: string) => void;
  // the line asked about at the caret (and the words selected in it), and how to ask
  asking: Asking | null;
  onAskHere: (text: string, scope: HereScope) => void;
  onCloseAsk: () => void;
  // the writer, by name and logo, and the line its turn is on while it works
  writer: string;
  mark?: string;
  working: boolean;
  onLine: string;
  onPicture: string;
  onStop: () => void;
};
const ScriptCtx = createContext<Ctx | null>(null);
const useScript = () => useContext(ScriptCtx)!;

// How long a line runs as it is typed: its words, and the seconds they take at the plan's own pace
// for it, so the length reads as the rest of the script's does.
function length(text: string, line: EpisodeFrame | undefined): string {
  const n = text.trim() ? text.trim().split(/\s+/).length : 0;
  const pace = line?.words && line.seconds ? line.words / line.seconds : 2.6;
  return `${n} ${n === 1 ? "word" : "words"} · about ${Math.max(1, Math.round(n / pace))} s`;
}

// The words shown in a line nobody has written yet.
const HINTS: Record<string, string> = {
  more: "Say the next line",
  camera: "Say it to camera",
};
const hintOf = (kind: LineKind) => HINTS[kind] ?? `Say what this ${(PICTURES[kind] ?? "picture").toLowerCase()} shows`;

function BlockView({ node }: ReactNodeViewProps) {
  const c = useScript();
  const attrs = node.attrs as BlockAttrs;
  const ids: string[] = [];
  node.forEach((l) => {
    const id = (l.attrs as LineAttrs).id;
    if (id) ids.push(id);
  });
  const lines = ids.map((id) => c.byId.get(id)).filter((l): l is EpisodeFrame => l !== undefined);
  const unit = attrs.unit ? c.view.units.find((u) => u.id === attrs.unit) : undefined;
  const cut = (
    <Tooltip content={attrs.kind ? "Take this block out" : "Cut this block"} side="bottom" align="end">
      <button
        type="button"
        className="icon-btn ep-script-cut"
        aria-label={attrs.kind ? "Take this block out" : "Cut this block"}
        disabled={c.busy || c.recording}
        onClick={() => c.onCutBlock(attrs.key)}
      >
        <Trash2 />
      </button>
    </Tooltip>
  );
  if (attrs.kind) {
    // a block the person added and has not kept yet: what it asks for, and how it will be made
    const Icon = KIND_ICONS[attrs.kind] ?? KIND_ICONS.camera;
    const picture = attrs.kind !== "camera" && attrs.kind !== "more";
    return (
      <NodeViewWrapper className={`ep-block ${picture ? "ep-figure" : ""}`} data-new="">
        <header className="ep-block-head" data-status={picture ? "planned" : "camera"} contentEditable={false}>
          <Icon aria-hidden="true" />
          <b>{picture ? (PICTURES[attrs.kind] ?? "Picture") : "To camera"}</b>
          <span>{picture ? "New · the writer designs it when you apply your changes" : "New"}</span>
          {cut}
        </header>
        <NodeViewContent className="ep-block-lines" role="list" />
      </NodeViewWrapper>
    );
  }
  const block: Block = { key: attrs.key, unit, lines };
  if (unit) {
    return (
      <NodeViewWrapper className="ep-block ep-figure" data-state={pictureState(unit, c.view)}>
        <div contentEditable={false} className="ep-figure-wrap">
          <PictureCard
            view={c.view}
            block={block as Block & { unit: EpisodeUnit }}
            lines={c.lines}
            picked={c.current}
            onPick={c.onPick}
            onOpen={() => c.onOpen(unit)}
            run={c.run}
            busy={c.busy || c.recording}
            tools={cut}
          />
          {c.working && c.onPicture && unit.frames.includes(c.onPicture) && (
            <span className="ep-ai-at" role="status">
              <AgentMark mark={c.mark} size="sm" />
              {c.writer.slice(0, 1).toUpperCase() + c.writer.slice(1)} is changing this picture
              <button type="button" className="ep-ai-stop" onClick={c.onStop}>
                Stop
              </button>
            </span>
          )}
        </div>
        <NodeViewContent className="ep-block-lines" role="list" />
      </NodeViewWrapper>
    );
  }
  return (
    <NodeViewWrapper className="ep-block">
      <div contentEditable={false} className="ep-block-top">
        <BlockHead block={block} view={c.view} />
        {cut}
      </div>
      <NodeViewContent className="ep-block-lines" role="list" />
    </NodeViewWrapper>
  );
}

function LineView({ node }: ReactNodeViewProps) {
  const c = useScript();
  const attrs = node.attrs as LineAttrs;
  const line = attrs.id ? c.byId.get(attrs.id) : undefined;
  const i = line ? c.lines.indexOf(line) : -1;
  const current = Boolean(attrs.id) && attrs.id === c.current;
  const empty = node.content.size === 0;
  const again = attrs.id ? c.view.rerecord.includes(attrs.id) : false;
  const before = c.marked && attrs.id ? c.was[attrs.id] : undefined;
  // What a rich picture does on this line, from its motion plan: on every line while the picture
  // is drawn and looked at, after that on the line that is picked.
  const mine = line ? unitOf(c.view, line.id) : undefined;
  const shot = mine?.picture.motion?.shots.find((s) => s.frame === line?.id);
  const reviewing = mine ? ["making", "go"].includes(pictureState(mine)) : false;
  const presence = line?.presence ?? (attrs.kind === "camera" ? "person" : attrs.kind === "more" ? "" : "both");
  // what was made from this line before its words changed: its picture, or the take
  const theirs = Boolean(line?.by_person) && line?.vo !== line?.by_person?.was;
  const behind = again ? "take" : theirs && mine && pictureState(mine, c.view) === "reworded" ? "picture" : undefined;
  const status = c.recording ? (i >= 0 && i < c.said && !c.solo ? "✓" : "") : current ? "" : again ? "Say again" : c.take && line ? "✓" : "";
  return (
    <NodeViewWrapper
      className="ep-line-card"
      role="listitem"
      data-current={current || undefined}
      data-new={!attrs.id || undefined}
      data-behind={behind}
      data-ai={(c.working && c.onLine === attrs.id) || undefined}
      data-recording-at={(c.recording && i === c.said) || undefined}
    >
      <i className="ep-who" data-presence={presence || undefined} aria-label={presence ? PRESENCE[presence] : "A new line"} contentEditable={false} />
      <div className="ep-line-body">
        <NodeViewContent<"p"> as="p" className="ep-line-text" />
        {empty && (
          <span className="ep-line-hint" contentEditable={false} aria-hidden="true">
            {hintOf(attrs.kind)}
          </span>
        )}
        {c.working && c.onLine === attrs.id && (
          // the writer at work on this line, as a teammate's cursor would be
          <span className="ep-ai-at" contentEditable={false} role="status">
            <AgentMark mark={c.mark} size="sm" />
            {c.writer.slice(0, 1).toUpperCase() + c.writer.slice(1)} is changing this line
            <button type="button" className="ep-ai-stop" onClick={c.onStop}>
              Stop
            </button>
          </span>
        )}
        {status && (
          <small className="ep-line-status" data-tone={status === "Say again" ? "amber" : undefined} contentEditable={false}>
            {status}
          </small>
        )}
        {!c.recording && !current && !before && c.changed.has(attrs.id) && <em className="ep-line-changed" aria-label="Changed" contentEditable={false} />}
        {shot && !c.recording && (current || reviewing) && (
          <p className="ep-shot" title={`It ends on: ${shot.still}`} contentEditable={false}>
            {shot.shot || shot.hero}
          </p>
        )}
        {current && !c.recording && (
          <div className="ep-line-foot" contentEditable={false}>
            <small data-tone={behind ? "amber" : undefined}>
              {again ? "Say again · " : behind === "picture" ? "Its picture was made for the words before · " : c.take ? "Recorded · " : ""}
              {length(node.textContent, line)}
            </small>
            {before !== undefined && (
              <Tooltip content="Put the old words back" side="bottom">
                <button type="button" className="icon-btn" aria-label="Put the old words back" disabled={c.busy} onClick={() => c.onReword(attrs.id, before)}>
                  <Undo2 />
                </button>
              </Tooltip>
            )}
            {c.take && (
              <Tooltip content="Record this line again" side="bottom">
                <button type="button" className="icon-btn" aria-label="Record this line again" disabled={c.busy} onClick={() => c.onRecordLine(attrs.id)}>
                  <Mic />
                </button>
              </Tooltip>
            )}
          </div>
        )}
      </div>
      {c.asking?.line === attrs.id && attrs.id && (
        <AskHere
          words={c.asking.words}
          scopes={[...(c.asking.words ? (["words"] as const) : []), "line", ...(mine?.kind === "picture" ? (["picture"] as const) : []), "chapter", "film"]}
          start={c.asking.scope}
          writer={c.writer}
          mark={c.mark}
          waits={c.working}
          onAsk={c.onAskHere}
          onClose={c.onCloseAsk}
        />
      )}
      {c.marked &&
        c.cuts.get(attrs.id)?.map((says, n) => (
          <div key={n} className="ep-line-cut" contentEditable={false}>
            <del>{says}</del>
            <small>Cut</small>
          </div>
        ))}
    </NodeViewWrapper>
  );
}

// -- the schema --------------------------------------------------------------------------------

const Doc = Node.create({ name: "doc", topNode: true, content: "scriptBlock+" });
const Text = Node.create({ name: "text", group: "inline" });
const quiet = (fallback: unknown) => ({ default: fallback, renderHTML: () => ({}), parseHTML: () => fallback });
const ScriptBlock = Node.create({
  name: "scriptBlock",
  content: "scriptLine+",
  isolating: true,
  selectable: false,
  addAttributes: () => ({ key: quiet(""), unit: quiet(""), kind: quiet("") }),
  parseHTML: () => [{ tag: "section[data-script-block]" }],
  renderHTML: () => ["section", { "data-script-block": "" }, 0],
  addNodeView: () => ReactNodeViewRenderer(BlockView, { className: "ep-script-block" }),
});
const ScriptLine = Node.create({
  name: "scriptLine",
  content: "text*",
  marks: "",
  addAttributes: () => ({ uid: quiet(""), id: quiet(""), base: quiet(""), kind: quiet("more"), split: quiet("") }),
  parseHTML: () => [{ tag: "p[data-script-line]" }],
  renderHTML: () => ["p", { "data-script-line": "" }, 0],
  addNodeView: () => ReactNodeViewRenderer(LineView, { className: "ep-script-line", contentDOMElementTag: "span" }),
});

// The shape of the document: which lines, in which blocks.
const bones = (doc: PMNode) =>
  linesIn(doc)
    .map((l) => `${l.blockIndex}:${l.uid}`)
    .join(" ");

// Refuses a change of shape nobody here made, and puts what the last change did into the words:
// what went struck through, what came in marked.
const MARKS = new PluginKey<Record<string, string>>("episode-script-marks");
function guard(): Plugin {
  return new Plugin({
    filterTransaction: (tr, state) => !tr.docChanged || Boolean(tr.getMeta(SCRIPT)) || bones(tr.doc) === bones(state.doc),
  });
}
function marks(): Plugin<Record<string, string>> {
  return new Plugin<Record<string, string>>({
    key: MARKS,
    state: { init: () => ({}), apply: (tr, value) => (tr.getMeta(MARKS) as Record<string, string> | undefined) ?? value },
    props: {
      decorations(state) {
        const was = MARKS.getState(state) ?? {};
        const out: Decoration[] = [];
        for (const l of linesIn(state.doc)) {
          const before = l.id ? was[l.id] : undefined;
          if (before === undefined) continue;
          const tokens = [...l.text.matchAll(/\S+/g)];
          const start = l.pos + 1;
          let k = 0;
          for (const piece of wordDiff(before, l.text)) {
            if (piece.kind === "cut") {
              const end = k >= tokens.length;
              const at = end ? start + l.text.length : start + tokens[k].index;
              out.push(
                Decoration.widget(
                  at,
                  () => {
                    const del = document.createElement("del");
                    del.textContent = end ? ` ${piece.text}` : `${piece.text} `;
                    del.setAttribute("aria-hidden", "true");
                    del.contentEditable = "false";
                    return del;
                  },
                  { side: -1, key: `${l.uid}-${at}-${piece.text}` },
                ),
              );
              continue;
            }
            const n = piece.text.split(" ").length;
            if (piece.kind === "new" && tokens[k]) {
              const last = tokens[Math.min(k + n, tokens.length) - 1];
              out.push(Decoration.inline(start + tokens[k].index, start + last.index + last[0].length, { nodeName: "ins" }));
            }
            k += n;
          }
        }
        return DecorationSet.create(state.doc, out);
      },
    },
  });
}

// The pill that offers the writer's help where the caret is placed: at the end of the line, or
// of the words selected in it. It shows only when it is turned on (the caret is placed and no
// words are being typed), and a press opens the prompt without moving the caret.
const HINT = new PluginKey<{ show: boolean }>("episode-script-hint");
function hint(open: () => void): Plugin<{ show: boolean }> {
  return new Plugin<{ show: boolean }>({
    key: HINT,
    state: { init: () => ({ show: false }), apply: (tr, value) => (tr.getMeta(HINT) as { show: boolean } | undefined) ?? value },
    props: {
      decorations(state) {
        if (!HINT.getState(state)?.show) return DecorationSet.empty;
        const here = lineAt(state);
        if (!here?.id) return DecorationSet.empty;
        const sel = state.selection;
        const some = !sel.empty && sel.$from.parent === sel.$to.parent;
        const at = some ? sel.to : here.pos + 1 + here.text.length;
        const label = some ? "Ask AI about these words" : "Ask AI";
        const pill = () => {
          const button = document.createElement("button");
          button.type = "button";
          button.className = "ep-ai-hint";
          button.contentEditable = "false";
          button.setAttribute("aria-label", `${label} (Cmd J)`);
          const star = document.createElement("i");
          star.textContent = "✦";
          star.setAttribute("aria-hidden", "true");
          const words = document.createElement("span");
          words.textContent = some ? "Ask AI" : "Ask AI";
          const key = document.createElement("kbd");
          key.textContent = navigator.platform.includes("Mac") ? "⌘J" : "Ctrl J";
          button.append(star, words, key);
          button.addEventListener("mousedown", (e) => {
            e.preventDefault();
            open();
          });
          return button;
        };
        return DecorationSet.create(state.doc, [Decoration.widget(at, pill, { side: 1, key: `hint-${here.uid}-${at}-${some}`, ignoreSelection: true, stopEvent: () => true })]);
      },
    },
  });
}

// -- the editor --------------------------------------------------------------------------------

// What the prompt at the caret is open on: a line, the words selected in it, and what it asks about.
type Asking = { line: string; words: string; scope: HereScope };

export type ScriptHandle = {
  focusLine: (frame: string, slash?: boolean) => void;
  // opens the prompt at the end of a line, asking about it, its picture, the chapter or the film
  askAt: (frame: string, scope: HereScope) => void;
};

export function Script({
  ref,
  view,
  chapter,
  lines,
  current,
  recording,
  said,
  solo,
  take,
  marked,
  run,
  busy,
  onPick,
  onOpen,
  onReword,
  onRecordLine,
  onAskLine,
  onUndo,
  onRedo,
}: {
  ref?: Ref<ScriptHandle>;
  view: EpisodeView;
  chapter: EpisodeChapter;
  lines: EpisodeFrame[];
  // the line the preview shows: the picked one, or while recording the one being said
  current: string;
  recording: boolean;
  said: number;
  solo: string | null;
  take: EpisodeTake | undefined;
  marked: boolean;
  run: Run;
  busy: boolean;
  onPick: (frame: string) => void;
  onOpen: (unit: EpisodeUnit) => void;
  onReword: (frame: string, text: string) => void;
  onRecordLine: (frame: string) => void;
  // the writer asked, at the caret, to change a line or the words selected in it
  onAskLine: (frame: string, words: string, text: string, scope: HereScope) => void;
  // the studio's own undo and redo, of the last change kept
  onUndo: () => void;
  onRedo: () => void;
}) {
  const blocks = useMemo(() => blocksOf(view, lines), [view, lines]);
  const working = view.stage.state === "working" || view.stage.state === "reading";
  const [menu, setMenu] = useState<SlashState | null>(null);
  const menuRef = useRef<SlashState | null>(null);
  menuRef.current = menu;
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  const on = useRef({ onPick, onUndo, onRedo, chapter: chapter.id, view: view.id, pictures: view.options.pictures });
  on.current = { onPick, onUndo, onRedo, chapter: chapter.id, view: view.id, pictures: view.options.pictures };
  const caret = useRef("");
  const editorRef = useRef<Editor | null>(null);
  const [asking, setAsking] = useState<Asking | null>(null);
  const [focused, setFocused] = useState(false);
  const [typing, setTyping] = useState(false);
  const quietTimer = useRef(0);
  const openRef = useRef((_scope?: HereScope) => {});
  // while the writer is on a change the script can't be edited, but a change can still be asked
  // for here: it waits its turn
  openRef.current = (scope) => {
    const ed = editorRef.current;
    if (!ed || recording) return;
    const here = lineAt(ed.state);
    if (!here?.id) return;
    const sel = ed.state.selection;
    const words = !sel.empty && sel.$from.parent === sel.$to.parent ? ed.state.doc.textBetween(sel.from, sel.to).trim() : "";
    onPick(here.id);
    setAsking({ line: here.id, words, scope: scope ?? (words ? "words" : "line") });
  };

  // Every call the document makes goes one after another, so a line is kept before the line
  // after it is sent. A refusal is said, and the plan as it stands is read again.
  const send = (job: () => Promise<void>) => {
    queue.current = queue.current.then(job).catch((error: Error) => {
      useHouse.getState().say(error.message);
      void api
        .episode(on.current.view)
        .then((v) => useHouse.getState().setEpisode(v))
        .catch(() => undefined);
    });
  };
  const land = (v: EpisodeView) => useHouse.getState().setEpisode(v);

  // A transaction that changes the document's shape, made here.
  const shape = (editor: Editor, build: (tr: Transaction) => void) => {
    const tr = editor.state.tr.setMeta(SCRIPT, true);
    build(tr);
    editor.view.dispatch(tr);
  };
  const setAttrs = (editor: Editor, uid: string, attrs: Partial<LineAttrs>, text?: string) =>
    shape(editor, (tr) => {
      const l = linesIn(tr.doc).find((x) => x.uid === uid);
      if (!l) return;
      tr.setNodeMarkup(l.pos, undefined, { ...attrsOf(l), ...attrs });
      if (text !== undefined && text !== l.text) {
        const node = tr.doc.nodeAt(l.pos)!;
        tr.replaceWith(l.pos + 1, l.pos + 1 + node.content.size, text ? editor.schema.text(text) : []);
      }
    });

  // A line the caret has left: its words are kept (a line with none is cut), and one the
  // person added is sent to the plan. The first half of a split goes with its second.
  const leave = (editor: Editor, uid: string, into: string) => {
    const doc = editor.state.doc;
    const all = linesIn(doc);
    const l = all.find((x) => x.uid === uid);
    if (!l) return;
    if (into && all.find((x) => x.uid === into)?.split === uid) return;
    if (l.id) {
      if (kept(l.text) === words(l.base)) return;
      if (!kept(l.text)) {
        cutLocal(editor, [uid]);
        return send(async () => land(await api.cutLines(on.current.view, [l.id])));
      }
      const text = kept(l.text);
      return send(async () => {
        const v = await api.editLine(on.current.view, l.id, text);
        setAttrs(editor, uid, { base: text });
        land(v);
      });
    }
    if (!kept(l.text)) return cutLocal(editor, [uid]);
    send(async () => {
      const now = linesIn(editor.state.doc);
      const k = now.findIndex((x) => x.uid === uid);
      if (k < 0 || now[k].id || !kept(now[k].text)) return;
      const me = now[k];
      const prev = now
        .slice(0, k)
        .reverse()
        .find((x) => x.id);
      const from = me.split ? now.find((x) => x.uid === me.split) : undefined;
      const keep = from?.id && kept(from.text) !== words(from.base) ? kept(from.text) : undefined;
      const kind: LineKind = !prev && me.kind === "more" ? "camera" : me.kind;
      const text = kept(me.text);
      const v = await api.addLine(on.current.view, { after: prev?.id ?? on.current.chapter, text, kind, keep });
      const id = v.last_change?.added?.find((a) => !now.some((x) => x.id === a));
      if (id) setAttrs(editor, uid, { id, base: text, split: "" });
      if (from && keep !== undefined) setAttrs(editor, from.uid, { base: keep });
      land(v);
    });
  };

  // Lines taken out here at once (the plan is told by whoever calls this); a block left with
  // none goes too, and the caret goes to the end of the line before.
  const cutLocal = (editor: Editor, uids: string[]) =>
    shape(editor, (tr) => {
      const gone = linesIn(tr.doc).filter((l) => uids.includes(l.uid));
      if (!gone.length) return;
      const before = linesIn(tr.doc)
        .filter((l) => l.pos < gone[0].pos && !uids.includes(l.uid))
        .pop();
      for (const l of [...gone].reverse()) {
        const block = tr.doc.nodeAt(l.blockPos)!;
        const left = linesIn(tr.doc).filter((x) => x.blockPos === l.blockPos && !uids.includes(x.uid)).length;
        if (left === 0 && tr.doc.childCount > 1) tr.delete(l.blockPos, l.blockPos + block.nodeSize);
        else if (left > 0) tr.delete(l.pos, l.pos + tr.doc.nodeAt(l.pos)!.nodeSize);
      }
      if (before) {
        const at = linesIn(tr.doc).find((x) => x.uid === before.uid);
        if (at) tr.setSelection(TextSelection.create(tr.doc, at.pos + 1 + at.text.length));
      }
    });

  // A new line after `after` in its block, or a new block after it, with the caret at the start
  // of its words.
  const insert = (editor: Editor, after: Here, line: LineAttrs, text: string, block?: BlockAttrs) =>
    shape(editor, (tr) => {
      const lineEnd = after.pos + tr.doc.nodeAt(after.pos)!.nodeSize;
      if (!block) {
        tr.insert(lineEnd, editor.schema.nodeFromJSON(lineNode(line, text)));
        tr.setSelection(TextSelection.create(tr.doc, lineEnd + 1));
        return;
      }
      const own = editor.schema.nodeFromJSON(blockNode(block, [lineNode(line, text)]));
      const parent = tr.doc.nodeAt(after.blockPos)!;
      const end = after.blockPos + parent.nodeSize;
      if (after.index === after.count - 1) {
        tr.insert(end, own);
        tr.setSelection(TextSelection.create(tr.doc, end + 2));
        return;
      }
      // within a run said to camera: the block splits around the new one
      const rest: PMNode[] = [];
      parent.forEach((l, offset) => {
        if (after.blockPos + 1 + offset >= lineEnd) rest.push(l);
      });
      tr.delete(lineEnd, end - 1);
      const tail = editor.schema.nodes.scriptBlock.create({ ...parent.attrs, key: `${(parent.attrs as BlockAttrs).key}-rest` }, rest);
      tr.insert(lineEnd + 1, [own, tail]);
      tr.setSelection(TextSelection.create(tr.doc, lineEnd + 3));
    });

  // What the slash menu does with a pick, where the slash was typed.
  const pick = (editor: Editor, range: { from: number; to: number }, item: SlashItem) => {
    shape(editor, (tr) => {
      tr.delete(range.from, range.to);
    });
    const here = lineAt(editor.state);
    if (!here) return;
    if (item.kind === "ask") {
      // the prompt at the caret, on the line the slash was typed in (or the kept line before it)
      const about =
        here.id ||
        linesIn(editor.state.doc)
          .filter((l) => l.pos < here.pos && l.id)
          .pop()?.id;
      if (about && about !== here.id) {
        const kept = linesIn(editor.state.doc).find((l) => l.id === about)!;
        editor.commands.setTextSelection(kept.pos + 1 + kept.text.length);
      }
      if (about) window.setTimeout(() => openRef.current("line"), 0);
      return;
    }
    place(editor, item.kind);
  };

  // A block of `kind` where the caret is: a new line in a run said to camera, the person's own
  // empty block turned into it, or a new block after the line (in a run said to camera) or after
  // the picture's last line.
  const place = (editor: Editor, kind: LineKind) => {
    const here = lineAt(editor.state);
    if (!here) return;
    const camera = kind === "camera";
    const toCamera = !here.block.unit && (here.block.kind === "" || here.block.kind === "camera" || here.block.kind === "more");
    const blank = !here.id && !words(here.text);
    if (camera && toCamera) {
      if (blank) return;
      return insert(editor, here, { uid: fresh(), id: "", base: "", kind: "more", split: "" }, "");
    }
    if (blank && here.block.kind && here.count === 1) {
      // the person's own empty block becomes what they picked
      return shape(editor, (tr) => {
        tr.setNodeMarkup(here.blockPos, undefined, { ...here.block, kind });
        tr.setNodeMarkup(here.pos, undefined, { uid: here.uid, id: "", base: "", kind, split: "" });
      });
    }
    if (blank) cutLocal(editor, [here.uid]);
    const now = lineAt(editor.state) ?? here;
    // inside a picture's block the new one goes after its last line; in a run said to camera,
    // after the line the slash was typed on
    const anchor = toCamera
      ? now
      : linesIn(editor.state.doc)
          .filter((l) => l.blockPos === now.blockPos)
          .pop()!;
    insert(editor, anchor, { uid: fresh(), id: "", base: "", kind, split: "" }, "", { key: fresh(), unit: "", kind });
  };

  const editor = useEditor(
    {
      extensions: [
        Doc,
        Text,
        ScriptBlock,
        ScriptLine,
        Extension.create({
          name: "episodeScript",
          // before the editor's own keys: Enter, Backspace and Delete mean the script's here
          priority: 1000,
          addProseMirrorPlugins() {
            const editor = this.editor;
            return [
              guard(),
              marks(),
              hint(() => openRef.current()),
              Suggestion<SlashItem, SlashItem>({
                editor,
                char: "/",
                allowSpaces: false,
                items: ({ query }) => slashItems(query, on.current.pictures),
                command: ({ editor, range, props }) => pick(editor, range, props),
                render: () => ({
                  onStart: (p: SuggestionProps<SlashItem, SlashItem>) => setMenu({ items: p.items, at: 0, rect: p.clientRect?.() ?? null, choose: p.command }),
                  onUpdate: (p: SuggestionProps<SlashItem, SlashItem>) =>
                    setMenu((m) => ({ items: p.items, at: Math.min(m?.at ?? 0, Math.max(0, p.items.length - 1)), rect: p.clientRect?.() ?? null, choose: p.command })),
                  onExit: () => setMenu(null),
                  onKeyDown: ({ event }: SuggestionKeyDownProps) => {
                    const m = menuRef.current;
                    if (!m) return false;
                    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                      const step = event.key === "ArrowDown" ? 1 : -1;
                      setMenu({ ...m, at: (m.at + step + m.items.length) % Math.max(1, m.items.length) });
                      return true;
                    }
                    if (event.key === "Enter" || event.key === "Tab") {
                      const item = m.items[m.at];
                      if (item) m.choose(item);
                      return Boolean(item);
                    }
                    if (event.key === "Escape") {
                      setMenu(null);
                      return true;
                    }
                    return false;
                  },
                }),
              }),
            ];
          },
          addKeyboardShortcuts() {
            return {
              Enter: () => enter(this.editor),
              Backspace: () => backspace(this.editor),
              Delete: () => forward(this.editor),
              "Shift-Enter": () => true,
              "Mod-j": () => (openRef.current(), true),
              "Mod-z": () => revert(this.editor) || (on.current.onUndo(), true),
              "Mod-Shift-z": () => (on.current.onRedo(), true),
              "Mod-y": () => (on.current.onRedo(), true),
            };
          },
        }),
      ],
      content: layout(blocks, null),
      editable: !recording && !working,
      editorProps: {
        attributes: { class: "ep-script", "aria-label": "Script", spellcheck: "true" },
        // a paste is words for this line: its breaks become spaces
        handlePaste: (pmView, event) => {
          const text = event.clipboardData?.getData("text/plain");
          if (text === undefined) return false;
          pmView.dispatch(pmView.state.tr.insertText(text.replace(/\s*\n+\s*/g, " ")));
          return true;
        },
        handleDrop: () => true,
        // the markdown keys: "- " on a line with nothing else makes a list, three backticks code
        handleTextInput: (pmView, from, to, text) => {
          const editor = editorRef.current;
          const here = lineAt(pmView.state);
          if (!editor || !here || to !== from) return false;
          const typed = here.text.slice(0, from - here.pos - 1) + text;
          const kind = Object.entries(SHORTCUTS).find(([, keys]) => typed === keys && here.text.length === typed.length - text.length)?.[0];
          if (!kind) return false;
          setAttrs(editor, here.uid, {}, "");
          place(editor, kind as LineKind);
          return true;
        },
      },
      onSelectionUpdate: ({ editor }) => {
        const here = lineAt(editor.state);
        const was = caret.current;
        caret.current = here?.uid ?? "";
        const into = caret.current;
        if (was && was !== into) window.setTimeout(() => !editor.isDestroyed && leave(editor, was, into), 0);
        if (here?.id) on.current.onPick(here.id);
      },
      onFocus: () => setFocused(true),
      onUpdate: () => {
        // words are being typed: the pill steps aside until the typing stops
        setTyping(true);
        window.clearTimeout(quietTimer.current);
        quietTimer.current = window.setTimeout(() => setTyping(false), 900);
      },
      onBlur: ({ editor, event }) => {
        setFocused(false);
        // a click on the slash menu, or inside the editor's own chrome, is not leaving it
        if ((event.relatedTarget as HTMLElement | null)?.closest(".ep-slash")) return;
        const was = caret.current;
        caret.current = "";
        if (was) leave(editor, was, "");
      },
    },
    [],
  );

  editorRef.current = editor;

  // Enter: the next line of the block. In the middle of a line the words after the caret are
  // the new line's; at a line's start, or on a line with no words yet, nothing happens.
  function enter(editor: Editor): boolean {
    if (menuRef.current) return false;
    const here = lineAt(editor.state);
    const sel = editor.state.selection;
    if (!here || !sel.empty) return true;
    const offset = sel.$from.parentOffset;
    if (!words(here.text) || (offset === 0 && here.text.length > 0)) return true;
    const left = here.text.slice(0, offset).trimEnd();
    const right = here.text.slice(offset).trimStart();
    if (right) setAttrs(editor, here.uid, {}, left);
    const moved = linesIn(editor.state.doc).find((x) => x.uid === here.uid)!;
    insert(editor, moved, { uid: fresh(), id: "", base: "", kind: "more", split: right && here.id ? here.uid : "" }, right);
    return true;
  }

  // Backspace at a line's start joins it to the line before it in its block. An empty line the
  // person added goes; an empty line of the plan's is cut.
  function backspace(editor: Editor): boolean {
    const here = lineAt(editor.state);
    const sel = editor.state.selection;
    if (!here || !sel.empty || sel.$from.parentOffset > 0) return false;
    const all = linesIn(editor.state.doc);
    const k = all.findIndex((l) => l.uid === here.uid);
    const prev = here.index > 0 ? all[k - 1] : undefined;
    if (!prev) {
      if (!here.id && !words(here.text)) cutLocal(editor, [here.uid]);
      return true;
    }
    if (!words(here.text)) {
      cutLocal(editor, [here.uid]);
      if (here.id) send(async () => land(await api.cutLines(on.current.view, [here.id])));
      return true;
    }
    if (here.block.unit && here.index === 0) return true;
    join(editor, prev, here);
    return true;
  }

  // Delete at a line's end joins the next line of its block to it.
  function forward(editor: Editor): boolean {
    const here = lineAt(editor.state);
    const sel = editor.state.selection;
    if (!here || !sel.empty || sel.$from.parentOffset < here.text.length) return false;
    if (here.index >= here.count - 1) return true;
    const all = linesIn(editor.state.doc);
    const next = all[all.findIndex((l) => l.uid === here.uid) + 1];
    join(editor, here, next);
    return true;
  }

  function join(editor: Editor, first: Here, second: Here) {
    const joined = [first.text.trimEnd(), second.text.trimStart()].filter(Boolean).join(" ");
    const caretAt = first.text.trimEnd().length;
    // the line that stays is the plan's where it can be: the first, unless only the second is kept
    const keep = !first.id && second.id ? second : first;
    const drop = keep === first ? second : first;
    shape(editor, (tr) => {
      tr.delete(drop.pos, drop.pos + tr.doc.nodeAt(drop.pos)!.nodeSize);
      const at = linesIn(tr.doc).find((x) => x.uid === keep.uid)!;
      tr.replaceWith(at.pos + 1, at.pos + 1 + tr.doc.nodeAt(at.pos)!.content.size, editor.schema.text(joined));
      tr.setSelection(TextSelection.create(tr.doc, at.pos + 1 + caretAt));
    });
    if (first.id && second.id) {
      // one change: the second goes, and the first has the words of both
      send(async () => {
        const v = await api.cutLines(on.current.view, [second.id], true, joined);
        setAttrs(editor, first.uid, { base: joined });
        land(v);
      });
    }
  }

  // Cmd-Z puts back the words of a line the caret is in, before they are kept; past that, the
  // studio takes back the last change, as everywhere else.
  function revert(editor: Editor): boolean {
    const here = lineAt(editor.state);
    if (here?.id && words(here.text) !== words(here.base)) {
      setAttrs(editor, here.uid, {}, here.base);
      return true;
    }
    return false;
  }

  // The plan as it stands, laid over the document whenever it changes.
  useEffect(() => {
    if (!editor || editor.isDestroyed) return;
    const next = layout(blocks, editor.state.doc);
    if (shapeOf(next) === shapeOf(editor.getJSON())) return;
    const here = lineAt(editor.state);
    const offset = editor.state.selection.$from.parentOffset;
    shape(editor, (tr) => {
      const doc = editor.schema.nodeFromJSON(next);
      tr.replaceWith(0, tr.doc.content.size, doc.content);
      const at = here && linesIn(tr.doc).find((l) => l.uid === here.uid);
      if (at) tr.setSelection(TextSelection.create(tr.doc, at.pos + 1 + Math.min(offset, at.text.length)));
    });
  }, [editor, blocks]);

  useEffect(() => {
    editor?.setEditable(!recording && !working);
  }, [editor, recording, working]);

  // the pill is there when the caret is placed in a line, and not while words are typed or a
  // menu or the prompt is open
  const show = focused && !typing && !menu && !asking && !recording && !working;
  useEffect(() => {
    if (!editor || editor.isDestroyed) return;
    editor.view.dispatch(editor.state.tr.setMeta(HINT, { show }));
  }, [editor, show]);

  // What the last change did is drawn into the words while its marks are on; the words it
  // brought in are written in once, as it lands.
  const was = view.last_change?.was;
  const landedAt = view.last_change?.at;
  const [landed, setLanded] = useState(false);
  useEffect(() => {
    if (!landedAt) return;
    setLanded(true);
    const t = window.setTimeout(() => setLanded(false), 1200);
    return () => window.clearTimeout(t);
  }, [landedAt]);
  useEffect(() => {
    if (!editor || editor.isDestroyed) return;
    editor.view.dispatch(editor.state.tr.setMeta(MARKS, marked ? (was ?? {}) : {}));
  }, [editor, marked, was]);

  // Leaving the chapter keeps what the caret was on.
  useEffect(
    () => () => {
      if (editor && !editor.isDestroyed && caret.current) leave(editor, caret.current, "");
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [editor],
  );

  useImperativeHandle(ref, () => ({
    askAt: (frame, scope) => {
      if (!editor) return;
      const l = linesIn(editor.state.doc).find((x) => x.id === frame);
      if (!l) return;
      // the caret goes to the line's end without the editor taking the focus, which it would do a
      // frame later: the prompt's field takes it
      editor.commands.setTextSelection(l.pos + 1 + l.text.length);
      openRef.current(scope);
    },
    focusLine: (frame, slash = false) => {
      if (!editor) return;
      const l = linesIn(editor.state.doc).find((x) => x.id === frame);
      if (!l) return;
      editor
        .chain()
        .focus()
        .setTextSelection(l.pos + 1 + l.text.length)
        .run();
      if (slash) editor.view.dispatch(editor.state.tr.insertText(l.text && !l.text.endsWith(" ") ? " /" : "/"));
    },
  }));

  const changed = useMemo(() => new Set([...(view.last_change?.lines ?? []), ...(view.last_change?.added ?? [])]), [view.last_change]);
  const cuts = useMemo(() => {
    const by = new Map<string, string[]>();
    for (const c of view.last_change?.cut ?? []) {
      if (c.chapter !== chapter.id) continue;
      const after = lines.some((l) => l.id === c.after) ? c.after : "";
      by.set(after, [...(by.get(after) ?? []), c.says]);
    }
    return by;
  }, [view.last_change, chapter.id, lines]);
  const byId = useMemo(() => new Map(lines.map((l) => [l.id, l])), [lines]);

  const ctx: Ctx = {
    view,
    chapter,
    byId,
    lines,
    current,
    recording,
    said,
    solo,
    take,
    marked,
    was: was ?? {},
    changed,
    cuts,
    run,
    busy,
    onPick,
    onOpen,
    onReword,
    onRecordLine,
    asking,
    onAskHere: (text, scope) => {
      if (!asking) return;
      onAskLine(asking.line, asking.words, text, scope);
      setAsking(null);
    },
    onCloseAsk: () => {
      setAsking(null);
      editor?.commands.focus();
    },
    writer: WRITERS[view.settings.writer] ?? "the writer",
    mark: view.options.writers.find((w) => w.id === view.settings.writer && w.local) ? view.settings.writer : undefined,
    working,
    onLine: view.stage.asked?.scope === "line" ? (view.stage.asked.target ?? "") : "",
    onPicture: view.stage.asked?.scope === "picture" ? (view.stage.asked.target ?? "") : "",
    onStop: () => void api.stopEpisode(view.id).catch(() => undefined),
    onCutBlock: (key) => {
      if (!editor) return;
      const mine = linesIn(editor.state.doc).filter((l) => l.block.key === key);
      const kept = mine.filter((l) => l.id).map((l) => l.id);
      cutLocal(
        editor,
        mine.map((l) => l.uid),
      );
      if (kept.length) send(async () => land(await api.cutLines(on.current.view, kept)));
    },
  };

  return (
    <ScriptCtx.Provider value={ctx}>
      {marked && cuts.has("") && (
        <div className="ep-block-lines">
          {cuts.get("")!.map((says, n) => (
            <div key={n} className="ep-line-cut">
              <del>{says}</del>
              <small>Cut</small>
            </div>
          ))}
        </div>
      )}
      <EditorContent editor={editor} className={landed ? "ep-script-wrap ep-landed" : "ep-script-wrap"} />
      {menu && <SlashMenu state={menu} onAt={(at) => setMenu({ ...menu, at })} />}
    </ScriptCtx.Provider>
  );
}
