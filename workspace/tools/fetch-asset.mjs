#!/usr/bin/env node
// fetch-asset.mjs — download public web assets (images by default, any file with --kind any) into the
// workspace, so a composition references a local file and renders offline. Only a compact JSON line
// per asset reaches the model; the bytes stay a sandbox file.
//
// URLs are untrusted input (often pulled from a page or a message), so the fetch is SSRF-hardened:
//   - scheme allowlist: http and https only;
//   - every address is checked: literal IPs before connecting, and hostnames inside the connection's
//     own DNS lookup, so the address that is checked is the address that is dialled (no rebinding
//     window between a check and the connect). Private, loopback, link-local (including the
//     169.254.169.254 cloud metadata service), CGNAT, multicast, reserved and documentation ranges
//     are refused, and so are IPv6 forms that embed one (mapped, compatible, NAT64, 6to4, Teredo);
//   - redirects are followed by hand, at most --max-redirects, and each hop is checked again;
//   - a hard size cap (Content-Length up front, then streamed), a total timeout, a content-type check,
//     and for images a real decode with sharp;
//   - writes stay under the workspace (--out is confined to --root).
// It connects directly; it does not use an HTTP proxy from the environment.
//
// Usage:
//   node /workspace/tools/fetch-asset.mjs <url> [<url> ...] --out <dir> [--kind image|any] [--max-mb 25]
//        [--name <stem>] [--timeout-ms 30000] [--max-redirects 4]
// Output: `__FETCH_OK__` then one JSON line per saved asset {url, path, contentType, bytes, sha256,
// format, width, height}; `__FETCH_ERR__ <url> <reason>` per failure.
// Exit: 0 every URL saved · 1 any URL refused or failed · 2 bad arguments or the toolchain is missing.

import crypto from "node:crypto";
import dns from "node:dns";
import { mkdir, writeFile } from "node:fs/promises";
import http from "node:http";
import https from "node:https";
import net from "node:net";
import path from "node:path";
import { EXIT, ToolingError, WORKSPACE, isMain, renderRequire, runCli } from "./toolchain.mjs";

const SCHEMES = new Set(["http:", "https:"]);

// --- address policy -------------------------------------------------------------------------------
const BLOCKED_V4 = [
  ["0.0.0.0", 8], // "this network"
  ["10.0.0.0", 8], // private
  ["100.64.0.0", 10], // CGNAT
  ["127.0.0.0", 8], // loopback
  ["169.254.0.0", 16], // link-local, including the 169.254.169.254 metadata service
  ["172.16.0.0", 12], // private
  ["192.0.0.0", 24], // IETF protocol assignments
  ["192.0.2.0", 24], // documentation
  ["192.88.99.0", 24], // 6to4 relay anycast
  ["192.168.0.0", 16], // private
  ["198.18.0.0", 15], // benchmarking
  ["198.51.100.0", 24], // documentation
  ["203.0.113.0", 24], // documentation
  ["224.0.0.0", 4], // multicast
  ["240.0.0.0", 4], // reserved, including broadcast
];

const v4Int = (ip) => ip.split(".").reduce((acc, part) => ((acc << 8) | Number(part)) >>> 0, 0);
function inV4Range(ip, base, bits) {
  const mask = bits === 0 ? 0 : (~0 << (32 - bits)) >>> 0;
  return (v4Int(ip) & mask) === (v4Int(base) & mask);
}

/** 16 bytes for an IPv6 address (zone id dropped, dotted IPv4 tail accepted), or null. */
function ipv6Bytes(input) {
  let ip = input.split("%")[0];
  let tail = null;
  const dotted = /(\d+\.\d+\.\d+\.\d+)$/.exec(ip);
  if (dotted) {
    if (!net.isIPv4(dotted[1])) return null;
    tail = dotted[1].split(".").map(Number);
    ip = `${ip.slice(0, -dotted[1].length)}0:0`;
  }
  const halves = ip.split("::");
  if (halves.length > 2) return null;
  const head = halves[0] ? halves[0].split(":") : [];
  const rest = halves.length === 2 && halves[1] ? halves[1].split(":") : [];
  const fill = halves.length === 2 ? 8 - head.length - rest.length : 0;
  if (fill < 0) return null;
  const groups = [...head, ...Array(fill).fill("0"), ...rest];
  if (groups.length !== 8 || groups.some((g) => !/^[0-9a-f]{1,4}$/i.test(g))) return null;
  const bytes = groups.flatMap((g) => {
    const n = parseInt(g, 16);
    return [n >> 8, n & 255];
  });
  if (tail) bytes.splice(12, 4, ...tail);
  return bytes;
}

