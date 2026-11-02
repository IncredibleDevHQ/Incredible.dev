#!/usr/bin/env node
// film-probe.mjs — read the ARTIFACT, not the source string.
//
// Loads a HyperFrames composition in the sandbox Chrome, seeks its paused GSAP timeline the way the
// renderer does (sequential, increasing time, through `window.__hf.seek` or the timelines registered
// on `window.__timelines`), and records, per sample:
//
//   • which elements are actually VISIBLE (opacity chain, display/visibility, on-stage, big enough
//     to read) — not "is there a selector in the source";
//   • whether each visible element CHANGED since the previous sample (rect, opacity, colour,
//     transform, filter, clip-path, dash-offset) — real motion, not "is a timeline registered";
//   • a real downsampled SCREENSHOT of the rendered frame (CDP `Page.captureScreenshot` with
//     `clip.scale`, decoded here with the built-in zlib), so blank frames are measured in pixels.
//
// It emits one JSON "film model". `film-analysis.mjs` turns that model into findings and
// `video-score.mjs` into a verdict. Keeping the probe (I/O, environment) apart from the analysis
// (pure) is what lets every check carry a regression test against a recorded model.
//
// Usage:
//   node /workspace/tools/film-probe.mjs <composition.html> [--step 0.1] [--max-samples 400]
//        [--out model.json] [--timeout 30000] [--json] [--root <dir>]
//
// Exit: 0 model produced · 2 could not probe (missing browser, no timeline, page error). Never exit
// 0 without a model — a check that cannot run is not a pass.

