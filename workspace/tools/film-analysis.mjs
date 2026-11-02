#!/usr/bin/env node
// film-analysis.mjs — PURE analysis of a film model (see film-probe.mjs). No I/O, no
// browser, no network, no clock: same model in, same findings out. That is deliberate —
// it is what lets every check here carry a regression test with a recorded fixture and a
// passing control instead of "the gate ran and printed something".
//
// A rule written down in prose does not stop a defect from shipping; a measurement in the gate does,
// so each check here encodes one failure mode of seek-rendered film as a number.
//
// Severities: ERROR fails the gate. WARN is reported and costs score. INFO is context.

// ── tunables, each one a measured threshold ──────────────────────────────────────────
export const T = {
  // Under ~3000 non-ground px on a 1920x1080 frame reads as blank; a healthy frame carries
  // hundreds of thousands.
  INK_BLANK: 3000 / (1920 * 1080), // 0.00145 as a fraction, so it survives any stage size
  // A small first element (a 30px mono eyebrow) legitimately measures 1600-1800 px: a deliberate
  // reveal, not a blank. So a frame with SOME ink under the floor is THIN and only errors if the
  // dropout lasts (the defect is a multi-frame blank ground, not one dissolve midpoint). A frame
  // with literally zero non-ground pixels is BLANK with no caveat.
  THIN_RUN_S: 0.25,
  HEAD_TAIL_GRACE: 0.25, // a fade-up from ground at the very head/tail is legitimate film grammar
  // scene segmentation: a cut is where nearly everything on screen turns over inside one
  // shot-length window.
  TURNOVER_WINDOW_S: 0.8,
  TURNOVER_CUT: 0.75,
  MIN_SCENE_S: 0.6,
  // a carried element has to belong to BOTH shots, not merely straddle the dissolve
  CARRY_MARGIN_S: 0.5,
  // settled_hold = next_event_start - (entrance_start + entrance_duration). When it is negative,
  // the screen never settles long enough to read.
  MIN_SETTLED_HOLD_S: 0.3,
  // development: a change that lands within an element's own first second is its entrance,
  // not its development.
  ENTRY_GRACE_S: 1.0,
  EXIT_GRACE_S: 0.4,
  // Motion, measured on rendered frames. Calibrated against a well-paced 3-shot control
  // (34% of frames differ, longest interior still 1.7s), so that a film with real HOLDS is not
  // punished for having them: a two-line sentence at 46px wants ~2.5s of settled dwell. Only dead
  // air and a genuine still fail.
  MAX_STATIC_RUN_S: 3.0,
  MIN_CHANGING_FRAMES: 0.15,
  // px of overflow that counts as a real crop rather than line-box rounding
  MIN_CLIP_PX: 4,
  // a stray micro-label set tiny is not the defect; a BODY set tiny is
  MIN_SIZE_SHARE: 0.05,
  // Fraction of the fainter element's own PAINTED PIXELS that the other one paints over.
  // Not a box overlap: a label centred in a ring's hole scores 0 here and 1.0 on boxes.
  MIN_COLLISION_INK: 0.2,
};

const r2 = (n) => Math.round(n * 100) / 100;

// ── helpers over the sampled visibility matrix ───────────────────────────────────────
function visibleSet(model, i) {
  const row = model.vis[i];
  const out = new Set();
  for (let k = 0; k < row.length; k++) if (row[k] === "1") out.add(k);
  return out;
}
const atTime = (model, t) => {
  let best = 0, d = Infinity;
  for (let i = 0; i < model.times.length; i++) {
    const dd = Math.abs(model.times[i] - t);
    if (dd < d) { d = dd; best = i; }
  }
  return best;
};

/**
 * Segment the film into shots from what is ACTUALLY on screen, not from `.scene`
 * selectors in the source — a film assembled from sub-composition clips, one built from
 * stacked wrappers and one built from `.scene` divs all segment the same way.
 *
 * A cut is a TURNOVER: across one shot-length window, almost nothing that was on screen
 * is still on screen. Beats inside a shot (a row arriving, a number counting) leave most
 * of the frame intact and score far below the threshold, so they do not split a scene.
 * Returns `{scenes, cuts}` where each cut carries the window it occupies, which is what
 * the continuity check needs.
 */
