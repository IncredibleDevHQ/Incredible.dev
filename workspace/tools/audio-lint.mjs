#!/usr/bin/env node
// audio-lint.mjs — the deterministic half of audio QA: levels and length, which a model cannot judge
// by listening.
//
// Measures a media file's integrated loudness and true peak with ffmpeg's EBU R128 meter and checks
// them against the master target (default -14 ±1 LUFS, true peak ≤ -1 dBTP), and optionally that the
// audio runs as long as it should.
//
// Usage:
//   node /workspace/tools/audio-lint.mjs <media file> [--target-lufs -14] [--tolerance 1]
//        [--max-true-peak -1] [--expect-duration <seconds>] [--duration-tolerance 0.05] [--json]
// ffmpeg and ffprobe run with argument arrays, never a shell. Relative paths resolve against --root
// (default: the folder holding tools/, i.e. /workspace) and nothing outside it is read.
// Exit: 0 within target · 1 out of range, no audio stream, or wrong length · 2 the meter could not run.

import { spawnSync } from "node:child_process";
import { relative, resolve } from "node:path";
import { EXIT, ToolingError, WORKSPACE, confined, parseFlags, requireFile, runCli } from "./toolchain.mjs";

function run(binary, args) {
  const result = spawnSync(binary, args, { encoding: "utf8", maxBuffer: 64 * 1024 * 1024 });
  if (result.error?.code === "ENOENT") throw new ToolingError(`${binary} is not installed (run inside the sandbox image)`);
  if (result.error) throw new ToolingError(`${binary} failed: ${result.error.message}`);
  return result;
}

function number(flags, name, fallback) {
  const value = Number(flags[name] ?? fallback);
  if (!Number.isFinite(value)) throw new ToolingError(`--${name} must be a number`);
  return value;
}

/** The audio stream's duration in seconds, or null when the file has no audio stream. */
function audioDuration(file) {
  const probe = run("ffprobe", ["-v", "error", "-select_streams", "a:0", "-show_entries", "stream=duration:format=duration", "-of", "json", file]);
  if (probe.status !== 0) throw new ToolingError(`ffprobe could not read the file: ${(probe.stderr || "").trim().split("\n")[0]}`);
  const info = JSON.parse(probe.stdout || "{}");
  if (!info.streams?.length) return null;
  return Number(info.streams[0].duration ?? info.format?.duration);
}

await runCli("audio-lint", async () => {
  const { flags, positionals } = parseFlags(process.argv.slice(2), {
    values: ["target-lufs", "tolerance", "max-true-peak", "expect-duration", "duration-tolerance", "root"],
    booleans: ["json"],
  });
  if (positionals.length !== 1) throw new ToolingError("usage: audio-lint.mjs <media file> [--target-lufs -14] [--expect-duration S] [--json]");
  const root = resolve(flags.root || WORKSPACE);
  const file = requireFile(confined(root, positionals[0], "media file"), "media file");
  const rel = relative(root, file);
  const target = number(flags, "target-lufs", -14);
  const tolerance = number(flags, "tolerance", 1);
  const ceiling = number(flags, "max-true-peak", -1);
  const expected = flags["expect-duration"] === undefined ? null : number(flags, "expect-duration");
  const durationTolerance = number(flags, "duration-tolerance", 0.05);

  const report = { ok: false, file: rel, target: { lufs: target, tolerance, maxTruePeak: ceiling }, findings: [] };
  const duration = audioDuration(file);
  if (duration === null) {
    report.findings.push("no audio stream");
  } else {
    report.duration = duration;
    const meter = run("ffmpeg", ["-nostdin", "-hide_banner", "-i", file, "-map", "0:a:0", "-af", "ebur128=peak=true", "-f", "null", "-"]);
    const summary = (meter.stderr || "").slice((meter.stderr || "").lastIndexOf("Summary:"));
    const integrated = /Integrated loudness:[\s\S]*?I:\s*(-?[\d.]+|-inf)\s*LUFS/.exec(summary)?.[1];
    const peak = /True peak:[\s\S]*?Peak:\s*(-?[\d.]+|-inf)\s*dBFS/.exec(summary)?.[1];
    if (meter.status !== 0 || integrated === undefined || peak === undefined) {
      throw new ToolingError(`the loudness meter did not run: ${(meter.stderr || "").trim().split("\n").at(-1)}`);
    }
    const lufs = integrated === "-inf" ? -Infinity : Number(integrated);
    const truePeak = peak === "-inf" ? -Infinity : Number(peak);
    Object.assign(report, { lufs, truePeak });
    if (!(lufs >= target - tolerance && lufs <= target + tolerance)) {
      report.findings.push(`integrated loudness ${lufs} LUFS is outside ${target} ±${tolerance} LUFS`);
    }
    // The meter prints one decimal place; allow that rounding step over the ceiling.
    if (!(truePeak <= ceiling + 0.1)) report.findings.push(`true peak ${truePeak} dBTP is over the ${ceiling} dBTP ceiling`);
    if (expected !== null && !(Math.abs(duration - expected) <= durationTolerance)) {
      report.findings.push(`audio runs ${duration}s, expected ${expected}s (±${durationTolerance}s)`);
    }
  }
  report.ok = report.findings.length === 0;
  if (flags.json) {
    console.log(JSON.stringify(report));
  } else {
    console.log(`audio-lint: ${rel}  ·  I=${report.lufs ?? "n/a"} LUFS · true peak=${report.truePeak ?? "n/a"} dBTP · ${report.duration ?? "n/a"}s`);
    if (report.ok) console.log(`  ✅ within ${target} ±${tolerance} LUFS / ≤ ${ceiling} dBTP`);
    for (const finding of report.findings) console.log(`  ✗ ${finding}`);
    if (!report.ok) console.log("✋ audio-lint FAILED — re-master before delivery.");
  }
  return report.ok ? EXIT.PASS : EXIT.FINDINGS;
});
