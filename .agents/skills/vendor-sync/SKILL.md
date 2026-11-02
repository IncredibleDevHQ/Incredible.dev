---
name: vendor-sync
description: Move a vendored upstream (HyperFrames, LangSmith skills, Deep Agents skills) to a newer pin, re-vendor its skills unmodified, verify them, and update everything that depends on the pin.
---

# Update vendored skills

Vendored skills are never edited; they are replaced from upstream at a commit and checked against
`skills-lock.json` in CI. Each upstream's pin lives in `UPSTREAMS` in
`src/design_agent/skills_lock.py`, with the skills it vendors into `skills/` (runtime) and
`.agents/skills/` (coding agents). `uv run design-agent skills sync-vendor --check-only` compares
every pin with its upstream's newest release (HyperFrames) or `main` commit (LangChain's packs).

## HyperFrames

1. Pick the release: the latest stable HyperFrames tag (never a prerelease) and its commit. Read its
   changelog for CLI changes (flags, renamed or deprecated commands such as `validate` → `check`).
2. Bump the `hyperframes` entry's `commit` and `release` in `UPSTREAMS`, the `hyperframes` version
   in `sandbox/render/package.json`, then `npm install --package-lock-only` in `sandbox/render/`
   and `uv run python scripts/sync_sandbox_recipe.py` (embeds the lock in `setup.sh`).
3. `uv run design-agent skills sync-vendor --upstream hyperframes`; review
   `git diff skills/ skills-lock.json`. Check the exclusion list still catches third-party media,
   unlicensed fonts and bundled libraries. Upstream skills carry their own `.gitignore`s:
   `git add -f` any locked file they hide (`test_git_tracks_every_locked_file` names them).
4. Rebuild and prove: `uv run design-agent sandbox build`, `sandbox test`,
   `uv run pytest -q -m render`, `uv run design-agent demo`. MDA deployments need
   `sandbox publish` again, since the recipe changed.

## LangSmith and Deep Agents skills

1. Read what changed on `main` of `langchain-ai/langsmith-skills` or `langchain-ai/langchain-skills`
   since the pinned commit, then bump that entry's `commit` in `UPSTREAMS`.
2. `uv run design-agent skills sync-vendor --upstream langsmith-skills` (or `langchain-skills`);
   review `git diff skills/ .agents/skills/ skills-lock.json`.
3. If `langsmith-trace` changed, check its one-line summary in `config/vendored-skills.toml` still
   steers the deployed agent to `list_traces` and `read_trace`: its sandbox has no network and no
   LangSmith key, so the CLI the skill teaches cannot run there.

## Every upstream

- New or renamed runtime skills: add a one-line summary to `config/vendored-skills.toml`, and the
  folder to `extend-exclude` in `pyproject.toml` (tests fail until both match the lock). New
  coding-agent skills need a route in `AGENTS.md` (`test_coding_agent_skills.py` checks).
- Prove: `uv run design-agent skills verify`, `uv run pytest -q`.
- Record the new pin and anything that changed in `NOTICE.md`, `docs/sources/` and `CHANGELOG.md`.