export function segmentScenes(model) {
  const n = model.times.length;
  const W = Math.max(1, Math.round(T.TURNOVER_WINDOW_S / model.step));
  const sets = [];
  for (let i = 0; i < n; i++) sets.push(visibleSet(model, i));

  const turnover = new Array(n).fill(0);
  for (let i = W; i < n; i++) {
    const a = sets[i - W], b = sets[i];
    // a turnover measured across an empty frame measures nothing
    if (!a.size || !b.size) { turnover[i] = 0; continue; }
    let inter = 0;
    for (const k of b) if (a.has(k)) inter++;
    turnover[i] = 1 - inter / (a.size + b.size - inter);
  }

  // every maximal run above the cut threshold is one boundary; its peak is the cut time
  let cuts = [];
  let i = W;
  while (i < n) {
    if (turnover[i] <= T.TURNOVER_CUT) { i++; continue; }
    let j = i, peak = i;
    while (j < n && turnover[j] > T.TURNOVER_CUT) { if (turnover[j] > turnover[peak]) peak = j; j++; }
    // the window that turned over spans from W samples before the run to its end
    cuts.push({ startIdx: Math.max(0, i - W), endIdx: j - 1, peakIdx: peak, t: model.times[peak] });
    i = j;
  }
  // a ground inversion or a flash reads as two turnovers a fraction of a second apart;
  // that is one transition, not two shots.
  const gap = Math.round(T.MIN_SCENE_S / model.step);
  cuts = cuts.reduce((acc, c) => {
    const prev = acc[acc.length - 1];
    if (prev && c.startIdx - prev.endIdx < gap) {
      prev.endIdx = c.endIdx;
      if (turnover[c.peakIdx] > turnover[prev.peakIdx]) { prev.peakIdx = c.peakIdx; prev.t = c.t; }
      return acc;
    }
    acc.push(c);
    return acc;
  }, []);

  const scenes = [];
  let from = 0;
  for (const c of cuts) {
    if (c.startIdx > from) scenes.push({ startIdx: from, endIdx: c.startIdx });
    from = Math.min(n - 1, c.endIdx + 1);
  }
  scenes.push({ startIdx: from, endIdx: n - 1 });

  const out = scenes
    .map((s) => ({ ...s, start: model.times[s.startIdx], end: model.times[s.endIdx] }))
    .filter((s) => s.end - s.start >= T.MIN_SCENE_S);

  // A sub-composition film declares its cuts outright; trust the declaration when the
  // sampled DOM cannot see inside the clips (an unbuilt `.sub.html` renders nothing).
  // Clips on parallel tracks overlap in time and describe layers, not cuts, so only a sequence of
  // clips (each starting where the previous one ends, or later) is a declaration of shots.
  const clips = (model.clips || []).filter((c) => c.duration > 0).sort((a, b) => a.start - b.start);
  const sequential = clips.every((c, i) => i === 0 || c.start >= clips[i - 1].start + clips[i - 1].duration - model.step);
  if (clips.length > 1 && sequential && out.length < clips.length) {
    const declared = clips.map((c) => ({
      startIdx: atTime(model, c.start), endIdx: atTime(model, c.start + c.duration),
      start: c.start, end: c.start + c.duration, clipId: c.id,
    }));
    return {
      scenes: declared,
      cuts: declared.slice(1).map((s) => ({ startIdx: s.startIdx, endIdx: s.startIdx, peakIdx: s.startIdx, t: s.start })),
    };
  }
  return { scenes: out.length ? out : [{ startIdx: 0, endIdx: n - 1, start: model.times[0], end: model.times[n - 1] }], cuts };
}

/**
 * CONTINUITY — does anything survive the cut?
 *
 * A film carries at least one element through each cut; when every cut replaces everything on
 * screen at once, viewers read the transitions as jarring and the motion as disconnected.
 *
 * A carried element is one that is CONTINUOUSLY visible across the whole boundary window
 * plus a settle margin on the far side — it never leaves the screen, so the eye has
 * something to hold. Dead wallpaper (visible in every frame and never changing) does not
 * count: it carries no motion across the cut.
 */