import { writeFileSync } from "node:fs";
import { relative, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import zlib from "node:zlib";
import { EXIT, ToolingError, WORKSPACE, confined, isMain, launchBrowser, parseFlags, requireFile, runCli } from "./toolchain.mjs";

// ── PNG decode (built-in zlib only; the frames are 240×135 so this is ~1 ms) ──
export function decodePng(buf) {
  if (buf.length < 8 || buf.readUInt32BE(0) !== 0x89504e47) throw new Error("not a PNG");
  let off = 8, w = 0, h = 0, depth = 0, ct = 0;
  const idat = [];
  while (off + 8 <= buf.length) {
    const len = buf.readUInt32BE(off);
    const type = buf.toString("ascii", off + 4, off + 8);
    const data = buf.subarray(off + 8, off + 8 + len);
    if (type === "IHDR") { w = data.readUInt32BE(0); h = data.readUInt32BE(4); depth = data[8]; ct = data[9]; }
    else if (type === "IDAT") idat.push(data);
    else if (type === "IEND") break;
    off += 12 + len;
  }
  const ch = { 0: 1, 2: 3, 4: 2, 6: 4 }[ct];
  if (!ch || depth !== 8) throw new Error(`unsupported PNG (colourType=${ct} depth=${depth})`);
  const raw = zlib.inflateSync(Buffer.concat(idat));
  const stride = w * ch;
  const out = Buffer.alloc(h * stride);
  let p = 0;
  for (let y = 0; y < h; y++) {
    const f = raw[p++];
    const line = raw.subarray(p, p + stride);
    p += stride;
    const cur = out.subarray(y * stride, (y + 1) * stride);
    const prev = y ? out.subarray((y - 1) * stride, y * stride) : null;
    for (let i = 0; i < stride; i++) {
      const a = i >= ch ? cur[i - ch] : 0;
      const b = prev ? prev[i] : 0;
      const c = prev && i >= ch ? prev[i - ch] : 0;
      let v = line[i];
      if (f === 1) v += a;
      else if (f === 2) v += b;
      else if (f === 3) v += (a + b) >> 1;
      else if (f === 4) {
        const pa = Math.abs(b - c), pb = Math.abs(a - c), pc = Math.abs(a + b - 2 * c);
        v += pa <= pb && pa <= pc ? a : pb <= pc ? b : c;
      }
      cur[i] = v & 255;
    }
  }
  return { w, h, ch, data: out };
}

// Frame statistics. Ink is measured against each frame's OWN modal colour, not a fixed ground (a
// film with two grounds breaks a fixed-ground test): histogram the frame, take the modal bucket,
// count pixels more than 36 away from it. Mean luminance is the wrong probe — a beat whose content
// is one headline barely moves the frame mean, while its non-ground pixel count is unmistakable.
//
// `ink` is returned as a FRACTION of the frame so the ~3000px-on-1920x1080 floor survives the
// downscale and any stage size.
const INK_DISTANCE = 36; // channel-sum distance from the modal colour
export function frameStats(img) {
  const px = img.w * img.h;
  const counts = new Map();
  let hash = 0x811c9dc5;
  for (let i = 0; i < img.data.length; i += img.ch) {
    const k = ((img.data[i] >> 3) << 10) | ((img.data[i + 1] >> 3) << 5) | (img.data[i + 2] >> 3);
    counts.set(k, (counts.get(k) || 0) + 1);
    hash = Math.imul(hash ^ k, 16777619) >>> 0;
  }
  let modal = 0, modalKey = 0;
  for (const [k, v] of counts) if (v > modal) { modal = v; modalKey = k; }
  // recover the modal bucket centre, then count true non-ground pixels
  const br = ((modalKey >> 10) & 31) * 8 + 4, bg = ((modalKey >> 5) & 31) * 8 + 4, bb = (modalKey & 31) * 8 + 4;
  let inkPx = 0;
  for (let i = 0; i < img.data.length; i += img.ch) {
    if (Math.abs(img.data[i] - br) + Math.abs(img.data[i + 1] - bg) + Math.abs(img.data[i + 2] - bb) > INK_DISTANCE) inkPx++;
  }
  return {
    ink: +(inkPx / px).toFixed(5),
    distinct: counts.size,
    ground: `#${[br, bg, bb].map((c) => c.toString(16).padStart(2, "0")).join("")}`,
    hash: hash >>> 0,
  };
}

// ── the in-page sampler (stringified into the browser) ───────────────────────
// Kept in one function so the probe has exactly one definition of "visible".
const PAGE_SETUP = function () {
  const MIN_INK_AREA = 256; // px² — 1×1 SFX anchor divs are not "on screen"
  const stage = {
    w: parseFloat(document.querySelector("#root")?.dataset?.width || "0") || window.innerWidth,
    h: parseFloat(document.querySelector("#root")?.dataset?.height || "0") || window.innerHeight,
  };
  // A finding that says "svg x svg" cannot be acted on. When the plain selector is not unique,
  // qualify it with the nearest identified ancestor and its position among its siblings, so
  // every reported element can actually be found in the source.
  const plain = (el) =>
    el.id ? "#" + el.id : el.tagName.toLowerCase() + ([...el.classList].slice(0, 2).map((c) => "." + c).join(""));
  const sel = (el) => {
    const base = plain(el);
    if (el.id) return base;
    const anchor = el.parentElement?.closest("[id]");
    const nth = el.parentElement ? [...el.parentElement.children].indexOf(el) + 1 : 0;
    return (anchor ? "#" + anchor.id + " " : "") + base + (nth ? `:nth-child(${nth})` : "");
  };

  // Track anything identifiable, anything that carries text, and any graphic leaf.
  const seen = new Set();
  const els = [];
  const consider = (el) => {
    if (seen.has(el) || el.id === "root" || el === document.body) return;
    seen.add(el);
    els.push(el);
  };
  document.querySelectorAll("[id]").forEach(consider);
  document.querySelectorAll(".scene,[data-scene],.clip").forEach(consider);
  document.querySelectorAll("svg,img,canvas,video").forEach(consider);
  document.querySelectorAll("*").forEach((el) => {
    if (els.length > 600) return;
    for (const n of el.childNodes) if (n.nodeType === 3 && n.textContent.trim()) return consider(el);
  });

  const eff = (el) => {
    let op = 1;
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
      const cs = getComputedStyle(n);
      if (cs.visibility === "hidden" || cs.display === "none") return 0;
      op *= parseFloat(cs.opacity);
      if (!(op > 0)) return 0;
    }
    return op;
  };

  // An element carries ink of its own when it has a text node or is a graphic leaf. A card and
  // its label are parent and child, never a collision; two labels on the same pixels are.
  const inks = els.map((el) => {
    if (/^(svg|img|canvas|video)$/i.test(el.tagName)) return true;
    return [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
  });
  const related = (a, b) => a.contains(b) || b.contains(a);
  // `data-layout-allow-overlap` declares a deliberate overlap (a cursor, a scrim, a wipe handle). It covers
  // the element and its descendants, one side of a pair is enough, the pair still reports as a WARN, and
  // it is ignored on anything covering more than half the stage -- a scene root is a ground, never a
  // peer, and the marker on scene roots would otherwise switch the check off for a whole film.
  const GROUND = 0.5;
  const marker = els.map((el) => el.closest("[data-layout-allow-overlap]"));
  const excused = (i) => {
    const m = marker[i];
    if (!m) return false;
    const r = m.getBoundingClientRect();
    return r.width * r.height <= stage.w * stage.h * GROUND;
  };

  const st = {
    ids: els.map(sel),
    prev: els.map(() => ""),
    best: els.map(() => null),
    // worst box overlap per unordered pair, "i|j" -> candidate for the pixel pass
    collisions: new Map(),
    stage,
  };
  window.__probe = st;

  // A shrinkable flex item in a fixed-height stage absorbs overflow by compressing and the stage
  // crops the rest silently: `stage.scrollHeight - stage.clientHeight` must be 0, alongside
  // per-element `scrollWidth - clientWidth` (the width check alone cannot see this).
  const stageEl = document.querySelector("#root") || document.body;
  st.stageOverflow = { x: 0, y: 0 };

  window.__probeSample = function (t) {
    st.stageOverflow.x = Math.max(st.stageOverflow.x, stageEl.scrollWidth - stageEl.clientWidth);
    st.stageOverflow.y = Math.max(st.stageOverflow.y, stageEl.scrollHeight - stageEl.clientHeight);
    let vis = "";
    const changed = [];
    for (let i = 0; i < els.length; i++) {
      const el = els[i];
      const r = el.getBoundingClientRect();
      const op = eff(el);
      const onStage = r.right > 0 && r.bottom > 0 && r.left < stage.w && r.top < stage.h;
      const visible = op > 0.02 && r.width * r.height >= MIN_INK_AREA && onStage;
      const cs = getComputedStyle(el);
      const sig = visible
        ? [
            Math.round(r.x * 2), Math.round(r.y * 2), Math.round(r.width * 2), Math.round(r.height * 2),
            Math.round(op * 100), cs.color, cs.backgroundColor, cs.transform, cs.filter,
            cs.clipPath, cs.strokeDashoffset, cs.strokeDasharray, el.textContent.trim().length,
          ].join("|")
        : "";
      vis += visible ? "1" : "0";
      if (sig !== st.prev[i]) { changed.push(i); st.prev[i] = sig; }

      // remember the sample where this element reads strongest — typography, clipping
      // and off-stage geometry are judged there, not at an arbitrary frame.
      if (visible) {
        const weight = r.width * r.height * op;
        if (!st.best[i] || weight > st.best[i].weight) {
          const own = [...el.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent.trim()).join(" ");
          st.best[i] = {
            weight, fontPx: parseFloat(cs.fontSize) || 0, family: cs.fontFamily,
            weightCss: cs.fontWeight, textLen: own.length,
            w: Math.round(r.width), h: Math.round(r.height),
            x: Math.round(r.x), y: Math.round(r.y),
            // only a box that actually CROPS can clip its content silently; an element
            // whose overflow is visible merely overhangs, which is a different defect.
            ownCrops: /hidden|clip|scroll|auto/.test(cs.overflow + cs.overflowX + cs.overflowY),
            selfClipY: Math.max(0, el.scrollHeight - el.clientHeight),
            selfClipX: Math.max(0, el.scrollWidth - el.clientWidth),
            flexItem: el.parentElement ? getComputedStyle(el.parentElement).display.includes("flex") : false,
            flexRule: cs.flexGrow + " " + cs.flexShrink + " " + cs.flexBasis,
            clipped: (() => {
              // nearest ancestor that actually crops (overflow only — an animated
              // clip-path IS the wipe, not a defect)
              for (let n = el.parentElement; n && n !== document.body; n = n.parentElement) {
                const pcs = getComputedStyle(n);
                if (/hidden|clip|scroll|auto/.test(pcs.overflow + pcs.overflowX + pcs.overflowY)) {
                  const pr = n.getBoundingClientRect();
                  const dx = Math.max(0, pr.left - r.left) + Math.max(0, r.right - pr.right);
                  const dy = Math.max(0, pr.top - r.top) + Math.max(0, r.bottom - pr.bottom);
                  if (dx > 1 || dy > 1) return { by: sel(n), dx: Math.round(dx), dy: Math.round(dy) };
                  return null;
                }
              }
              return null;
            })(),
            offStage: {
              dx: Math.round(Math.max(0, -r.left) + Math.max(0, r.right - stage.w)),
              dy: Math.round(Math.max(0, -r.top) + Math.max(0, r.bottom - stage.h)),
            },
          };
        }
      }
    }
    // ── collision: two things drawn on the same pixels, both fully opaque ──────
    // This is the defect a checkmark fading in over a numeral produces (`0<check>1`). It is not
    // clipping -- both elements are inside their parent and both "visible" -- so the overflow
    // checks cannot see it, and neither can brand-lint, which never renders.
    const solid = [];
    for (let i = 0; i < els.length; i++) {
      if (!inks[i] || vis[i] !== "1") continue;
      if (eff(els[i]) < 0.9) continue;            // mid-crossfade is not a collision
      const r = els[i].getBoundingClientRect();
      if (r.width < 4 || r.height < 4) continue;
      // A ground is not a colliding peer. Type over a full-bleed backdrop, card or scene is the
      // normal way a frame is built; only elements that are both small enough to be PEERS can
      // smudge each other.
      if (r.width * r.height > stage.w * stage.h * GROUND) continue;
      solid.push({ i, r });
    }
    for (let a = 0; a < solid.length; a++) {
      for (let b = a + 1; b < solid.length; b++) {
        const A = solid[a], B = solid[b];
        if (related(els[A.i], els[B.i])) continue;
        const ow = Math.min(A.r.right, B.r.right) - Math.max(A.r.left, B.r.left);
        const oh = Math.min(A.r.bottom, B.r.bottom) - Math.max(A.r.top, B.r.top);
        if (ow <= 1 || oh <= 1) continue;
        const smaller = Math.min(A.r.width * A.r.height, B.r.width * B.r.height);
        const ratio = (ow * oh) / (smaller || 1);
        if (ratio < 0.25) continue;               // a touching edge is not an overlap
        const key = A.i + "|" + B.i;
        const had = st.collisions.get(key);
        if (had && ratio <= had.ratio) continue;
        // The rect is carried out so the pixel pass can re-capture exactly this region.
        st.collisions.set(key, {
          t, ratio, i: A.i, j: B.i, excused: excused(A.i) || excused(B.i),
          rect: {
            x: Math.max(0, Math.round(Math.max(A.r.left, B.r.left))),
            y: Math.max(0, Math.round(Math.max(A.r.top, B.r.top))),
            w: Math.round(ow), h: Math.round(oh),
          },
        });
      }
    }

    return { vis, changed };
  };

  window.__probeBest = function () {
    return st.ids.map((id, i) => (st.best[i] ? { id, ...st.best[i] } : null)).filter(Boolean);
  };

  window.__probeCollisions = function () {
    return [...st.collisions.values()]
      .map((v) => ({ a: st.ids[v.i], b: st.ids[v.j], t: v.t, ratio: Math.round(v.ratio * 100) / 100, excused: v.excused, i: v.i, j: v.j, rect: v.rect }))
      .sort((x, y) => y.ratio - x.ratio);
  };

  // Hide exactly the listed elements and restore every other one, so the pixel pass can ask
  // "which pixels does this element paint?" without disturbing the timeline.
  const stash = new Map();
  window.__probeHide = function (list) {
    const want = new Set(list);
    for (const [i, prev] of [...stash]) {
      if (want.has(i)) continue;
      els[i].style.visibility = prev;
      stash.delete(i);
    }
    for (const i of want) {
      if (stash.has(i)) continue;
      stash.set(i, els[i].style.visibility);
      els[i].style.visibility = "hidden";
    }
  };

  window.__probeBroken = function () {
    return [...document.images].filter((i) => !i.complete || i.naturalWidth === 0).map((i) => i.currentSrc || i.src);
  };
};

// ── occlusion, confirmed in pixels ───────────────────────────────────────────
// The box test above is a candidate generator, not a verdict: a label centred in a ring's
// hole intersects the ring's box completely and occludes nothing, while a tick fading in over
// a numeral intersects the same way and destroys both. Boxes cannot tell those apart. Pixels
// can, and this is a fact about the artifact, so code should own it rather than the prompt.
//
// For each candidate: hide both elements, then each alone, and diff. The pixels an element
// paints are the ones that change when it alone is revealed. Two elements collide when the
// pixels they paint are the SAME pixels -- which is direction-free, so it does not matter
// which of the two is on top.
const CONFIRM_MAX = 48;          // a pathological film must not turn the gate into a render
// A mark at >=0.9 opacity changes the pixels it covers by far more than this; a visibility toggle inside
// an `overflow:hidden; border-radius` container re-rasterizes that container's clip edge by up to ~11
// levels, and at 10 that edge was being counted as paint by BOTH elements -- a false collision.
const CHANNEL_EPS = 24;
// A ratio over a handful of shared pixels is anti-aliasing, not a smudge. Measured: noise shares ~4 px
// (a hidden tick's edge against a numeral), while the smallest real defect shares 14 (a tick stub over
// a "3"), a garbled 16px icon pair 25. So the floor is on the SHARED count; a floor on each element's
// own size hides small real collisions.
const MIN_SHARED_PX = 10;

// `decodePng` returns { w, h, ch, data } and `ch` is 3 for the opaque clips captured here, not
// 4 — assuming RGBA silently produced a zero-length mask and a film with a real collision came
// back clean, which is exactly the shape of failure a gate must never have.
function inkMask(base, lit) {
  if (base.w !== lit.w || base.h !== lit.h || base.ch !== lit.ch) return { mask: null, count: 0 };
  const ch = base.ch;
  const n = base.w * base.h;
  const mask = new Uint8Array(n);
  let count = 0;
  for (let p = 0; p < n; p++) {
    const o = p * ch;
    let diff = false;
    for (let k = 0; k < Math.min(3, ch); k++) {
      if (Math.abs(base.data[o + k] - lit.data[o + k]) > CHANNEL_EPS) { diff = true; break; }
    }
    if (diff) { mask[p] = 1; count++; }
  }
  return { mask, count };
}

async function confirmCollisions(page, cdp, seek, candidates, stage) {
  const out = [];
  const queue = candidates.slice(0, CONFIRM_MAX).sort((x, y) => x.t - y.t);
  if (!queue.length) return out;
  await seek(0);                                   // the seek contract is monotonic-increasing
  for (const c of queue) {
    const x = Math.max(0, Math.min(c.rect.x, stage.w - 1));
    const y = Math.max(0, Math.min(c.rect.y, stage.h - 1));
    const width = Math.min(c.rect.w, stage.w - x);
    const height = Math.min(c.rect.h, stage.h - y);
    if (width < 2 || height < 2) continue;
    const clip = { x, y, width, height, scale: 1 };
    const shoot = async () =>
      decodePng(Buffer.from((await cdp.send("Page.captureScreenshot", { format: "png", clip })).data, "base64"));
    try {
      await seek(c.t);
      await page.evaluate((v) => window.__probeHide(v), [c.i, c.j]);
      const neither = await shoot();
      await page.evaluate((v) => window.__probeHide(v), [c.j]);
      const aOnly = await shoot();
      await page.evaluate((v) => window.__probeHide(v), [c.i]);
      const bOnly = await shoot();
      await page.evaluate(() => window.__probeHide([]));
      const A = inkMask(neither, aOnly);
      const B = inkMask(neither, bOnly);
      if (!A.count || !B.count) continue;             // one of them paints nothing here
      let both = 0;
      for (let p = 0; p < A.mask.length; p++) if (A.mask[p] && B.mask[p]) both++;
      if (both < MIN_SHARED_PX) continue;
      const overlap = both / Math.min(A.count, B.count);
      out.push({
        a: c.a, b: c.b, t: c.t, boxRatio: c.ratio, excused: !!c.excused,
        ink: Math.round(overlap * 100) / 100,
        sharedPx: both,
      });
    } catch (err) {
      console.error(`film-probe: could not confirm ${c.a} x ${c.b} @${c.t}s — ${err.message}`);
      // A capture that fails is not evidence of a defect; keep the candidate's box verdict out
      // of the model rather than inventing one.
      await page.evaluate(() => window.__probeHide([])).catch(() => {});
    }
  }
  return out.sort((x, y) => y.ink - x.ink);
}

// ── the probe ────────────────────────────────────────────────────────────────
export async function probeFilm(file, opts = {}) {
  const root = opts.root ?? WORKSPACE;
  const step = opts.step ?? 0.1;
  const maxSamples = opts.maxSamples ?? 400;
  const timeout = opts.timeout ?? 30000;

  // The same flags every export uses (text-fidelity.mjs): a gate that renders text differently from the
  // export measures a different film, and --no-sandbox is what lets Chromium start in the sandbox.
  const browser = await launchBrowser(["--allow-file-access-from-files"]);
  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 1920, height: 1080 });
    const load = { pageErrors: [], consoleErrors: [], failedRequests: [] };
    page.on("pageerror", (e) => load.pageErrors.push(String(e).slice(0, 300)));
    page.on("console", (m) => { if (m.type() === "error") load.consoleErrors.push(m.text().slice(0, 300)); });
    page.on("requestfailed", (r) => load.failedRequests.push(r.url().slice(0, 200)));

    try {
      await page.goto(pathToFileURL(file).href, { waitUntil: "networkidle0", timeout });
    } catch (error) {
      throw new ToolingError(`film-probe: could not load the composition: ${error.message}`);
    }
    await page.evaluate(() => document.fonts.ready).catch(() => {});

    const meta = await page.evaluate(() => {
      const reg = window.__timelines || {};
      const ids = Object.keys(reg);
      const root = document.querySelector("#root");
      let tlDur = 0, paused = null, children = 0;
      for (const id of ids) {
        const tl = reg[id];
        if (typeof tl?.duration !== "function") continue;
        tlDur = Math.max(tlDur, tl.duration());
        if (paused === null) paused = typeof tl.paused === "function" ? tl.paused() : null;
        if (typeof tl.getChildren === "function") children += tl.getChildren(true, true, true).length;
      }
      const clips = [...document.querySelectorAll(".clip[data-start],[data-composition-src]")].map((c) => ({
        id: c.dataset.compositionId || c.id || "(clip)",
        start: parseFloat(c.dataset.start || "0"),
        duration: parseFloat(c.dataset.duration || "0"),
      }));
      return {
        ids,
        compositionId: root?.dataset?.compositionId || ids[0] || null,
        dataDuration: parseFloat(root?.dataset?.duration || "0") || 0,
        stage: {
          w: parseFloat(root?.dataset?.width || "0") || 1920,
          h: parseFloat(root?.dataset?.height || "0") || 1080,
        },
        tlDur, paused, children, clips,
      };
    });

    if (!meta.ids.length) {
      throw new ToolingError(
        "film-probe: no GSAP timeline registered on window.__timelines — the renderer " +
          "reads that registry synchronously after load, so this composition cannot be captured at all."
      );
    }

    // `data-duration` is what the renderer captures; the GSAP duration is advisory.
    const duration = meta.dataDuration || meta.tlDur;
    if (!(duration > 0)) throw new ToolingError("film-probe: composition has no positive duration");
    const realStep = Math.max(step, +(duration / maxSamples).toFixed(4));

    await page.evaluate(PAGE_SETUP);
    // Capture at the stage's own size: a vertical or square stage in a 1920x1080 viewport would crop.
    if (meta.stage.w !== 1920 || meta.stage.h !== 1080) {
      await page.setViewport({ width: Math.round(meta.stage.w), height: Math.round(meta.stage.h) });
    }
    const cdp = await page.createCDPSession();

    const times = [];
    for (let t = 0; t <= duration + 1e-9; t = +(t + realStep).toFixed(4)) times.push(Math.min(t, duration));

    const visRows = [];
    const changedRows = [];
    const seek = (time) =>
      page.evaluate((v) => {
        if (window.__hf && typeof window.__hf.seek === "function") return window.__hf.seek(v);
        // `seek(t)` defaults to suppressEvents:true, which skips callbacks; the renderer seeks with
        // callbacks on, so a component driven by `tl.call()` would be judged in a state the real
        // render never produces.
        for (const tl of Object.values(window.__timelines || {})) if (typeof tl.seek === "function") tl.seek(v, false);
      }, time);

    const frames = [];
    for (const t of times) {
      // Sequential, increasing seeks — the renderer's own access pattern. (A random-access
      // seek with the default suppressEvents skips onUpdate, so counter text would freeze
      // at its initial value and the probe would judge a frame the render never produces.)
      await seek(t);
      const s = await page.evaluate((time) => window.__probeSample(time), t);
      visRows.push(s.vis);
      changedRows.push(s.changed);
      const shot = await cdp.send("Page.captureScreenshot", {
        format: "png",
        clip: { x: 0, y: 0, width: meta.stage.w, height: meta.stage.h, scale: 240 / meta.stage.w },
      });
      frames.push({ t, ...frameStats(decodePng(Buffer.from(shot.data, "base64"))) });
    }

    const best = await page.evaluate(() => window.__probeBest());
    const collisions = await confirmCollisions(
      page, cdp, seek, await page.evaluate(() => window.__probeCollisions()), meta.stage,
    );
    const ids = await page.evaluate(() => window.__probe.ids);
    const stageOverflow = await page.evaluate(() => window.__probe.stageOverflow);
    load.brokenImages = await page.evaluate(() => window.__probeBroken());

    return {
      tool: "film-probe/1",
      file: relative(root, file),
      compositionId: meta.compositionId,
      duration,
      timelineDuration: +meta.tlDur.toFixed(3),
      timeline: { ids: meta.ids, paused: meta.paused, children: meta.children },
      stage: meta.stage,
      stageOverflow,
      collisions,
      clips: meta.clips,
      step: realStep,
      times,
      ids,
      vis: visRows,
      changed: changedRows,
      frames,
      elements: best,
      load,
    };
  } finally {
    await browser.close().catch(() => {});
  }
}

