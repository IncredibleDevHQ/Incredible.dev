// Small pictures for the tiles that pick a line's picture: one for each kind of picture, and one
// for each way a picture comes in. They stand for the kind, not for this film's picture, drawn on
// the same paper, ink and green as the layout thumbnails so they read the same in either theme.
// A way in shows the move half done; pointed at or focused, it plays the move as the film does it
// (`episode.film`): the same distance, the same easing, the same seconds.

const PAPER = "#f3efe6";
const INK = "#2f3833";
const SOFT = "#cfe3d6";
const GREEN = "#3f9a66";
const DEEP = "#2b6b48";
const LINE = "#c4bdae";
const AMBER = "#e2b052";
const DARK = "#1f2622";

export function KindArt({ kind }: { kind: string }) {
  return (
    <svg className="ep-kind-art" viewBox="0 0 160 90" role="presentation" focusable="false">
      <rect width="160" height="90" fill={PAPER} />
      {ART[kind] ?? ART.slide}
    </svg>
  );
}

const arrow = (x: number, y: number) => <path d={`M${x} ${y - 4} L${x + 6} ${y} L${x} ${y + 4} Z`} fill={INK} />;

const ART: Record<string, React.ReactNode> = {
  // boxes and arrows that build with the voice: the box being said is lit
  diagram: (
    <>
      <path d="M28 33 C28 12 132 12 132 33" fill="none" stroke={LINE} strokeWidth="2" strokeDasharray="4 4" />
      <path d="M126 29 L132 35 L138 29" fill="none" stroke={LINE} strokeWidth="2" />
      <rect x="10" y="35" width="36" height="24" rx="5" fill={SOFT} stroke={INK} strokeWidth="1.5" />
      <rect x="62" y="35" width="36" height="24" rx="5" fill={GREEN} />
      <rect x="114" y="35" width="36" height="24" rx="5" fill="#ffffff" stroke={LINE} strokeWidth="1.5" />
      <path d="M47 47 H54" stroke={INK} strokeWidth="2" />
      {arrow(54, 47)}
      <path d="M99 47 H106" stroke={INK} strokeWidth="2" />
      {arrow(106, 47)}
      <rect x="17" y="44" width="22" height="5" rx="2.5" fill={INK} opacity="0.55" />
      <rect x="69" y="44" width="22" height="5" rx="2.5" fill="#ffffff" />
      <rect x="121" y="44" width="22" height="5" rx="2.5" fill={LINE} />
      <rect x="40" y="70" width="80" height="6" rx="3" fill={LINE} />
    </>
  ),
  // bullets that build, one per phrase: two in, the third still to come
  list: (
    <>
      <circle cx="26" cy="27" r="5" fill={GREEN} />
      <rect x="40" y="23" width="92" height="8" rx="4" fill={INK} />
      <circle cx="26" cy="46" r="5" fill={GREEN} />
      <rect x="40" y="42" width="72" height="8" rx="4" fill={INK} />
      <circle cx="26" cy="65" r="5" fill={LINE} />
      <rect x="40" y="61" width="84" height="8" rx="4" fill={LINE} />
    </>
  ),
  // code set as a card, with the line being read lit
  "typeset-code": (
    <>
      <rect x="14" y="10" width="132" height="70" rx="7" fill={DARK} />
      <circle cx="25" cy="20" r="2.5" fill="#e0715c" />
      <circle cx="33" cy="20" r="2.5" fill={AMBER} />
      <circle cx="41" cy="20" r="2.5" fill="#6cc48d" />
      <rect x="24" y="31" width="22" height="5" rx="2.5" fill="#7fd1a0" />
      <rect x="50" y="31" width="48" height="5" rx="2.5" fill="#d9d4c7" />
      <rect x="14" y="40" width="132" height="12" fill="#7fd1a0" opacity="0.18" />
      <rect x="32" y="43.5" width="30" height="5" rx="2.5" fill={AMBER} />
      <rect x="66" y="43.5" width="44" height="5" rx="2.5" fill="#d9d4c7" />
      <rect x="32" y="57" width="58" height="5" rx="2.5" fill="#8fb3d9" />
      <rect x="24" y="68" width="18" height="5" rx="2.5" fill="#7fd1a0" />
    </>
  ),
  // short labels in boxes, one per item
  chips: (
    <>
      <rect x="12" y="24" width="42" height="18" rx="9" fill="#ffffff" stroke={INK} strokeWidth="1.5" />
      <rect x="21" y="31" width="24" height="4" rx="2" fill={INK} />
      <rect x="60" y="24" width="52" height="18" rx="9" fill={GREEN} />
      <rect x="70" y="31" width="32" height="4" rx="2" fill="#ffffff" />
      <rect x="118" y="24" width="30" height="18" rx="9" fill="#ffffff" stroke={INK} strokeWidth="1.5" />
      <rect x="126" y="31" width="14" height="4" rx="2" fill={INK} />
      <rect x="32" y="50" width="48" height="18" rx="9" fill="#ffffff" stroke={LINE} strokeWidth="1.5" strokeDasharray="3 3" />
      <rect x="42" y="57" width="28" height="4" rx="2" fill={LINE} />
      <rect x="86" y="50" width="42" height="18" rx="9" fill="#ffffff" stroke={LINE} strokeWidth="1.5" strokeDasharray="3 3" />
      <rect x="95" y="57" width="24" height="4" rx="2" fill={LINE} />
    </>
  ),
  // a picture drawn for one idea: a scene, here a card carried from one place to another
  illustration: (
    <>
      <circle cx="132" cy="22" r="9" fill={AMBER} />
      <path d="M4 76 Q 80 62 156 76 L156 90 L4 90 Z" fill={SOFT} />
      <rect x="18" y="42" width="34" height="30" rx="5" fill="#ffffff" stroke={INK} strokeWidth="1.5" />
      <rect x="24" y="49" width="10" height="8" rx="1.5" fill={SOFT} stroke={INK} strokeWidth="1" />
      <rect x="37" y="49" width="10" height="8" rx="1.5" fill={SOFT} stroke={INK} strokeWidth="1" />
      <rect x="110" y="36" width="26" height="36" rx="4" fill={INK} />
      <rect x="115" y="43" width="16" height="3" rx="1.5" fill={SOFT} />
      <rect x="115" y="50" width="16" height="3" rx="1.5" fill={SOFT} />
      <rect x="115" y="57" width="16" height="3" rx="1.5" fill={GREEN} />
      <path d="M108 46 Q 82 14 56 42" fill="none" stroke={DEEP} strokeWidth="1.5" strokeDasharray="3 3" />
      <g transform="rotate(-10 79 30)">
        <rect x="68" y="23" width="22" height="15" rx="2.5" fill={GREEN} />
        <rect x="72" y="28" width="14" height="2.5" rx="1.25" fill="#ffffff" />
        <rect x="72" y="32" width="9" height="2.5" rx="1.25" fill="#ffffff" />
      </g>
    </>
  ),
  // a heading, a few lines and a picture
  slide: (
    <>
      <rect x="14" y="16" width="66" height="10" rx="5" fill={INK} />
      <rect x="14" y="35" width="62" height="5" rx="2.5" fill={LINE} />
      <rect x="14" y="45" width="54" height="5" rx="2.5" fill={LINE} />
      <rect x="14" y="55" width="58" height="5" rx="2.5" fill={LINE} />
      <rect x="92" y="14" width="56" height="62" rx="6" fill={SOFT} />
      <path d="M96 70 L112 50 L123 61 L131 53 L144 70 Z" fill={GREEN} />
      <circle cx="134" cy="28" r="5.5" fill={AMBER} />
    </>
  ),
};

// The picture before (a page of lines) and this picture (a green one), with the move between them.
export function MoveArt({ move }: { move: string }) {
  return (
    <span className="ep-move" data-move={move}>
      <span className="ep-move-a">
        <i />
        <i />
        <i />
      </span>
      <span className="ep-move-b">
        <i />
        <i />
      </span>
      {move === "cut" && <span className="ep-move-seam" />}
    </span>
  );
}