export function analyseContinuity(model, cuts) {
  const findings = [];
  if (!cuts.length) {
    return { boundaries: [], carriedRatio: null, findings, skipped: "single shot — continuity across a cut is not defined" };
  }
  const n = model.times.length;
  const margin = Math.max(1, Math.round(T.CARRY_MARGIN_S / model.step));
  const changeCount = model.ids.map(() => 0);
  for (const row of model.changed) for (const k of row) changeCount[k]++;
  // dead wallpaper carries no motion across the cut, so it is not continuity
  const wallpaper = model.ids.map((_, k) => model.vis.every((row) => row[k] === "1") && changeCount[k] <= 1);

  const boundaries = [];
  for (const c of cuts) {
    const a = Math.max(0, c.startIdx - margin);
    const b = Math.min(n - 1, c.endIdx + margin);
    const carried = [];
    for (let k = 0; k < model.ids.length; k++) {
      if (wallpaper[k]) continue;
      let ok = true;
      for (let i = a; i <= b; i++) if (model.vis[i][k] !== "1") { ok = false; break; }
      if (ok) carried.push(model.ids[k]);
    }
    boundaries.push({ t: r2(c.t), window: [r2(model.times[a]), r2(model.times[b])], carried });
    if (!carried.length) {
      findings.push({
        sev: "WARN", code: "continuity.bare-cut", at: r2(c.t),
        msg: `nothing survives the cut at ${r2(c.t)}s — everything on screen is replaced at once. Give the film a persistent carrier: a populated element in the host DOM OUTSIDE every scene container, on its own data-track-index, spanning the beats it connects.`,
      });
    }
  }
  const withCarry = boundaries.filter((b) => b.carried.length).length;
  const bare = boundaries.length - withCarry;
  const carriedRatio = withCarry / boundaries.length;
  // An isolated bare cut is an act break. Most cuts bare, or three bare in a row, is a
  // film with no through-line.
  let longestBareRun = 0, run = 0;
  for (const b of boundaries) { if (!b.carried.length) { run++; longestBareRun = Math.max(longestBareRun, run); } else run = 0; }
  // A single cut is an act break by definition — and a transition COMPONENT is one cut and
  // nothing else, which is its whole job. The film-level verdict needs at least two.
  if (boundaries.length >= 2 && (carriedRatio < 0.5 || longestBareRun >= 3)) {
    findings.push({
      sev: "ERROR", code: "continuity.none", at: null,
      msg: `${bare} of ${boundaries.length} cuts carry NOTHING across (longest bare run ${longestBareRun}) — this is a slide deck, not a film.`,
    });
  }
  return { boundaries, carriedRatio: r2(carriedRatio), bare, longestBareRun, findings };
}

/**
 * DEVELOPMENT + SETTLED HOLD — does the picture keep moving after it arrives, and does it
 * ever stop moving long enough to read?
 *
 * settled_hold = next_event_start - (entrance_start + entrance_duration). An end card whose last
 * line finishes fading in after the card starts fading out has a negative hold: the screen never
 * settles, and a viewer feels it before anyone measures it.
 *
 * A change inside an element's first second is its ENTRANCE. Development is a change to
 * something that has already arrived.
 */
