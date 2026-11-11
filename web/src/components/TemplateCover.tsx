// A template's cover: what it makes, drawn in the brand the channel wears. Each piece stands at
// its own shape (a 16:9 teaser, a 9:16 short, cards at their sizes), so a template shows what the
// person gets rather than how it is made, the way Figma's and Miro's template covers do. The
// biggest piece leads; up to three more stand around it.
import { Play, Repeat2 } from "lucide-react";
import type { CSSProperties, ReactNode } from "react";
import type { BrandPackView, Slot, Template } from "../api";
import { contrast, onColour, pick, rolesOf } from "../kit";

export type Look = { name: string; ground: string; ink: string; accent: string; muted: string; series: string[]; mark?: string; reversed?: string };

// Which piece leads a cover: a film before a deck, a deck before a card.
const LEADS = ["video", "captions", "deck", "genimg", "still", "chart", "thumbs", "gif"];
// Where the pieces stand on a 160×100 cover, the lead first; each is kept inside the edge.
const W = 160;
const H = 100;
const SPOTS: [number, number][] = [
  [62, 50],
  [128, 26],
  [130, 75],
  [36, 82],
];
const GAP = 0.08;

export function lookOf(pack: BrandPackView | null): Look {
  if (!pack) return { name: "", ground: "#f6f1e7", ink: "#14161a", accent: "#2f8f5b", muted: "#6b6f68", series: ["#2f8f5b", "#8fb3c9", "#d8c39a"] };
  const roles = rolesOf(pack);
  const ground = roles.ground || "#ffffff";
  const ink = roles.ink || "#111111";
  const accent = roles.accent || ink;
  // The brand's own colours that show on its ground, for covers and sets to tell apart.
  const series = [accent, ...pack.series, ...pack.palette.map((c) => c.value)].filter((c, i, all) => all.indexOf(c) === i && contrast(c, ground) > 1.3);
  return {
    name: pack.name,
    ground,
    ink,
    accent,
    muted: roles.muted || ink,
    series: series.length ? series : [accent],
    mark: (pick(pack.logos, "mark", false) ?? pick(pack.logos, "lockup", false))?.url,
    reversed: (pick(pack.logos, "mark", true) ?? pick(pack.logos, "lockup", true))?.url,
  };
}

const ratioOf = (shape: string) => {
  const [w, h] = shape.split(":").map(Number);
  return w > 0 && h > 0 ? w / h : 16 / 9;
};
const rank = (slot: Slot) => (LEADS.includes(slot.kind) ? LEADS.indexOf(slot.kind) : LEADS.length);

export function TemplateCover({ template, look, tint }: { template: Template; look: Look; tint: number }) {
  const made = template.slots.filter((s) => !s.gate);
  const lead = [...made].sort((a, b) => rank(a) - rank(b))[0];
  const pieces = lead ? [lead, ...made.filter((s) => s !== lead)].slice(0, SPOTS.length) : [];
  const backdrop = look.series[tint % look.series.length];
  return (
    <span className="cover" aria-hidden="true" style={{ background: `color-mix(in srgb, ${backdrop} 26%, ${look.ground})` }}>
      {pieces.map((slot, i) => (
        <Piece key={slot.key} slot={slot} look={look} spot={SPOTS[i]} share={i === 0 ? 0.3 : 0.1} lead={i === 0} />
      ))}
    </span>
  );
}

// One slot on its own, centred on a tint of the brand: what a template's sheet shows on each of
// its cards. A storyboard shows as three of its beats.
export function SlotArt({ slot, look, tint }: { slot: Slot; look: Look; tint: number }) {
  const shown = slot.kind === "board" ? { ...slot, shape: ["16:9", "16:9", "16:9"] } : slot;
  const backdrop = look.series[tint % look.series.length];
  return (
    <span className="cover slot-art" aria-hidden="true" style={{ background: `color-mix(in srgb, ${backdrop} 22%, ${look.ground})` }}>
      <Piece slot={shown} look={look} spot={[W / 2, H / 2]} share={0.42} lead />
    </span>
  );
}

// One slot's pieces side by side at their shapes (a set of sizes, two thumbnails, a carousel's
// slides), sized to its share of the cover and placed at its spot.
function Piece({ slot, look, spot, share, lead }: { slot: Slot; look: Look; spot: [number, number]; share: number; lead: boolean }) {
  // A server older than the web app sends no shapes: one 16:9 piece then.
  const shapes = slot.shape?.length ? slot.shape : ["16:9"];
  const across = shapes.reduce((sum, s) => sum + ratioOf(s), 0) + GAP * (shapes.length - 1);
  const fit = Math.min(1, (W - 8) / Math.sqrt(share * W * H * across), (H - 8) / Math.sqrt((share * W * H) / across));
  const w = Math.sqrt(share * W * H * across) * fit;
  const h = Math.sqrt((share * W * H) / across) * fit;
  const left = Math.max(4, Math.min(W - 4 - w, spot[0] - w / 2));
  const top = Math.max(4, Math.min(H - 4 - h, spot[1] - h / 2));
  return (
    <span
      className="piece"
      style={{ left: `${(left / W) * 100}%`, top: `${(top / H) * 100}%`, width: `${(w / W) * 100}%`, height: `${(h / H) * 100}%`, columnGap: `${(GAP / across) * 100}%` }}
    >
      {shapes.map((shape, n) => (
        <Sheet key={n} slot={slot} ratio={ratioOf(shape)} look={look} n={n} lead={lead} width={(ratioOf(shape) / across) * 100} />
      ))}
    </span>
  );
}

