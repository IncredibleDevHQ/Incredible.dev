// The frame for one line, drawn on a canvas the way the film lays it out: the ground, the
// picture's box and the person's window where the look's layout puts them, in the same table
// the film is rendered from. The picture is its posed still, or before it is made the plan's
// words for it; the person is the take at that line, or a stand-in before there is one. The
// canvas is as wide as its place, at the screen's own pixel density, and draws again when a
// still or the take's frame arrives.
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { EpisodeFrame, EpisodeTake, EpisodeUnit, EpisodeView } from "../../api";
import { clockLine, spotOf } from "../../episode";

const GROUND = "#f3efe6";
const PAPER = "#ffffff";
const WINDOW = "#d9d3c5";
const FIGURE = "rgba(91, 102, 95, 0.55)";
const INK = "#5b665f";

// Stills, loaded once each.
const stills = new Map<string, HTMLImageElement>();
function still(url: string, ready: () => void): HTMLImageElement {
  let img = stills.get(url);
  if (!img) {
    img = new Image();
    img.decoding = "async";
    img.src = url;
    stills.set(url, img);
  }
  if (!img.complete) img.addEventListener("load", ready, { once: true });
  return img;
}

// A take's frame at a moment: one muted video per take, sought to the moment the line starts.
const reels = new Map<string, HTMLVideoElement>();
function reel(url: string, at: number, ready: () => void): HTMLVideoElement {
  let video = reels.get(url);
  if (!video) {
    video = document.createElement("video");
    video.muted = true;
    video.playsInline = true;
    video.preload = "auto";
    video.src = url;
    reels.set(url, video);
  }
  const v = video;
  const seek = () => {
    if (Math.abs(v.currentTime - at) > 0.04) {
      v.addEventListener("seeked", ready, { once: true });
      v.currentTime = Math.max(0, at);
    } else if (v.readyState < 2) v.addEventListener("loadeddata", ready, { once: true });
  };
  if (v.readyState >= 1) seek();
  else v.addEventListener("loadedmetadata", seek, { once: true });
  return v;
}

function rounded(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  const radius = Math.max(0, Math.min(r, w / 2, h / 2));
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, radius);
}

// Drawn whole inside its box, as a picture is.
function contain(ctx: CanvasRenderingContext2D, src: CanvasImageSource, iw: number, ih: number, x: number, y: number, w: number, h: number) {
  const s = Math.min(w / iw, h / ih);
  ctx.drawImage(src, x + (w - iw * s) / 2, y + (h - ih * s) / 2, iw * s, ih * s);
}

// Filling its box, as the person's window is.
function cover(ctx: CanvasRenderingContext2D, src: CanvasImageSource, iw: number, ih: number, x: number, y: number, w: number, h: number, zoom = 1) {
  const s = Math.max(w / iw, h / ih) * zoom;
  ctx.drawImage(src, x + (w - iw * s) / 2, y + (h - ih * s) / 2, iw * s, ih * s);
}

// Where the person will be, until there is a take.
function standIn(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number) {
  ctx.fillStyle = FIGURE;
  const r = w * 0.13;
  ctx.beginPath();
  ctx.arc(x + w / 2, y + h * 0.24 + r, r, 0, Math.PI * 2);
  ctx.fill();
  const sw = w * 0.62;
  const sh = h * 0.46;
  ctx.beginPath();
  ctx.roundRect(x + (w - sw) / 2, y + h * 1.08 - sh, sw, sh, [Math.min(sw / 2, sh), Math.min(sw / 2, sh), 0, 0]);
  ctx.fill();
}

// Before a picture is made: what the plan says it shows, set in its box, at a size that can be
// read however small the canvas is.
function sketch(ctx: CanvasRenderingContext2D, words: string, x: number, y: number, w: number, h: number, least: number) {
  ctx.save();
  ctx.strokeStyle = "#f1eee6";
  ctx.lineWidth = least * 0.9;
  for (let d = -h; d < w; d += least * 2.2) {
    ctx.beginPath();
    ctx.moveTo(x + d, y + h);
    ctx.lineTo(x + d + h, y);
    ctx.stroke();
  }
  ctx.fillStyle = INK;
  ctx.font = `500 ${least}px Inter, system-ui, sans-serif`;
  ctx.textBaseline = "top";
  const pad = Math.max(w * 0.06, least);
  const room = w - pad * 2;
  const lines: string[] = [];
  let now = "";
  for (const word of words.split(/\s+/).filter(Boolean)) {
    const next = now ? `${now} ${word}` : word;
    if (ctx.measureText(next).width <= room || !now) now = next;
    else {
      lines.push(now);
      now = word;
    }
  }
  if (now) lines.push(now);
  const most = Math.max(1, Math.floor((h - pad * 2) / (least * 1.35)));
  const shown = lines.slice(0, most);
  if (lines.length > most) shown[most - 1] = `${shown[most - 1].replace(/\s+\S*$/, "")}…`;
  const top = y + (h - shown.length * least * 1.35) / 2;
  shown.forEach((line, i) => ctx.fillText(line, x + pad, top + i * least * 1.35));
  ctx.restore();
}