export function analyseDevelopment(model, scenes) {
  const findings = [];
  const entryGrace = Math.round(T.ENTRY_GRACE_S / model.step);
  const exitGrace = Math.round(T.EXIT_GRACE_S / model.step);
  const report = [];

  for (let s = 0; s < scenes.length; s++) {
    const sc = scenes[s];
    const span = sc.end - sc.start;
    const firstVisible = new Map();
    const developers = new Set();

    for (let i = sc.startIdx; i <= sc.endIdx; i++) {
      for (let k = 0; k < model.ids.length; k++) {
        if (model.vis[i][k] === "1" && !firstVisible.has(k)) firstVisible.set(k, i);
      }
      for (const k of model.changed[i]) {
        if (model.vis[i][k] !== "1") continue; // a disappearance is not development
        const enter = firstVisible.get(k);
        if (enter === undefined) continue;
        if (i - enter >= entryGrace && i <= sc.endIdx - exitGrace) developers.add(model.ids[k]);
      }
    }

    // The settled hold, measured on pixels: the longest stretch inside the shot where the
    // rendered frame does not change at all (the hold window contains zero tweens).
    let run = 0, longestQuiet = 0;
    for (let i = sc.startIdx + 1; i <= sc.endIdx; i++) {
      if (model.frames[i] && model.frames[i - 1] && model.frames[i].hash === model.frames[i - 1].hash) {
        run++; if (run > longestQuiet) longestQuiet = run;
      } else run = 0;
    }
    const settledHold = r2(longestQuiet * model.step);
    const exempt = span < T.ENTRY_GRACE_S + T.EXIT_GRACE_S + model.step;
    const isLast = s === scenes.length - 1;
    report.push({
      index: s, start: r2(sc.start), end: r2(sc.end), span: r2(span),
      develops: developers.size > 0, developers: [...developers].slice(0, 6),
      settledHold, exempt,
    });

    if (!exempt && developers.size === 0) {
      findings.push({
        sev: isLast ? "WARN" : "ERROR", code: "development.static-scene", at: r2(sc.start),
        msg: `shot ${s + 1} (${r2(sc.start)}–${r2(sc.end)}s) never develops — every element enters and then nothing about it changes again. That is a slide with a fade-in, not a shot.`,
      });
    }
    if (!exempt && settledHold < T.MIN_SETTLED_HOLD_S) {
      findings.push({
        sev: "WARN", code: "development.no-settled-hold", at: r2(sc.start),
        msg: `shot ${s + 1} never rests: its longest still stretch is ${settledHold}s (want >= ${T.MIN_SETTLED_HOLD_S}s). Something is moving on every frame, so there is no beat to read the frame on.`,
      });
    }
  }
  return { scenes: report, findings };
}

/**
 * FRAMES — blank / sparse / static, measured on rendered pixels.
 *
 * A scene whose first element is authored a fraction of a second after its cut plays a few frames
 * of blank ground at every cut, and a settled-frame contact sheet does not reveal it; a dissolve's
 * content lead is the most common cause. Frame 0 is the social poster and the video thumbnail, so a
 * fade-from-zero cold open ships a near-blank thumbnail.
 */