// ── CLI ──────────────────────────────────────────────────────────────────────
if (isMain(import.meta.url)) {
  await runCli("film-probe", async () => {
    const { flags, positionals } = parseFlags(process.argv.slice(2), {
      values: ["step", "max-samples", "timeout", "out", "root"],
      booleans: ["json"],
    });
    if (positionals.length !== 1) throw new ToolingError("usage: film-probe.mjs <composition.html> [--step S] [--out model.json] [--json]");
    const root = resolve(flags.root || WORKSPACE);
    const file = requireFile(confined(root, positionals[0], "composition"), "composition");
    const model = await probeFilm(file, {
      root,
      step: Number(flags.step ?? 0.1),
      maxSamples: Number(flags["max-samples"] ?? 400),
      timeout: Number(flags.timeout ?? 30000),
    });
    if (flags.out) {
      const out = confined(root, flags.out, "--out");
      writeFileSync(out, JSON.stringify(model));
      console.log(`film-probe: wrote ${relative(root, out)} (${model.times.length} samples @ ${model.step}s)`);
    } else if (flags.json) {
      console.log(JSON.stringify(model));
    } else {
      console.log(`film-probe: ${model.file}\n  duration ${model.duration}s · ${model.times.length} samples @ ${model.step}s` +
        `\n  timeline ${model.timeline.ids.join(",")} · ${model.timeline.children} tweens · paused=${model.timeline.paused}` +
        `\n  tracked elements ${model.ids.length} · clips ${model.clips.length}`);
    }
    return EXIT.PASS;
  });
}
