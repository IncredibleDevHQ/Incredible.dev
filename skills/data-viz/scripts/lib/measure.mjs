// measure.mjs: text widths without a browser, for layout decisions made in code (label room, wrapping,
// whether a big number fits). An estimate per glyph class, close for grotesque and serif text faces and
// exact for monospace; ECharts' server-side renderer uses it too (setPlatformAPI), so axis room and
// label placement agree with what the rasteriser draws.

const NARROW = new Set([..."il.,:;'|!ijtfr()[]{}  "]);
const WIDE = new Set([..."mwMW@%"]);

export function textWidth(text, fontSize, { mono = false, weight = 400 } = {}) {
  const chars = [...String(text ?? "")];
  if (mono) return chars.length * fontSize * 0.6;
  let em = 0;
  for (const ch of chars) {
    // zrender takes a line's height from the width of a CJK glyph, so wide glyphs are a full em.
    if (ch.codePointAt(0) >= 0x2e80) em += 1;
    else if (NARROW.has(ch)) em += 0.3;
    else if (WIDE.has(ch)) em += 0.86;
    else if (ch >= "A" && ch <= "Z") em += 0.68;
    else if (ch >= "0" && ch <= "9") em += 0.6;
    else em += 0.55;
  }
  return em * fontSize * (weight >= 600 ? 1.05 : 1);
}

/** Parse a CSS font shorthand the way ECharts builds it ("600 20px 'Inter', sans-serif"). */
export function measureFont(text, font) {
  const size = Number(/(\d+(?:\.\d+)?)px/.exec(font || "")?.[1] || 12);
  const weight = Number(/\b([1-9]00)\b/.exec(font || "")?.[1] || (/\bbold\b/.test(font || "") ? 700 : 400));
  const mono = /mono/i.test(font || "");
  return { width: textWidth(text, size, { mono, weight }) };
}

/**
 * Wrap into at most `maxLines` lines no wider than `maxWidth`, or null when it cannot fit. Two lines
 * are balanced (the break that makes the longer line shortest), so no word is left alone.
 */
export function wrap(text, fontSize, maxWidth, { maxLines = 2, weight = 400 } = {}) {
  const words = String(text).split(/\s+/).filter(Boolean);
  const width = (s) => textWidth(s, fontSize, { weight });
  if (width(words.join(" ")) <= maxWidth) return [words.join(" ")];
  if (maxLines === 2) {
    let best = null;
    for (let i = 1; i < words.length; i++) {
      const pair = [words.slice(0, i).join(" "), words.slice(i).join(" ")];
      const widest = Math.max(...pair.map(width));
      if (widest <= maxWidth && (!best || widest < best.widest)) best = { pair, widest };
    }
    return best ? best.pair : null;
  }
  const lines = [];
  let line = "";
  for (const word of words) {
    const next = line ? `${line} ${word}` : word;
    if (line && width(next) > maxWidth) {
      lines.push(line);
      line = word;
    } else line = next;
  }
  if (line) lines.push(line);
  return lines.length <= maxLines ? lines : null;
}