export function analyseFrames(model, cuts) {
  const findings = [];
  const grace = T.HEAD_TAIL_GRACE;
  const dur = model.duration;
  const visCount = model.vis.map((row) => (row.match(/1/g) || []).length);
  const thinRun = Math.max(1, Math.round(T.THIN_RUN_S / model.step));

  // group consecutive under-floor samples into windows
  const windows = [];
  let cur = null;
  model.frames.forEach((f, i) => {
    if (f.ink >= T.INK_BLANK) { if (cur) { windows.push(cur); cur = null; } return; }
    if (cur && i === cur.lastIdx + 1) {
      cur.end = f.t; cur.lastIdx = i; cur.samples++;
      cur.minInk = Math.min(cur.minInk, f.ink); cur.maxInk = Math.max(cur.maxInk, f.ink);
      cur.maxVis = Math.max(cur.maxVis, visCount[i]);
    } else {
      if (cur) windows.push(cur);
      cur = { start: f.t, end: f.t, lastIdx: i, samples: 1, minInk: f.ink, maxInk: f.ink, maxVis: visCount[i] };
    }
  });
  if (cur) windows.push(cur);

  const blank = [], thin = [];
  for (const w of windows) {
    const interior = w.start > grace && w.end < dur - grace;
    const nearCut = cuts.find((c) => c.t >= w.start - 0.8 && c.t <= w.end + 0.8);
    const where = `${r2(w.start)}${w.end > w.start ? "–" + r2(w.end) : ""}s`;
    const cutNote = nearCut
      ? ` — the cut at ${r2(nearCut.t)}s has a content lead (the most common cause of blank frames): pull the incoming shot's first element onto the cut (an instantaneous set, not a 0.3s fade).`
      : "";
    const entry = { start: r2(w.start), end: r2(w.end), ink: w.minInk, samples: w.samples, visibleElements: w.maxVis, interior };
    // Literally zero ink is always a blank; some ink under the floor (a small first element) is
    // only a defect when it LASTS.
    if (w.maxInk === 0) {
      blank.push(entry);
      findings.push(interior
        ? { sev: "ERROR", code: "frames.blank", at: r2(w.start), msg: `BLANK FRAME(S) at ${where}: not one non-ground pixel${cutNote}` }
        : { sev: "WARN", code: "frames.blank-poster", at: r2(w.start), msg: `the frame at ${where} is blank and sits at the head/tail — frame 0 is the social poster and the video thumbnail. Start the headline at opacity 1 and animate only y.` });
    } else {
      thin.push(entry);
      if (interior && w.samples >= thinRun) findings.push({
        sev: "ERROR", code: "frames.thin", at: r2(w.start),
        msg: `near-empty frames for ${r2(w.samples * model.step)}s at ${where} (min ink ${w.minInk} = ~${Math.round(w.minInk * model.stage.w * model.stage.h)}px of non-ground, floor is 3000px; ${w.maxVis} element(s) in the DOM)${cutNote}`,
      });
    }
  }

  // motion, measured on the pixels rather than on "is a timeline registered"
  let changing = 0, run = 1, longest = 1, longestAt = model.frames[0]?.t ?? 0, longestEnd = 0;
  for (let i = 1; i < model.frames.length; i++) {
    if (model.frames[i].hash === model.frames[i - 1].hash) {
      run++;
      if (run > longest) { longest = run; longestAt = model.frames[i - run + 1].t; longestEnd = model.frames[i].t; }
    } else { changing++; run = 1; }
  }
  const pairs = Math.max(1, model.frames.length - 1);
  const changeRatio = r2(changing / pairs);
  const longestStaticS = r2((longest - 1) * model.step);
  // A freeze on the END CARD is correct film grammar (the final frame holds so the result reads);
  // dead air mid-film is not.
  const staticAtEnd = longestEnd >= dur - model.step * 1.5;
  if (longestStaticS >= T.MAX_STATIC_RUN_S && !staticAtEnd) {
    findings.push({
      sev: "WARN", code: "motion.static-run", at: r2(longestAt),
      msg: `${longestStaticS}s of pixel-identical frames from ${r2(longestAt)}s, mid-film — nothing at all moves there.`,
    });
  }
  if (changeRatio < T.MIN_CHANGING_FRAMES) {
    findings.push({
      sev: "ERROR", code: "motion.frozen", at: null,
      msg: `only ${Math.round(changeRatio * 100)}% of sampled frames differ from the one before — the artifact is essentially a still. Motion is measured on rendered frames, not on a registered timeline.`,
    });
  }
  // TRANSITION VARIETY — read the shape of each cut off the ink curve, so "five identical
  // opacity+blur(8px) container crossfades" is a measurement rather than a reading of the
  // source. A dissolve collapses the ink to near zero; a hard cut does not; a wipe holds it.
  const kinds = [];
  for (const c of cuts) {
    const a = Math.max(0, c.startIdx), b = Math.min(model.frames.length - 1, c.endIdx);
    let minInk = Infinity;
    for (let i = a; i <= b; i++) minInk = Math.min(minInk, model.frames[i].ink);
    const outer = Math.max(model.frames[a]?.ink ?? 0, model.frames[b]?.ink ?? 0) || 1;
    const dip = minInk / outer;
    const spanS = r2((b - a) * model.step);
    const kind = dip < 0.25 ? "dissolve" : spanS <= model.step * 2 ? "cut" : "wipe";
    kinds.push({ t: r2(c.t), kind, spanS, dip: r2(dip) });
  }
  if (kinds.length >= 3) {
    const tally = new Map();
    for (const k of kinds) {
      const key = `${k.kind}/${Math.round(k.spanS * 2) / 2}s`;
      tally.set(key, (tally.get(key) || 0) + 1);
    }
    const [key, count] = [...tally.entries()].sort((a, b) => b[1] - a[1])[0];
    if (count >= 3 && count / kinds.length >= 0.7) {
      findings.push({
        sev: "WARN", code: "motion.one-transition", at: null,
        msg: `${count} of ${kinds.length} transitions are the same shape (${key}) — every cut lands the same way, so none of them mean anything. Vary the transition with the beat.`,
      });
    }
  }

  return { blank, thin, changeRatio, longestStaticS, transitions: kinds, findings };
}

/**
 * LAYOUT — silent clipping and off-stage content, measured, not declared.
 *
 * A shrinkable flex item absorbs overflow by compressing, and its own overflow:hidden then cuts
 * the last of its content off with no error and no warning. stage.scrollHeight -
 * stage.clientHeight must be 0, alongside per-element scrollWidth - clientWidth.
 */
