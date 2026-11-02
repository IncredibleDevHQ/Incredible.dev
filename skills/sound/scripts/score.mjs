#!/usr/bin/env node
// score.mjs: the whole sound pass in one command, gates wired in order:
//   score-video (resolve, mix, master, mux) -> audio-lint (loudness, clipping, duration)
// A failed stage stops the run with a non-zero exit and a per-stage summary.
//
//   node score.mjs <jobDir> [planFile]
//
// Every stage is a child process called with an argument array (no shell, no interpolated paths).

import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { repoRoot, workspacePath } from "./repo-root.mjs";
import { scoredPath } from "./score-video.mjs";

const REPO = repoRoot(import.meta.url);
const HERE = dirname(fileURLToPath(import.meta.url));
const [jobArg, planFile = "plan.json"] = process.argv.slice(2);
if (!jobArg) {
  console.error("usage: node score.mjs <jobDir> [planFile]");
  process.exit(2);
}
const jobDir = resolve(REPO, jobArg);
const plan = JSON.parse(readFileSync(join(jobDir, planFile), "utf8"));
const scored = scoredPath(resolve(REPO, plan.video.path), planFile);

const results = [];
const run = (label, args) => {
  console.log(`\n=== ${label} ===`);
  const ok = spawnSync("node", args, { stdio: "inherit" }).status === 0;
  results.push([label, ok]);
  return ok;
};
const summary = () => {
  console.log("\n--- summary ---");
  for (const [stage, ok] of results) console.log(`  ${ok ? "ok  " : "FAIL"} ${stage}`);
};

if (!run("1/2 resolve, mix, master, mux", [join(HERE, "score-video.mjs"), jobArg, planFile])) {
  summary();
  process.exit(1);
}
if (!run("2/2 audio-lint", [workspacePath(REPO, "tools", "audio-lint.mjs"), scored])) {
  summary();
  console.log("\nstopped: audio-lint did not pass (above). Fix the mix or the master before anyone listens.");
  process.exit(1);
}
summary();
console.log(`\nSCORED: ${scored} (${basename(scored)})`);
