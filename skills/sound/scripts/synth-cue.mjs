#!/usr/bin/env node
// synth-cue.mjs: a small library of interface sounds made in code, so a film can have UI sound with no
// provider key. One timbral family (sine core, soft octave), so repeated cues read as one instrument.
// Deterministic PCM: the same recipe always writes the same bytes (noise comes from a fixed-seed
// generator, never Math.random).
//
//   node synth-cue.mjs <recipe> <out.wav>      write one cue (44.1 kHz, 16-bit mono WAV)
//   node synth-cue.mjs --list                  the recipes, one JSON line
//
// Recipes: ui-confirm (a settled chime), ui-tick (a short click for each item), ui-soft-in (an element
// arriving), ui-alert (two falling notes), ui-swipe (a soft air movement for a slide or a wipe).
// Exit 0 written · 2 an unknown recipe or bad arguments.

import { writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const SR = 44100;
const TAU = Math.PI * 2;
const tri = (ph) => (2 / Math.PI) * Math.asin(Math.sin(ph));
const clamp = (x) => Math.max(-1, Math.min(1, x));
const buf = (sec) => new Float32Array(Math.round(sec * SR));

function normalize(b, peak) {
  let mx = 0;
  for (const v of b) mx = Math.max(mx, Math.abs(v));
  if (mx < 1e-6) return b;
  const g = peak / mx;
  for (let i = 0; i < b.length; i++) b[i] *= g;
  return b;
}

function tone(sec, freq, decay, octave, peak, edge = 0) {
  const b = buf(sec);
  for (let i = 0; i < b.length; i++) {
    const t = i / SR;
    const e = Math.exp(-t / decay) * Math.min(1, t / 0.003);
    b[i] = (Math.sin(TAU * freq * t) * 0.6 + Math.sin(TAU * freq * 2 * t) * octave + tri(TAU * freq * t) * edge) * e;
  }
  return normalize(b, peak);
}

// A fixed-seed generator (mulberry32) so noise-based cues are byte-identical run to run.
function seeded(seed) {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const RECIPES = {
  "ui-confirm": () => tone(0.22, 660, 0.06, 0.2, 0.6, 0.08),
  "ui-tick": () => tone(0.13, 990, 0.028, 0.2, 0.5),
  "ui-soft-in": () => tone(0.18, 520, 0.05, 0.18, 0.55),
  "ui-alert": () => {
    const a = tone(0.14, 740, 0.05, 0.2, 0.55);
    const b = tone(0.2, 555, 0.07, 0.2, 0.55);
    const out = buf(0.36);
    out.set(a, 0);
    for (let i = 0; i < b.length && i + Math.round(0.14 * SR) < out.length; i++) out[i + Math.round(0.14 * SR)] += b[i];
    return normalize(out, 0.55);
  },
  "ui-swipe": () => {
    const rand = seeded(7);
    const b = buf(0.32);
    let low = 0;
    for (let i = 0; i < b.length; i++) {
      const t = i / b.length;
      const env = Math.sin(Math.PI * t) ** 2;
      // A one-pole low-pass whose cutoff rises then falls reads as air moving past.
      const k = 0.04 + 0.25 * Math.sin(Math.PI * t);
      low += k * (rand() * 2 - 1 - low);
      b[i] = low * env;
    }
    return normalize(b, 0.45);
  },
};

export const SYNTH_RECIPES = Object.keys(RECIPES);

function writeWav(path, s) {
  const n = s.length;
  const b = Buffer.alloc(44 + n * 2);
  b.write("RIFF", 0); b.writeUInt32LE(36 + n * 2, 4); b.write("WAVE", 8);
  b.write("fmt ", 12); b.writeUInt32LE(16, 16); b.writeUInt16LE(1, 20); b.writeUInt16LE(1, 22);
  b.writeUInt32LE(SR, 24); b.writeUInt32LE(SR * 2, 28); b.writeUInt16LE(2, 32); b.writeUInt16LE(16, 34);
  b.write("data", 36); b.writeUInt32LE(n * 2, 40);
  for (let i = 0; i < n; i++) b.writeInt16LE(Math.round(clamp(s[i]) * 32767), 44 + i * 2);
  writeFileSync(path, b);
}

export function renderSynth(recipe, dest) {
  if (!Object.hasOwn(RECIPES, recipe)) throw new Error(`unknown synth recipe ${recipe}; one of ${SYNTH_RECIPES.join(", ")}`);
  const samples = RECIPES[recipe]();
  writeWav(dest, samples);
  return { recipe, file: dest, seconds: Number((samples.length / SR).toFixed(3)) };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const [recipe, out] = process.argv.slice(2);
  if (recipe === "--list") {
    console.log(JSON.stringify({ recipes: SYNTH_RECIPES }));
  } else if (!recipe || !out || !Object.hasOwn(RECIPES, recipe)) {
    console.error(`usage: synth-cue.mjs <${SYNTH_RECIPES.join("|")}> <out.wav> | --list`);
    process.exitCode = 2;
  } else {
    console.log(JSON.stringify({ ok: true, ...renderSynth(recipe, out) }));
  }
}