export function analyseLayout(model) {
  const findings = [];
  const so = model.stageOverflow || { x: 0, y: 0 };
  const flexNote = (el) =>
    el.flexItem && !/^0 0 /.test(el.flexRule || "")
      ? ` — it is a shrinkable flex item (flex: ${el.flexRule}); pin every non-spacer child of a fixed-size stage to flex:0 0 auto so an overflow becomes loud instead of eating content.`
      : ".";
  if (so.y > T.MIN_CLIP_PX) {
    findings.push({
      sev: "ERROR", code: "layout.stage-overflow", at: null,
      msg: `the stage's content is ${so.y}px TALLER than the stage (scrollHeight - clientHeight) — that height is being cropped with no error and no warning anywhere else.`,
    });
  } else if (so.x > T.MIN_CLIP_PX) {
    findings.push({
      sev: "WARN", code: "layout.stage-overflow", at: null,
      msg: `the stage's content is ${so.x}px WIDER than the stage (scrollWidth - clientWidth) — something is hanging off the side.`,
    });
  }
  const clipped = [], offStage = [];
  for (const el of model.elements || []) {
    if (el.clipped && (el.clipped.dx > T.MIN_CLIP_PX || el.clipped.dy > T.MIN_CLIP_PX)) {
      clipped.push({ id: el.id, by: el.clipped.by, dx: el.clipped.dx, dy: el.clipped.dy, flexRule: el.flexRule });
      findings.push({
        sev: "ERROR", code: "layout.clipped", at: null,
        msg: `${el.id} is cropped by ${el.clipped.by} (${el.clipped.dx}x${el.clipped.dy}px of it falls outside)${flexNote(el)}`,
      });
    }
    // only a box that CROPS can eat its own content; an element with visible overflow
    // merely overhangs, which the off-stage check covers.
    if (el.ownCrops && (el.selfClipY > T.MIN_CLIP_PX || el.selfClipX > T.MIN_CLIP_PX)) {
      clipped.push({ id: el.id, self: true, dx: el.selfClipX, dy: el.selfClipY, flexRule: el.flexRule });
      findings.push({
        sev: "ERROR", code: "layout.self-clip", at: null,
        msg: `${el.id} silently eats its own content: ${el.selfClipX}x${el.selfClipY}px overflows inside a box whose overflow is cropped${flexNote(el)}`,
      });
    }
    if (el.offStage && (el.offStage.dx > T.MIN_CLIP_PX || el.offStage.dy > T.MIN_CLIP_PX)) {
      offStage.push({ id: el.id, ...el.offStage });
      findings.push({
        sev: "WARN", code: "layout.off-stage", at: null,
        msg: `${el.id} reaches ${el.offStage.dx}x${el.offStage.dy}px outside the ${model.stage.w}x${model.stage.h} stage at its most-visible moment.`,
      });
    }
  }
  // ── collision: two ink-bearing elements drawn on the same pixels, both solid ──
  // Neither the clipping checks nor brand-lint can see this: both elements sit inside their
  // parent and both are "visible", so nothing is cropped and no colour is wrong. It is how a
  // completed-state checkmark ends up on top of the numeral it was meant to replace and reads as
  // one smudged mark.
  //
  // Three exclusions keep this honest, because a check that cries wolf gets switched off:
  // mid-crossfade (both sides must be >=0.9 opacity at probe time), a full-bleed ground under
  // type, and anything the author marked `data-layout-allow-overlap` for a wipe or a
  // deliberate double-exposure. What is left is measured in painted pixels, not boxes.
  const collisions = [];
  for (const c of model.collisions || []) {
    if ((c.ink ?? 0) < T.MIN_COLLISION_INK) continue;
    collisions.push(c);
    const covered = `${Math.round(c.ink * 100)}% of the smaller one's own marks are underneath the other`;
    findings.push(
      c.excused
        ? {
            // The author marked both sides, so this is a wipe or a deliberate double-exposure
            // rather than an accident — but it is still reported, because "I meant to" is a
            // claim about intent and the smudge is a fact about the frame.
            sev: "WARN", code: "layout.collision.allowed", at: c.t,
            msg: `${c.a} and ${c.b} paint the same pixels at ${c.t}s (${covered}); one of them carries data-layout-allow-overlap, so this is taken as deliberate. Look at the frame and confirm it reads as two layers and not one smudge.`,
          }
        : {
            sev: "ERROR", code: "layout.collision", at: c.t,
            msg: `${c.a} and ${c.b} paint the same pixels at ${c.t}s — ${covered}, both fully opaque. That reads as one smudged mark, not two layers. A state that REPLACES something must hide what it replaces, not fade in on top of it; if the overlap is the point, put data-layout-allow-overlap on the element that is MEANT to travel over the others (the cursor, the scrim, the wipe handle).`,
          },
    );
  }

  return { stageOverflow: so, clipped, offStage, collisions, findings };
}

