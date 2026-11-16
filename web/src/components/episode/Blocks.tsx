// A chapter's script as it reads: a block for each picture with the lines it is shown on, and a
// block for each run of lines said to camera between them. The chapter's page and the film's
// notebook both read a chapter in these blocks, under the same heads.
import { Code, Image as ImageIcon, List, Presentation, Tags, User, Workflow, type LucideIcon } from "lucide-react";
import type { EpisodeFrame, EpisodeUnit, EpisodeView } from "../../api";
import { PICTURES, pictureState, pictureWords, unitOf } from "../../episode";

export type Block = { key: string; unit?: EpisodeUnit; lines: EpisodeFrame[] };

export function blocksOf(view: EpisodeView, lines: EpisodeFrame[]): Block[] {
  const out: Block[] = [];
  for (const l of lines) {
    const mine = unitOf(view, l.id);
    const last = out[out.length - 1];
    if (last && (mine ? last.unit?.id === mine.id : !last.unit)) last.lines.push(l);
    else out.push({ key: l.id, unit: mine, lines: [l] });
  }
  return out;
}

// The icon each kind of picture is known by.
const KIND_ICONS: Record<string, LucideIcon> = { diagram: Workflow, list: List, "typeset-code": Code, chips: Tags, illustration: ImageIcon, slide: Presentation };

const toCamera = (block: Block) => !block.unit && block.lines.every((l) => l.presence === "person");

export function blockName(block: Block): string {
  const u = block.unit;
  if (u) return u.kind === "undesigned" ? "A picture" : (PICTURES[u.kind_of_picture] ?? "Picture");
  return toCamera(block) ? "To camera" : "Picture";
}

// The icon a block is known by: its picture's kind, or a person for lines said to camera.
export function KindIcon({ block }: { block: Block }) {
  const u = block.unit;
  const Icon = (u ? KIND_ICONS[u.kind_of_picture] : toCamera(block) ? User : undefined) ?? ImageIcon;
  return <Icon aria-hidden="true" />;
}

// The block's kind, and for a picture how it is made and where it stands.
export function BlockHead({ block, view }: { block: Block; view?: EpisodeView }) {
  const u = block.unit;
  return (
    <header className="ep-block-head" data-status={u ? pictureState(u, view) : "camera"}>
      <KindIcon block={block} />
      <b>{blockName(block)}</b>
      {u && (
        <span>
          {u.level === "rich" ? "Rich" : "Simple"} · {pictureWords(u, view)}
        </span>
      )}
    </header>
  );
}
