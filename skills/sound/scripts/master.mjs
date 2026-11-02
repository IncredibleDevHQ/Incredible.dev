#!/usr/bin/env node
// master.mjs: master a mix to a loudness target with two-pass ffmpeg loudnorm.
//
//   node master.mjs <input audio|video> <output> [--target -14] [--true-peak -1] [--lra 11]
//
// Pass one measures the input (integrated loudness, true peak, loudness range, threshold); pass two
// applies loudnorm with those measurements, linear when the target allows it (one gain for the whole
// file, so the mix keeps its dynamics), dynamic otherwise. Dynamic mode converges slowly and lands
// short of the target on clips of a few seconds, so when the result misses by more than half a LU a
// trim pass applies the remaining static gain through a 4x-oversampled true-peak limiter. The output
// is measured with ebur128 and true peak, so the numbers printed are what the file is.
//
// Output by extension: .wav (24-bit PCM, 48 kHz), .mp3 (320 kbps), .m4a/.aac (AAC 256 kbps), or
// .mp4/.mov/.webm (the input's video stream copied, AAC audio). Lossy encoders add a few tenths of a
// dB of true peak, so master to a slightly lower --true-peak when the delivery is lossy.
//
// Prints one JSON line: {"ok","output","mode","target":{i,tp,lra},"input":{i,tp,lra},"result":{i,tp,lra}}.
// Exit 0 within ±1 LU of the target and at or under the true-peak ceiling · 1 written but off target
// (the JSON says by how much) · 2 bad arguments, a missing input or ffmpeg failed.

import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, extname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const FFMPEG = process.env.DESIGN_AGENT_FFMPEG || "ffmpeg";

export class MasterError extends Error {}

function ffmpeg(args) {
  const run = spawnSync(FFMPEG, ["-hide_banner", "-nostdin", ...args], { encoding: "utf8", maxBuffer: 1 << 28 });
  if (run.error) throw new MasterError(`ffmpeg could not run (${run.error.code || run.error.message})`);
  if (run.status !== 0) throw new MasterError(`ffmpeg failed: ${(run.stderr || "").trim().split("\n").slice(-3).join(" ")}`);
  return run.stderr || "";
}

/** The last {...} block loudnorm prints with print_format=json. */
function loudnormJson(stderr) {
  const start = stderr.lastIndexOf("{");
  const end = stderr.lastIndexOf("}");
  if (start < 0 || end < start) throw new MasterError("loudnorm printed no measurement");
  return JSON.parse(stderr.slice(start, end + 1));
}

/** Integrated loudness, true peak and loudness range of a file, from ebur128's summary. */
export function measure(file) {
  const stderr = ffmpeg(["-i", file, "-vn", "-af", "ebur128=peak=true", "-f", "null", "-"]);
  const summary = stderr.slice(stderr.lastIndexOf("Summary:"));
  const num = (re) => {
    const m = re.exec(summary);
    return m ? Number(m[1]) : null;
  };
  const i = num(/I:\s*(-?[\d.]+|-inf)\s*LUFS/);
  const lra = num(/LRA:\s*(-?[\d.]+)\s*LU/);
  const tp = num(/True peak:\s*Peak:\s*(-?[\d.]+|-inf)\s*dBFS/);
  if (i === null) throw new MasterError(`could not measure loudness of ${file}`);
  return { i, tp, lra };
}

const CODECS = {
  ".wav": ["-c:a", "pcm_s24le"],
  ".mp3": ["-c:a", "libmp3lame", "-b:a", "320k"],
  ".m4a": ["-c:a", "aac", "-b:a", "256k"],
  ".aac": ["-c:a", "aac", "-b:a", "256k"],
};
const VIDEO = new Set([".mp4", ".mov", ".webm", ".mkv"]);

export function master(input, output, { target = -14, truePeak = -1, lra = 11 } = {}) {
  if (!existsSync(input)) throw new MasterError(`input not found: ${input}`);
  const ext = extname(output).toLowerCase();
  if (!CODECS[ext] && !VIDEO.has(ext)) throw new MasterError(`unsupported output type ${ext || "(none)"}`);
  const base = `I=${target}:TP=${truePeak}:LRA=${lra}`;
  const first = loudnormJson(ffmpeg(["-i", input, "-vn", "-af", `loudnorm=${base}:print_format=json`, "-f", "null", "-"]));
  if (!Number.isFinite(Number(first.input_i)) || Number(first.input_i) < -70) {
    throw new MasterError(`the input is silent (${first.input_i} LUFS): nothing to master`);
  }
  const measured = [
    `measured_I=${first.input_i}`, `measured_TP=${first.input_tp}`, `measured_LRA=${first.input_lra}`,
    `measured_thresh=${first.input_thresh}`, `offset=${first.target_offset}`,
  ].join(":");
  mkdirSync(dirname(resolve(output)), { recursive: true });
  const work = mkdtempSync(join(tmpdir(), "master-"));
  try {
    const normalized = join(work, "normalized.wav");
    const second = loudnormJson(ffmpeg(["-i", input, "-vn", "-af", `loudnorm=${base}:${measured}:linear=true:print_format=json`,
      "-ar", "48000", "-c:a", "pcm_f32le", "-y", normalized]));
    let mode = String(second.normalization_type || "unknown").toLowerCase();
    const after = measure(normalized);
    let filter = "anull";
    if (Math.abs(after.i - target) > 0.5) {
      const ceiling = 10 ** (truePeak / 20);
      filter = `volume=${(target - after.i).toFixed(2)}dB,aresample=192000,alimiter=limit=${ceiling.toFixed(4)}:level=false,aresample=48000`;
      mode += "+trim";
    }
    const encode = ["-af", filter, "-ar", "48000"];
    ffmpeg(VIDEO.has(ext)
      ? ["-i", input, "-i", normalized, "-map", "0:v?", "-map", "1:a:0", "-c:v", "copy", ...encode, "-c:a", "aac", "-b:a", "256k", "-shortest", "-y", output]
      : ["-i", normalized, ...encode, ...CODECS[ext], "-y", output]);
    const result = measure(output);
    const within = Math.abs(result.i - target) <= 1 && (result.tp === null || result.tp <= truePeak + 0.05);
    return {
      ok: within,
      output,
      mode,
      target: { i: target, tp: truePeak, lra },
      input: { i: Number(first.input_i), tp: Number(first.input_tp), lra: Number(first.input_lra) },
      result,
    };
  } finally {
    rmSync(work, { recursive: true, force: true });
  }
}

function cli(argv) {
  const positional = [];
  const flags = {};
  for (let k = 0; k < argv.length; k++) {
    const a = argv[k];
    if (!a.startsWith("--")) positional.push(a);
    else if (["--target", "--true-peak", "--lra"].includes(a) && argv[k + 1] !== undefined) flags[a.slice(2)] = Number(argv[++k]);
    else throw new MasterError(`unknown or incomplete flag ${a}`);
  }
  if (positional.length !== 2) throw new MasterError("usage: master.mjs <input> <output> [--target -14] [--true-peak -1] [--lra 11]");
  const options = { target: flags.target ?? -14, truePeak: flags["true-peak"] ?? -1, lra: flags.lra ?? 11 };
  if (!Object.values(options).every(Number.isFinite)) throw new MasterError("--target, --true-peak and --lra take numbers");
  return master(positional[0], positional[1], options);
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const report = cli(process.argv.slice(2));
    console.log(JSON.stringify(report));
    process.exitCode = report.ok ? 0 : 1;
  } catch (error) {
    console.log(JSON.stringify({ ok: false, error: error.message }));
    process.exitCode = 2;
  }
}
