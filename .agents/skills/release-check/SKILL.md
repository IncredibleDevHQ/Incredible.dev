---
name: release-check
description: Run the release gates before tagging a Design Agent release: hygiene, secrets, licenses, docs, tests, and the human reviews.
---

# Release check

Stop at the first failure and report it; do not tag or publish. Tagging and publishing are the
maintainers' call.

1. `uv sync --all-extras --dev`, `uv run ruff check .`, `uv run ruff format --check .`,
   `uv run mypy src`, `uv run pytest -q`, `uv run pytest -q -m render` (Docker), `uv run design-agent
   demo`, `uv run design-agent skills verify`.
2. `DESIGN_AGENT_RELEASE_CHECK=1 uv run pytest -q tests/unit/test_public_hygiene.py`: no internal
   identifiers, licensed fonts, third-party media or build notes; the pre-release paths
   (`docs/prep/`, `IMPLEMENTATION_PROMPT.md`, `scripts/import_from_reference.py`) are deleted first.
3. `gitleaks detect --no-banner` (config `.gitleaks.toml`) on the full history.
4. Licenses: `fonts/LICENSES.md` matches `fonts/`, `licenses/` covers every vendored or bundled
   component, `NOTICE.md` is current, and `skills-lock.json` names each upstream license.
5. Docs: every link resolves (`uv run pytest -q tests/unit/test_docs_links.py`), README quick start
   works from a clean clone, `CHANGELOG.md` has the release.
6. `uv run mda build` from a clean checkout; inspect `.mda/build` and `.mda/__contexthub__`.
7. Human gates (SPEC §24): partner reviews (HyperFrames, Paper), legal review, sample-brand and
   gallery review. Record who signed off outside the repository.