/**
 * HIERARCHY — measured on the type that actually RENDERS, not on how many `font-size:`
 * declarations appear in the source. A black rectangle with two font-size declarations and
 * no visible text used to score full marks here.
 *
 * Type is compared as a % OF FRAME WIDTH so formats compare honestly: 42px on 1920 = 2.2% =
 * ~8.5px on a 390px phone, which is too small; 52px = 2.7% = ~10.5px.
 */
export function analyseHierarchy(model) {
  const findings = [];
  const text = (model.elements || []).filter((e) => e.textLen > 0 && e.fontPx > 0 && e.w * e.h > 0);
  if (!text.length) {
    findings.push({ sev: "ERROR", code: "hierarchy.no-text", at: null, msg: "no element renders visible text at any sampled frame — there is no type hierarchy to judge." });
    return { sizes: [], ratio: 0, distinct: 0, smallestPct: null, findings };
  }
  const byPx = new Map();
  for (const e of text) {
    const px = Math.round(e.fontPx);
    const rec = byPx.get(px) || { px, chars: 0, count: 0 };
    rec.chars += e.textLen; rec.count++;
    byPx.set(px, rec);
  }
  const sizes = [...byPx.values()].sort((a, b) => b.px - a.px);
  const max = sizes[0].px;
  const weighted = [];
  for (const s of sizes) for (let i = 0; i < s.count; i++) weighted.push(s.px);
  weighted.sort((a, b) => a - b);
  const median = weighted[Math.floor(weighted.length / 2)];
  const ratio = r2(max / Math.max(1, median));
  const distinct = sizes.length;

  if (distinct < 2) {
    findings.push({ sev: "ERROR", code: "hierarchy.flat", at: null, msg: `every rendered string is ${max}px — no hierarchy at all (eyebrow / headline / body should not be one size).` });
  } else if (ratio < 1.8) {
    findings.push({ sev: "WARN", code: "hierarchy.weak", at: null, msg: `largest rendered type is only ${ratio}x the median (${max}px vs ${median}px) — no element is clearly the focal one.` });
  }
  // the largest size should be a FOCUS, not the body
  const focalChars = sizes[0].chars;
  const totalChars = sizes.reduce((a, s) => a + s.chars, 0);
  if (distinct >= 2 && focalChars / totalChars > 0.6) {
    findings.push({ sev: "WARN", code: "hierarchy.no-focus", at: null, msg: `${Math.round((focalChars / totalChars) * 100)}% of the rendered characters are set at the largest size — nothing reads as the focal element.` });
  }
  // A stray micro-label is not the defect; a BODY set below the legible floor is.
  const bodySizes = sizes.filter((s) => s.chars / totalChars >= T.MIN_SIZE_SHARE);
  const smallest = (bodySizes.length ? bodySizes : sizes)[(bodySizes.length ? bodySizes : sizes).length - 1].px;
  const smallestPct = r2((smallest / model.stage.w) * 100);
  if (smallestPct < 1.2) {
    findings.push({ sev: "WARN", code: "hierarchy.illegible", at: null, msg: `the body type carrying most of the copy renders at ${smallest}px = ${smallestPct}% of frame width (~${r2((smallest / model.stage.w) * 390)}px on a 390px phone) — below the legible floor for video.` });
  }
  return { sizes: sizes.map((s) => ({ px: s.px, chars: s.chars })), ratio, distinct, smallestPct, findings };
}