// One piece as its kind looks: a film with its play button, a phone-shaped short, a captioned
// clip, an A/B thumbnail, a GIF loop, a storyboard's beat, a card, a page, a chart, a slide or
// hero art.
function Sheet({ slot, ratio, look, n, lead, width }: { slot: Slot; ratio: number; look: Look; n: number; lead: boolean; width: number }) {
  const display: CSSProperties = { fontFamily: "var(--kit-display, var(--font))" };
  const dark = n % 2 === 1;
  const paper = { background: look.ground, color: look.ink };
  const ink = { background: look.ink, color: look.ground };
  const colour = look.series[(n + 1) % look.series.length];
  const lines = (fg: string, widths: number[]) => widths.map((x, i) => <i key={i} className="sheet-line" style={{ width: `${x}%`, background: fg }} />);
  let face: CSSProperties = dark ? ink : paper;
  let body: ReactNode;

  if (slot.kind === "video" && ratio < 1) {
    face = ink;
    body = (
      <>
        {look.reversed && <img className="sheet-mark" src={look.reversed} alt="" />}
        <span className="sheet-copy">{lines(look.ground, [78, 54])}</span>
        <PlayButton look={look} />
      </>
    );
  } else if (slot.kind === "video") {
    face = paper;
    body = (
      <>
        {look.mark && <img className="sheet-mark" src={look.mark} alt="" />}
        <span className="sheet-copy">
          {lead && look.name ? <strong style={display}>{look.name}</strong> : lines(look.ink, [70])}
          <i className="sheet-rule" style={{ background: look.accent }} />
        </span>
        <PlayButton look={look} />
      </>
    );
  } else if (slot.kind === "captions") {
    face = { background: `color-mix(in srgb, ${look.ink} 86%, ${look.accent})`, color: look.ground };
    body = (
      <>
        <i className="sheet-head" style={{ background: look.muted }} />
        <i className="sheet-shoulders" style={{ background: look.muted }} />
        <span className="sheet-caption" style={{ background: look.ground }}>
          {lines(look.ink, [72])}
        </span>
      </>
    );
  } else if (slot.kind === "thumbs") {
    face = n === 0 ? { background: look.accent, color: onColour(look.accent) } : ink;
    body = (
      <>
        <b className="sheet-badge" style={{ background: face.color as string, color: face.background as string }}>
          {n === 0 ? "A" : "B"}
        </b>
        <span className="sheet-copy">{lines(face.color as string, [74, 46])}</span>
      </>
    );
  } else if (slot.kind === "gif") {
    face = { background: colour, color: onColour(colour) };
    body = (
      <span className="sheet-loop" style={display}>
        <Repeat2 />
        GIF
      </span>
    );
  } else if (slot.kind === "chart" && ratio <= 1.2) {
    face = paper;
    body = (
      <span className="sheet-stat">
        <strong style={{ ...display, color: look.accent }}>42%</strong>
        {lines(look.muted, [64])}
      </span>
    );
  } else if (slot.kind === "chart" || slot.kind === "deck") {
    face = paper;
    body = (
      <>
        {slot.kind === "deck" && <span className="sheet-title">{lines(look.ink, [46])}</span>}
        <span className="sheet-bars" style={{ borderColor: look.muted }}>
          {[0.42, 0.7, 0.55, 0.9].map((x, i) => (
            <i key={i} style={{ height: `${x * 100}%`, background: look.series[i % look.series.length] }} />
          ))}
        </span>
      </>
    );
  } else if (slot.kind === "board") {
    // A beat: its number, and a line of what it shows over the brand's rule.
    face = paper;
    body = (
      <>
        <b className="sheet-badge" style={{ background: look.ink, color: look.ground }}>
          {n + 1}
        </b>
        <span className="sheet-copy">
          {lines(look.muted, [78])}
          <i className="sheet-rule" style={{ background: look.accent }} />
        </span>
      </>
    );
  } else if (slot.kind === "genimg") {
    face = { background: `color-mix(in srgb, ${colour} 30%, ${look.ground})` };
    body = look.series.slice(0, 3).map((c, i) => <i key={i} className={`sheet-blob b${i}`} style={{ background: c }} />);
  } else if (ratio < 0.8) {
    // A page: a band in the brand's colour over lines of text.
    face = paper;
    body = (
      <>
        <i className="sheet-band" style={{ background: look.accent }} />
        <span className="sheet-text">{lines(look.muted, [86, 92, 74, 88, 60])}</span>
      </>
    );
  } else {
    body = (
      <>
        {(dark ? look.reversed : look.mark) && <img className="sheet-mark" src={dark ? look.reversed : look.mark} alt="" />}
        <span className="sheet-copy">
          {lines(face.color as string, [80, 56])}
          <i className="sheet-pill" style={{ background: look.accent }} />
        </span>
      </>
    );
  }
  return (
    <span className="sheet" style={{ ...face, width: `${width}%` }}>
      {body}
    </span>
  );
}

function PlayButton({ look }: { look: Look }) {
  return (
    <span className="sheet-play" style={{ background: look.accent, color: onColour(look.accent) }}>
      <Play />
    </span>
  );
}
