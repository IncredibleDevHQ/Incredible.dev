---
name: design-agent-update
description: Bring a fork or clone of Design Agent up to date with the upstream repository while keeping the team's brand, skills and edits, rebuild what changed, and redeploy safely. Use when someone asks to update, upgrade or pull the latest Design Agent.
---

# Update from upstream

The brand pack (`workspace/brand/`), licensed fonts (`private-fonts/`) and `.env` are Git-ignored,
so an update never touches them. The team's own skills and instruction edits can conflict.

1. `git status`. Commit the person's local work first, or ask; never use a bare `git stash`.
2. Add the remote once: `git remote add upstream https://github.com/langchain-ai/design-agent.git`.
   Then `git fetch upstream` and read the new entries in `CHANGELOG.md` for breaking changes.
3. Merge `upstream/main` into the person's branch. In conflicts, keep their skills and instruction
   edits and take upstream's code; ask when a conflict touches both.
4. `uv sync`, `uv run design-agent doctor`, `uv run pytest -q`, `uv run design-agent skills verify`.
5. If `sandbox/setup.sh` changed: `uv run design-agent sandbox build && uv run design-agent sandbox test`;
   for Managed Deep Agents, also `uv run design-agent sandbox publish` (the snapshot name follows the
   recipe's hash).
6. Try the update on a test copy (`uv run mda deploy --name design-agent-test`), then
   deploy the team's agent after a yes ([design-agent-deploy](../design-agent-deploy/SKILL.md)).
