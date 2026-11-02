// Pure-logic tests for the film-breakdown, sound, thumbnails and image-ops scripts: `node --test`,
// no toolchain, no ffmpeg.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const SKILLS = join(ROOT, "skills");
const { detectCuts } = await import(join(SKILLS, "film-breakdown", "scripts", "lib", "cuts.mjs"));
const { timeOf, frameAt } = await import(join(SKILLS, "film-breakdown", "scripts", "lib", "media.mjs"));
const { automation, scoredPath } = await import(join(SKILLS, "sound", "scripts", "score-video.mjs"));
const { renderSynth, SYNTH_RECIPES } = await import(join(SKILLS, "sound", "scripts", "synth-cue.mjs"));
const { resolveFile, resolveSynth } = await import(join(SKILLS, "sound", "scripts", "resolve.mjs"));
const { readComp, contrastRatio, relativeLuminance } = await import(join(SKILLS, "thumbnails", "scripts", "thumb-gate.mjs"));

test("frame maths stays on the rational grid", () => {
  const ntsc = { num: 30000, den: 1001, fpsValue: 30000 / 1001 };
  assert.equal(frameAt(timeOf(223, ntsc), ntsc), 223);
  assert.equal(frameAt(1, ntsc), 30);
});

test("a hard cut is found and a dissolve is not", () => {
  const n = 90;
  const F = { d: Array(n).fill(1), d2: Array(n).fill(2), scene: Array(n).fill(0.01), hd: Array(n).fill(0), mc: Array(n).fill(1), rho: Array(n).fill(0.99), y: Array(n).fill(120) };
  // Frame 60 replaces the picture: a spike against its neighbours, and as far from frame 58 as from 59.
  F.d[60] = 60; F.d2[60] = 60; F.d2[61] = 60; F.scene[60] = 0.9; F.rho[60] = 0.2;
  // Frames 20-24 dissolve: each sits halfway between its neighbours.
  for (let i = 20; i <= 24; i++) { F.d[i] = 8; F.d2[i] = 16; F.d2[i + 1] = 16; F.scene[i] = 0.2; }
  const { cuts, transitions } = detectCuts(F, { num: 30, den: 1, fpsValue: 30 });
  assert.deepEqual(cuts.map((c) => c.n), [60]);
  assert.ok(transitions.some((t) => t.n >= 20 && t.n <= 24 && t.kind === "blend"));
});

test("bed automation follows cue intents and the scored file is named from the plan", () => {
  const autos = automation([
    { intent: "riser", t_start_s: 2, dur_s: 1 },
    { intent: "transition", t_start_s: 5, dur_s: 0.3 },
    { intent: "ui-tick", t_start_s: 6, dur_s: 0.1 },
  ]);
  assert.deepEqual(autos.map((a) => [a.t0, a.t1]), [[2, 3], [4.7, 5]]);
  assert.equal(scoredPath("/w/p/film-silent.mp4", "plan.json"), "/w/p/film-scored.mp4");
  assert.equal(scoredPath("/w/p/film.mp4", "plan-alt.json"), "/w/p/film-scored-alt.mp4");
});

test("synth cues are deterministic WAVs", () => {
  const dir = mkdtempSync(join(tmpdir(), "synth-"));
  for (const recipe of SYNTH_RECIPES) {
    renderSynth(recipe, join(dir, `${recipe}-1.wav`));
    renderSynth(recipe, join(dir, `${recipe}-2.wav`));
    const a = readFileSync(join(dir, `${recipe}-1.wav`));
    assert.deepEqual(a, readFileSync(join(dir, `${recipe}-2.wav`)), recipe);
    assert.equal(a.toString("ascii", 0, 4), "RIFF");
    assert.equal(a.readUInt32LE(24), 44100);
  }
  assert.throws(() => renderSynth("nope", join(dir, "x.wav")), /unknown synth recipe/);
});

test("the sound resolver only reads slug-named files inside the job's assets", () => {
  const assets = mkdtempSync(join(tmpdir(), "assets-"));
  mkdirSync(join(assets, "sfx"));
  writeFileSync(join(assets, "sfx", "hit.wav"), "x");
  assert.ok(resolveFile({ assetsDir: assets, kind: "sfx", file: "sfx/hit.wav", source: "supplied" }));
  assert.equal(resolveFile({ assetsDir: assets, kind: "sfx", file: "../sfx/hit.wav", source: "supplied" }), null);
  assert.equal(resolveFile({ assetsDir: assets, kind: "music", file: "sfx/hit.wav", source: "supplied" }), null);
  assert.equal(resolveFile({ assetsDir: assets, kind: "sfx", file: "sfx/hit.wav", source: "somewhere" }), null);
  assert.equal(resolveSynth({ assetsDir: assets, recipe: "../../etc" }), null);
  assert.ok(resolveSynth({ assetsDir: assets, recipe: "ui-tick" }));
  const ledger = JSON.parse(readFileSync(join(assets, "ledger.json"), "utf8"));
  assert.deepEqual(ledger.map((e) => e.source).sort(), ["supplied", "synth"]);
});

test("the thumbnail gate reads the hero from the comp without a browser", () => {
  const comp = readComp(`<style>.t{font:600 96px/1.05 'Brand Display';left:80px;top:120px;width:640px;height:220px}</style>
    <h1 class="t" data-thumb-role="hero">Ship it <em>today</em></h1><img src="shot.png" style="width:900px">`);
  assert.deepEqual(comp.hero.words, ["Ship", "it", "today"]);
  assert.equal(comp.hero.fontSize, 96);
  assert.equal(comp.hero.fontWeight, 600);
  assert.deepEqual(comp.hero.box, { left: 80, top: 120, width: 640, height: 220 });
  assert.deepEqual(comp.rasters.map((r) => [r.ref, r.width]), [["shot.png", 900]]);
  assert.ok(Math.abs(contrastRatio(relativeLuminance(0, 0, 0), relativeLuminance(255, 255, 255)) - 21) < 1e-9);
});

test("image-ops refuses bad arguments as a tooling failure (exit 2) with help", () => {
  const img = join(SKILLS, "image-ops", "scripts", "img.mjs");
  const none = spawnSync(process.execPath, [img], { encoding: "utf8" });
  assert.equal(none.status, 2);
  assert.match(none.stdout, /--resize/);
  const missing = spawnSync(process.execPath, [img, "/no/such/file.png", "out.png"], { encoding: "utf8" });
  assert.equal(missing.status, 2);
  assert.match(missing.stderr, /input not found/);
});