/** LOAD — a page that errored or failed to fetch an asset did not render the artifact. */
export function analyseLoad(model) {
  const findings = [];
  const l = model.load || {};
  for (const e of (l.pageErrors || []).slice(0, 3)) findings.push({ sev: "ERROR", code: "load.page-error", at: null, msg: `page error during render: ${e}` });
  for (const u of (l.failedRequests || []).slice(0, 3)) findings.push({ sev: "ERROR", code: "load.failed-request", at: null, msg: `asset failed to load: ${u}` });
  for (const u of (l.brokenImages || []).slice(0, 3)) findings.push({ sev: "ERROR", code: "load.broken-image", at: null, msg: `<img> never decoded: ${u}` });
  if (model.timeline && model.timeline.paused === false) {
    findings.push({ sev: "ERROR", code: "load.timeline-running", at: null, msg: "the registered timeline is NOT paused — a seek-driven renderer must own playback (gsap.timeline({paused:true}))." });
  }
  // HyperFrames renders duration*fps frames EXCLUDING t=duration, so anything the timeline
  // schedules past `data-duration` is authored motion that is never captured.
  const over = r2((model.timelineDuration || 0) - model.duration);
  if (over > 0.02) {
    findings.push({
      sev: "WARN", code: "load.tween-past-duration", at: null,
      msg: `the timeline runs ${over}s past data-duration=${model.duration}s — that motion is authored but never rendered. Trim the tween or raise data-duration.`,
    });
  }
  return { findings, overrun: over };
}

/**
 * Re-analyse a recorded model (`film-probe --out model.json`) without re-probing:
 *   node tools/film-analysis.mjs <model.json> [--json]
 * The probe is the slow, environment-dependent half; this half is pure, so a recorded model
 * is a durable regression fixture.
 */
export function analyseFilm(model) {
  const { scenes, cuts } = segmentScenes(model);
  const load = analyseLoad(model);
  const continuity = analyseContinuity(model, cuts);
  const development = analyseDevelopment(model, scenes);
  const frames = analyseFrames(model, cuts);
  const layout = analyseLayout(model);
  const hierarchy = analyseHierarchy(model);
  const findings = [
    ...load.findings, ...frames.findings, ...continuity.findings,
    ...development.findings, ...layout.findings, ...hierarchy.findings,
  ];
  return {
    file: model.file, duration: model.duration, sceneCount: scenes.length, cutCount: cuts.length,
    scenes: scenes.map((s) => ({ start: r2(s.start), end: r2(s.end), clipId: s.clipId })),
    load, continuity, development, frames, layout, hierarchy,
    findings,
    errors: findings.filter((f) => f.sev === "ERROR").length,
    warnings: findings.filter((f) => f.sev === "WARN").length,
  };
}

// ── CLI ──────────────────────────────────────────────────────────────────────
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { EXIT, ToolingError, WORKSPACE, confined, isMain, parseFlags, requireFile, runCli } from "./toolchain.mjs";

if (isMain(import.meta.url)) {
  await runCli("film-analysis", async () => {
    const { flags, positionals } = parseFlags(process.argv.slice(2), { values: ["root"], booleans: ["json"] });
    if (positionals.length !== 1) throw new ToolingError("usage: film-analysis.mjs <model.json> [--json]");
    const file = requireFile(confined(resolve(flags.root || WORKSPACE), positionals[0], "model"), "model");
    let model;
    try {
      model = JSON.parse(readFileSync(file, "utf8"));
    } catch (error) {
      throw new ToolingError(`${positionals[0]} is not a film model (${error.message})`);
    }
    if (!Array.isArray(model?.times) || !Array.isArray(model?.vis) || !Array.isArray(model?.frames)) {
      throw new ToolingError(`${positionals[0]} is not a film-probe model (times, vis and frames are required)`);
    }
    const rep = analyseFilm(model);
    if (flags.json) console.log(JSON.stringify(rep));
    else {
      console.log(`film-analysis: ${rep.file} · ${rep.sceneCount} shot(s) · ${rep.cutCount} cut(s) · ${rep.errors} error(s), ${rep.warnings} warning(s)`);
      for (const f of rep.findings) console.log(`  ${f.sev === "ERROR" ? "✗" : "⚠"} [${f.code}]${f.at != null ? ` @${f.at}s` : ""} ${f.msg}`);
    }
    return rep.errors ? EXIT.FINDINGS : EXIT.PASS;
  });
}
