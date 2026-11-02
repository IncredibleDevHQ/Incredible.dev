// resolve.mjs: every sound a plan names, as a local file plus a provenance ledger entry.
//
// Sources: files the host tools generated into the job (`generate_voiceover`, `generate_sound_effect`,
// `generate_music`: source "elevenlabs"), files made in the sandbox (source "code"), files supplied
// with the request (source "supplied"), and the synthesized cue library (source "synth"). Nothing is
// fetched: the sandbox holds no keys and the mix never needs the network.
//
// Names are slug-validated and confined to the job's sound-assets folder, so a plan cannot point a
// write or a read anywhere else; ledger writes are atomic (temp file, then rename).

import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { join, resolve, sep } from "node:path";
import { renderSynth, SYNTH_RECIPES } from "./synth-cue.mjs";

const hashFile = (p) => createHash("sha256").update(readFileSync(p)).digest("hex").slice(0, 16);

function confine(root, dest) {
  const r = resolve(root);
  const d = resolve(dest);
  return d === r || d.startsWith(r + sep) ? d : null;
}

function atomicWrite(dest, data) {
  const tmp = `${dest}.${process.pid}.tmp`;
  writeFileSync(tmp, data);
  renameSync(tmp, dest);
}

function ledgerPush(assetsDir, entry) {
  const p = join(assetsDir, "ledger.json");
  let ledger = [];
  if (existsSync(p)) {
    try {
      ledger = JSON.parse(readFileSync(p, "utf8"));
    } catch {
      ledger = [];
    }
  }
  const key = (e) => `${e.kind}:${e.id || e.recipe}`;
  if (!ledger.some((e) => key(e) === key(entry))) ledger.push(entry);
  atomicWrite(p, JSON.stringify(ledger, null, 2) + "\n");
}

const MADE = /^(music|sfx|vo)\/([A-Za-z0-9_-]{1,128})\.(mp3|wav)$/;
const MADE_BY = {
  elevenlabs: { resolved: "host-generated", license: { source: "elevenlabs", generative: true } },
  code: { resolved: "sandbox-made", license: { source: "procedural", generative: false } },
  supplied: { resolved: "supplied", license: { source: "supplied with the request", generative: false } },
};
export const FILE_SOURCES = Object.keys(MADE_BY);

/** A file already in <assetsDir>/<music|sfx|vo>/, named by a slug. Null when it is missing or misnamed. */
export function resolveFile({ assetsDir, kind, file, title, prompt, source = "elevenlabs" }) {
  const m = MADE.exec(file || "");
  const made = MADE_BY[source];
  if (!m || m[1] !== kind || !made) return null;
  const dest = confine(assetsDir, join(assetsDir, file));
  if (!dest || !existsSync(dest)) return null;
  ledgerPush(assetsDir, { kind, source, id: m[2], title, prompt, file, hash: hashFile(dest), resolved: made.resolved, license: made.license });
  return dest;
}

/** A cue from the synthesized library, rendered once into <assetsDir>/sfx/. */
export function resolveSynth({ assetsDir, recipe }) {
  if (!SYNTH_RECIPES.includes(recipe)) return null;
  mkdirSync(join(assetsDir, "sfx"), { recursive: true });
  const dest = confine(assetsDir, join(assetsDir, "sfx", `synth-${recipe}.wav`));
  if (!dest) return null;
  if (!existsSync(dest)) renderSynth(recipe, dest);
  ledgerPush(assetsDir, { kind: "sfx", source: "synth", recipe, file: `sfx/synth-${recipe}.wav`, hash: hashFile(dest),
    license: { source: "synthesized", generative: false, deterministic: true } });
  return dest;
}