const hasPrefix = (bytes, prefix, bits) => {
  for (let bit = 0; bit < bits; bit++) {
    const byte = bit >> 3;
    const mask = 0x80 >> (bit & 7);
    if ((bytes[byte] & mask) !== (prefix[byte] & mask)) return false;
  }
  return true;
};
const v4Of = (bytes, at) => bytes.slice(at, at + 4).join(".");
const BLOCKED_V6 = [
  [[0xfc], 7], // unique local
  [[0xfe, 0x80], 10], // link-local
  [[0xfe, 0xc0], 10], // site-local
  [[0xff], 8], // multicast
  [[0x20, 0x01, 0x0d, 0xb8], 32], // documentation
  [[0x20, 0x01, 0x00, 0x00], 32], // Teredo (embeds an obfuscated IPv4)
  [[0x01, 0x00, 0, 0, 0, 0, 0, 0], 64], // discard-only
  [[0x00, 0x64, 0xff, 0x9b, 0x00, 0x01], 48], // NAT64 local use
];

/** True for any address a fetch must not reach. Anything unparseable is refused. */
export function isBlockedIP(input) {
  const ip = String(input).replace(/^\[|\]$/g, "");
  if (net.isIPv4(ip)) return BLOCKED_V4.some(([base, bits]) => inV4Range(ip, base, bits));
  if (!net.isIPv6(ip)) return true;
  const bytes = ipv6Bytes(ip);
  if (!bytes) return true;
  // ::/96 (compatible, which includes :: and ::1) and ::ffff:0:0/96 (mapped) carry an IPv4 address.
  if (bytes.slice(0, 10).every((b) => b === 0) && ((bytes[10] === 0 && bytes[11] === 0) || (bytes[10] === 0xff && bytes[11] === 0xff))) {
    return isBlockedIP(v4Of(bytes, 12));
  }
  if (hasPrefix(bytes, [0x00, 0x64, 0xff, 0x9b], 96)) return isBlockedIP(v4Of(bytes, 12)); // NAT64
  if (hasPrefix(bytes, [0x20, 0x02], 16)) return isBlockedIP(v4Of(bytes, 2)); // 6to4
  return BLOCKED_V6.some(([prefix, bits]) => hasPrefix(bytes, [...prefix, ...Array(16).fill(0)], bits));
}

/**
 * The lookup every connection uses: resolve, refuse if ANY address is blocked, and hand the socket
 * exactly the addresses that were checked.
 */
export function guardedLookup(hostname, options, callback) {
  const opts = typeof options === "function" ? {} : options || {};
  const done = typeof options === "function" ? options : callback;
  dns.lookup(hostname, { all: true, family: opts.family || 0 }, (error, addresses) => {
    if (error) return done(error);
    if (!addresses.length) return done(new Error(`host does not resolve: ${hostname}`));
    const bad = addresses.find(({ address }) => isBlockedIP(address));
    if (bad) return done(Object.assign(new Error(`blocked address ${bad.address} for host ${hostname}`), { code: "EBLOCKED" }));
    if (opts.all) return done(null, addresses);
    return done(null, addresses[0].address, addresses[0].family);
  });
}

/** Parse and check one hop before any connection: scheme, credentials, literal addresses. */
export function checkUrl(raw) {
  let url;
  try {
    url = new URL(raw);
  } catch {
    throw new Error(`bad URL: ${String(raw).slice(0, 200)}`);
  }
  if (!SCHEMES.has(url.protocol)) throw new Error(`only http(s) URLs are fetched, not ${url.protocol}`);
  if (url.username || url.password) throw new Error("URLs with credentials are refused");
  const host = url.hostname.replace(/^\[|\]$/g, "");
  if (!host) throw new Error("URL has no host");
  if (host.toLowerCase() === "localhost" || host.toLowerCase().endsWith(".localhost")) throw new Error(`blocked host: ${host}`);
  if (net.isIP(host) && isBlockedIP(host)) throw new Error(`blocked address: ${host}`);
  return url;
}

// --- output ---------------------------------------------------------------------------------------
export function confineDir(root, dir) {
  const base = path.resolve(root);
  const abs = path.resolve(base, dir);
  if (abs !== base && !abs.startsWith(base + path.sep)) throw new ToolingError(`--out must be under ${base} (got ${abs})`);
  return abs;
}

const EXT_BY_MIME = {
  "image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif",
  "image/svg+xml": "svg", "image/avif": "avif", "application/pdf": "pdf",
};
export function safeName(url, base, contentType, sharpFormat) {
  let stem = base;
  if (!stem) {
    try {
      stem = path.basename(new URL(url).pathname) || "asset";
    } catch {
      stem = "asset";
    }
    stem = stem.replace(/\.[a-z0-9]{1,5}$/i, "");
  }
  stem = (stem || "asset").replace(/[^a-zA-Z0-9._-]/g, "-").replace(/-+/g, "-").replace(/^[.-]+/, "").slice(0, 60) || "asset";
  const hash = crypto.createHash("sha256").update(url).digest("hex").slice(0, 8);
  const ext = EXT_BY_MIME[(contentType || "").split(";")[0].trim().toLowerCase()] || (sharpFormat === "jpeg" ? "jpg" : sharpFormat) || "bin";
  return `${stem}-${hash}.${ext}`;
}

// --- fetch ----------------------------------------------------------------------------------------
function get(url, opt, signal) {
  return new Promise((resolve, reject) => {
    const lib = url.protocol === "https:" ? https : http;
    const req = lib.request(url, {
      method: "GET",
      agent: false,
      lookup: guardedLookup,
      signal,
      headers: { "user-agent": "design-agent/fetch-asset", accept: opt.kind === "image" ? "image/*" : "*/*" },
    });
    req.on("response", resolve);
    req.on("error", reject);
    req.end();
  });
}

