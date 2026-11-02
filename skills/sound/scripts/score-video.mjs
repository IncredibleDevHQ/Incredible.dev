#!/usr/bin/env node
// score-video.mjs: the plan-driven mixer. Resolves the bed, cues and voiceover lines (resolve.mjs),
// places them on the timeline, derives music automation from cue intents, levels the voice and ducks
// the bed under it, masters the mix (master.mjs: -14 LUFS integrated, true peak under -1 dBTP) and
// muxes it onto the silent render as <video>-scored[-<plan suffix>].mp4.
//
//   node score-video.mjs <jobDir> [planFile]
//
// ffmpeg runs from argument arrays; every file a plan names is confined to <jobDir>/sound-assets.

import { spawnSync } from "node:child_process";
import { mkdirSync, readFileSync, rmSync } from "node:fs";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { master } from "./master.mjs";
import { repoRoot } from "./repo-root.mjs";
import { FILE_SOURCES, resolveFile, resolveSynth } from "./resolve.mjs";

// The voice leads: every line is levelled to VO_LUFS so no take jumps out, the bed sits BED_UNDER_VO
// dB under it and dips about 2 dB more while a word is spoken. A cue at gain 1.0 peaks SFX_OVER_VO dB
// against the voice level whatever its source, so effects support the voice rather than cover it.
const VO_LUFS = -16;
const BED_UNDER_VO = 3;
const SFX_OVER_VO = -2;
// Lossy AAC adds true peak, so the master leaves headroom under the -1 dBTP delivery ceiling.
const MASTER = { target: -14, truePeak: -1.5, lra: 11 };

export function scoredPath(video, planFile) {
  const suffix = basename(planFile, ".json").replace(/^plan/, "").replace(/^[-_]/, "");
  const stem = basename(video).replace(/-silent(?=\.mp4$)/, "").replace(/\.mp4$/, "");
  return join(dirname(video), `${stem}-scored${suffix ? `-${suffix}` : ""}.mp4`);
}

/** Bed automation from cue intents: a dip before a hit, a duck under risers, shimmers and stings. */
export function automation(cues) {
  const autos = [];
  for (const q of cues) {
    const t0 = q.t_start_s;
    const t1 = q.t_start_s + q.dur_s;
    // A riser leads into its cut, so the bed ducks under the riser itself, not before it.
    if (/riser|swell/i.test(q.intent)) autos.push({ t0, t1, d: 0.35, why: `duck under ${q.intent}` });
    else if (/swoosh|hero|transition|turn|flash/i.test(q.intent)) autos.push({ t0: t0 - 0.3, t1: t0, d: 0.92, why: `hold before ${q.intent}` });
    else if (/shimmer|chime|reveal|bloom/i.test(q.intent)) autos.push({ t0: t0 - 0.2, t1, d: 0.35, why: `duck under ${q.intent}` });
    else if (/sting|signature|logo/i.test(q.intent)) autos.push({ t0: t0 - 0.2, t1, d: 0.45, why: `duck under ${q.intent}` });
  }
  return autos.map((a) => ({ ...a, t0: Number(Math.max(0, a.t0).toFixed(2)), t1: Number(a.t1.toFixed(2)) }));
}

const ff = (args) => spawnSync("ffmpeg", ["-nostdin", ...args], { encoding: "utf8", maxBuffer: 256 * 1024 * 1024 });
const lufs = (s) => {
  const m = (s || "").match(/Integrated loudness:[\s\S]*?I:\s*(-?[\d.]+)\s*LUFS/);
  return m ? parseFloat(m[1]) : null;
};
const fileLufs = (f) => lufs(ff(["-i", f, "-af", "ebur128", "-f", "null", "-"]).stderr);
// The loudest 400 ms of a file (EBU R128 momentary), padded so a click shorter than the window is
// measured the same way every time: what a cue sounds like at its peak.
const maxMomentary = (f) => {
  const seen = [...(ff(["-i", f, "-af", "apad=pad_dur=0.5,ebur128", "-f", "null", "-"]).stderr || "").matchAll(/\bM:\s*(-?[\d.]+)/g)].map((m) => parseFloat(m[1]));
  return seen.length ? Math.max(...seen) : null;
};

