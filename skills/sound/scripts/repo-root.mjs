import { existsSync } from "node:fs";
import { basename, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

// The operating root from a module URL: the repository root when run from a checkout (a `.git`
// entry), otherwise the directory named `workspace` itself (the sandbox stages skills under
// /workspace/skills). Relative job paths resolve against it.
export function repoRoot(fromUrl) {
  const start = dirname(fileURLToPath(fromUrl));
  let d = start;
  let gitDir = null;
  let wsDir = null;
  for (let i = 0; i < 12; i++) {
    if (!gitDir && existsSync(join(d, ".git"))) gitDir = d;
    if (!wsDir && basename(d) === "workspace") wsDir = d;
    const up = dirname(d);
    if (up === d) break;
    d = up;
  }
  return gitDir || wsDir || start;
}

// A path inside the workspace tree (e.g. "tools/audio-lint.mjs"): `repoRoot` is the repository locally
// and the workspace itself in the sandbox, so never join a literal `workspace/...`.
export function workspacePath(root, ...parts) {
  const base = basename(root) === "workspace" ? root : join(root, "workspace");
  return join(base, ...parts);
}