export async function fetchOne(startUrl, opt) {
  const maxBytes = Math.floor(opt.maxMb * 1024 * 1024);
  const signal = AbortSignal.timeout(opt.timeoutMs);
  let current = startUrl;
  for (let hop = 0; hop <= opt.maxRedirects; hop++) {
    const url = checkUrl(current);
    const res = await get(url, opt, signal);
    if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
      res.resume();
      current = new URL(res.headers.location, url).href; // the next pass checks the new hop
      continue;
    }
    if (res.statusCode < 200 || res.statusCode >= 300) {
      res.resume();
      throw new Error(`HTTP ${res.statusCode}`);
    }
    const contentType = String(res.headers["content-type"] || "");
    if (opt.kind === "image" && !contentType.toLowerCase().startsWith("image/")) {
      res.resume();
      throw new Error(`not an image (content-type: ${contentType || "none"})`);
    }
    if (Number(res.headers["content-length"]) > maxBytes) {
      res.resume();
      throw new Error(`Content-Length exceeds --max-mb ${opt.maxMb}`);
    }
    const chunks = [];
    let size = 0;
    for await (const chunk of res) {
      size += chunk.length;
      if (size > maxBytes) {
        res.destroy();
        throw new Error(`exceeds --max-mb ${opt.maxMb}`);
      }
      chunks.push(chunk);
    }
    const buf = Buffer.concat(chunks);
    return { buf, contentType, finalUrl: url.href, sha256: crypto.createHash("sha256").update(buf).digest("hex") };
  }
  throw new Error(`too many redirects (> ${opt.maxRedirects})`);
}

function parseArgs(argv) {
  const urls = [];
  const opt = { out: null, kind: "image", maxMb: 25, name: null, timeoutMs: 30000, maxRedirects: 4, root: WORKSPACE };
  const value = (i) => {
    if (argv[i + 1] === undefined || argv[i + 1].startsWith("--")) throw new ToolingError(`${argv[i]} needs a value`);
    return argv[i + 1];
  };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--out") opt.out = value(i++);
    else if (a === "--kind") opt.kind = value(i++);
    else if (a === "--max-mb") opt.maxMb = Number(value(i++));
    else if (a === "--name") opt.name = value(i++);
    else if (a === "--timeout-ms") opt.timeoutMs = Number(value(i++));
    else if (a === "--max-redirects") opt.maxRedirects = Number(value(i++));
    else if (a === "--root") opt.root = value(i++);
    else if (a.startsWith("--")) throw new ToolingError(`unknown flag: ${a}`);
    else urls.push(a);
  }
  if (!urls.length) throw new ToolingError("usage: fetch-asset.mjs <url> [<url> ...] --out <dir> [--kind image|any]");
  if (!opt.out) throw new ToolingError("--out <dir> is required");
  if (!["image", "any"].includes(opt.kind)) throw new ToolingError("--kind must be image or any");
  if (!(opt.maxMb > 0)) throw new ToolingError("--max-mb must be > 0");
  if (!(opt.timeoutMs > 0)) throw new ToolingError("--timeout-ms must be > 0");
  if (!(Number.isInteger(opt.maxRedirects) && opt.maxRedirects >= 0 && opt.maxRedirects <= 10)) throw new ToolingError("--max-redirects must be 0-10");
  return { urls, opt };
}

if (isMain(import.meta.url)) {
  await runCli("fetch-asset", async () => {
    const { urls, opt } = parseArgs(process.argv.slice(2));
    const outDir = confineDir(opt.root, opt.out);
    const saved = [];
    let failures = 0;
    let sharp = null;
    for (const url of urls) {
      try {
        const { buf, contentType, finalUrl, sha256 } = await fetchOne(url, opt);
        let meta = { format: null, width: null, height: null };
        if (opt.kind === "image") {
          sharp ??= renderRequire("sharp"); // a missing toolchain is a ToolingError: exit 2
          const m = await sharp(buf).metadata().catch(() => null);
          if (!m?.width || !m?.height) throw new Error("not a decodable image");
          meta = { format: m.format, width: m.width, height: m.height };
        }
        await mkdir(outDir, { recursive: true });
        const file = path.join(outDir, safeName(url, opt.name && urls.length === 1 ? opt.name : null, contentType, meta.format));
        await writeFile(file, buf);
        saved.push({ url, finalUrl, path: file, contentType, bytes: buf.length, sha256, ...meta });
      } catch (error) {
        if (error instanceof ToolingError) throw error;
        failures++;
        console.log(`__FETCH_ERR__ ${url} ${error?.name === "TimeoutError" ? `timed out after ${opt.timeoutMs}ms` : error?.message || error}`);
      }
    }
    if (saved.length) {
      console.log("__FETCH_OK__");
      for (const asset of saved) console.log(JSON.stringify(asset));
    }
    return failures ? EXIT.FINDINGS : EXIT.PASS;
  });
}