function main(jobArg, planFile) {
  const REPO = repoRoot(import.meta.url);
  const jobDir = resolve(REPO, jobArg);
  const plan = JSON.parse(readFileSync(join(jobDir, planFile), "utf8"));
  const A = join(jobDir, "sound-assets");
  mkdirSync(A, { recursive: true });
  const DUR = plan.video.duration_s;

  const beds = [];
  for (const m of plan.music || []) {
    const f = resolveFile({ assetsDir: A, kind: "music", file: m.selected?.file, title: m.selected?.title, prompt: m.selected?.prompt, source: m.selected?.source });
    if (f) beds.push({ ...m, file: f });
    else console.warn(`  bed ${m.act ?? ""}: unresolved (source one of ${FILE_SOURCES.join(", ")}, file music/<slug>.mp3|wav), skip`);
  }
  const cues = [];
  for (const q of plan.sfx_cues || []) {
    const f = q.source === "synth"
      ? resolveSynth({ assetsDir: A, recipe: q.recipe })
      : resolveFile({ assetsDir: A, kind: "sfx", file: q.file, title: q.description, prompt: q.prompt, source: q.source });
    if (f) cues.push({ ...q, file: f });
    else console.warn(`  ${q.intent}: unresolved, skip`);
  }
  const vo = [];
  for (const v of plan.vo || []) {
    const f = resolveFile({ assetsDir: A, kind: "vo", file: v.file, title: v.text, source: v.source || "elevenlabs" });
    if (f) vo.push({ ...v, file: f });
    else console.warn(`  vo @${v.start_s}s: unresolved, skip`);
  }
  console.log(`resolved: ${beds.length} bed(s), ${cues.length}/${(plan.sfx_cues || []).length} cues, ${vo.length}/${(plan.vo || []).length} voice lines`);

  const autos = automation(cues);
  const musicVol = "1" + autos.map((a) => `-${a.d}*between(t,${a.t0},${a.t1})`).join("");
  for (const a of autos) console.log(`  ${a.t0}-${a.t1}s  x${(1 - a.d).toFixed(2)}  (${a.why})`);

  const inputs = [];
  beds.forEach((b) => inputs.push("-i", b.file));
  cues.forEach((q) => inputs.push("-i", q.file));
  vo.forEach((v) => inputs.push("-i", v.file));
  const bedTrim = beds.map((b) => {
    if (!vo.length) return "volume=0.42";
    const measured = fileLufs(b.file);
    return measured == null ? "volume=0.42" : `volume=${(VO_LUFS - BED_UNDER_VO - measured).toFixed(2)}dB`;
  });
  const voTrim = vo.map((v) => {
    const measured = fileLufs(v.file);
    return measured == null ? 0 : VO_LUFS - measured;
  });
  const cueTrim = cues.map((q) => {
    const measured = maxMomentary(q.file);
    return measured == null ? 0 : VO_LUFS + SFX_OVER_VO - measured;
  });

  const chains = [];
  beds.forEach((b, i) => {
    if (b.start_s > 0) {
      const win = DUR - b.start_s;
      chains.push(`[${i}:a]atrim=0:${win.toFixed(2)},afade=t=in:st=0:d=${b.crossfade_in_s || 1.8},afade=t=out:st=${(win - 0.8).toFixed(2)}:d=0.8,${bedTrim[i]},adelay=${Math.round(b.start_s * 1000)}:all=1[bd${i}]`);
    } else {
      chains.push(`[${i}:a]atrim=0:${b.end_s},afade=t=in:st=0:d=0.4,afade=t=out:st=${(b.end_s - (b.crossfade_out_s || 2)).toFixed(2)}:d=${b.crossfade_out_s || 2},${bedTrim[i]}[bd${i}]`);
    }
  });
  if (beds.length) {
    chains.push(`${beds.map((_, i) => `[bd${i}]`).join("")}amix=inputs=${beds.length}:normalize=0:dropout_transition=0,aformat=sample_rates=48000:channel_layouts=stereo[mraw];[mraw]volume=volume='${musicVol}':eval=frame[music]`);
  } else {
    chains.push(`anullsrc=r=48000:cl=stereo,atrim=0:${DUR}[music]`);
  }
  cues.forEach((q, i) => chains.push(`[${beds.length + i}:a]adelay=${Math.round(q.t_start_s * 1000)}:all=1,volume=${cueTrim[i].toFixed(2)}dB,volume=${q.gain ?? 1}[s${i}]`));
  let musicBus = "[music]";
  if (vo.length) {
    const base = beds.length + cues.length;
    vo.forEach((v, j) => chains.push(`[${base + j}:a]aformat=sample_rates=48000:channel_layouts=stereo,volume=${voTrim[j].toFixed(2)}dB,adelay=${Math.round(v.start_s * 1000)}:all=1[v${j}]`));
    chains.push(`${vo.map((_, j) => `[v${j}]`).join("")}amix=inputs=${vo.length}:normalize=0:dropout_transition=0,apad=whole_dur=${DUR}[voall];[voall]asplit=2[vo][vokey]`);
    // About 2 dB of gain reduction on the bed while a line is spoken, released over ~0.45 s.
    chains.push("[music][vokey]sidechaincompress=threshold=0.05:ratio=1.4:attack=20:release=450:knee=6[musicd]");
    musicBus = "[musicd]";
  }
  const mixLabels = musicBus + cues.map((_, i) => `[s${i}]`).join("") + (vo.length ? "[vo]" : "");
  chains.push(`${mixLabels}amix=inputs=${1 + cues.length + (vo.length ? 1 : 0)}:normalize=0:dropout_transition=0[premix];[premix]apad=whole_dur=${DUR},atrim=0:${DUR}[m]`);

  const premix = join(A, "_premix.wav");
  let r = ff([...inputs, "-filter_complex", chains.join(";"), "-map", "[m]", "-c:a", "pcm_f32le", "-ar", "48000", "-ac", "2", "-y", premix]);
  if (r.status !== 0) throw new Error(`mix failed: ${(r.stderr || "").slice(-1200)}`);
  const wav = join(A, "audio.wav");
  const mastered = master(premix, wav, MASTER);
  rmSync(premix, { force: true });
  console.log(`master: ${mastered.input.i} LUFS in -> ${mastered.result.i} LUFS, ${mastered.result.tp} dBTP (${mastered.mode})`);

  const video = resolve(REPO, plan.video.path);
  const out = scoredPath(video, planFile);
  r = ff(["-i", video, "-i", wav, "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "256k", "-shortest", "-y", out]);
  if (r.status !== 0) throw new Error(`mux failed: ${(r.stderr || "").slice(-800)}`);
  if (vo.length && cues.length) {
    console.log("cue peaks against the voice:");
    for (const q of cues) {
      const at = SFX_OVER_VO + 20 * Math.log10(Math.max(q.gain ?? 1, 1e-3));
      console.log(`  ${at >= 0 ? "+" : ""}${at.toFixed(1)} dB  ${q.intent} @${q.t_start_s}s`);
    }
  }
  console.log(`DONE -> ${out}  (${beds.length} beds + ${cues.length} cues + ${vo.length} voice lines; master ${mastered.ok ? "on" : "OFF"} target)`);
  return mastered.ok;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const [jobArg, planFile = "plan.json"] = process.argv.slice(2);
  if (!jobArg) {
    console.error("usage: node score-video.mjs <jobDir> [planFile]");
    process.exit(2);
  }
  try {
    process.exitCode = main(jobArg, planFile) ? 0 : 1;
  } catch (error) {
    console.error(`score-video: ${error.message}`);
    process.exitCode = 2;
  }
}