export function FrameCanvas({
  view,
  frame,
  unit,
  take,
  label,
  takeless,
}: {
  view: EpisodeView;
  frame: EpisodeFrame;
  unit?: EpisodeUnit;
  take?: EpisodeTake;
  label: string;
  // a small frame among many draws the stand-in, so they do not all seek one take's video
  takeless?: boolean;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [width, setWidth] = useState(0);
  // bumps when a still or the take's frame arrives, so the frame is drawn again with it
  const [arrived, setArrived] = useState(0);
  useLayoutEffect(() => {
    const el = canvas.current;
    if (!el) return;
    setWidth(el.getBoundingClientRect().width);
    const watch = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    watch.observe(el);
    return () => watch.disconnect();
  }, []);

  const stillUrl = unit?.picture.stills[frame.id]?.url;
  const line = clockLine(view, frame.id);
  const offset = line?.source.kind === "take" ? (line.source.offset ?? 0) : 0;
  const takeUrl = takeless ? undefined : take?.video?.url;

  useEffect(() => {
    const el = canvas.current;
    const ctx = el?.getContext("2d");
    if (!el || !ctx || width <= 0) return;
    const ready = () => setArrived((n) => n + 1);
    const [W, H] = view.options.geometry.frame;
    const dpr = window.devicePixelRatio || 1;
    const cssH = (width * H) / W;
    el.width = Math.round(width * dpr);
    el.height = Math.round(cssH * dpr);
    ctx.setTransform((width * dpr) / W, 0, 0, (cssH * dpr) / H, 0, 0);
    // eleven pixels on screen, at least, in the frame's own units
    const least = Math.max(30, (11 * W) / width);

    ctx.fillStyle = GROUND;
    ctx.fillRect(0, 0, W, H);
    const spot = spotOf(view, frame.layout);
    const person = frame.presence !== "content" ? spot.person : null;
    const picture = frame.presence !== "person" ? spot.picture : null;

    const drawPicture = () => {
      if (!picture) return;
      const [x, y, w, h] = picture;
      ctx.save();
      rounded(ctx, x, y, w, h, Math.min(spot.picture_radius ?? 0, 400));
      ctx.clip();
      ctx.globalAlpha = spot.glass ? 0.94 : 1;
      ctx.fillStyle = PAPER;
      ctx.fillRect(x, y, w, h);
      const img = stillUrl ? still(stillUrl, ready) : null;
      if (img && img.complete && img.naturalWidth) contain(ctx, img, img.naturalWidth, img.naturalHeight, x, y, w, h);
      else sketch(ctx, frame.shows || unit?.shows || "A picture for this line", x, y, w, h, least);
      ctx.restore();
    };
    const drawPerson = () => {
      if (!person) return;
      const [x, y, w, h] = person;
      ctx.save();
      rounded(ctx, x, y, w, h, Math.min(spot.person_radius ?? 0, 400));
      ctx.clip();
      ctx.fillStyle = WINDOW;
      ctx.fillRect(x, y, w, h);
      const video = takeUrl ? reel(takeUrl, offset, ready) : null;
      if (video && video.readyState >= 2 && video.videoWidth) cover(ctx, video, video.videoWidth, video.videoHeight, x, y, w, h, spot.zoom ?? 1);
      else standIn(ctx, x, y, w, h);
      ctx.restore();
    };
    // a glass picture lies over the person; any other sits under the person's window
    if (spot.glass) {
      drawPerson();
      drawPicture();
    } else {
      drawPicture();
      drawPerson();
    }
  }, [view, frame, unit, width, arrived, stillUrl, takeUrl, offset]);

  return <canvas ref={canvas} className="ep-frame-canvas" role={label ? "img" : undefined} aria-label={label || undefined} aria-hidden={label ? undefined : true} />;
}
