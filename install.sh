#!/usr/bin/env bash
# Install Design Agent: uv if it is missing, a clone of the repository, and its dependencies.
#
#   curl -fsSL https://raw.githubusercontent.com/langchain-ai/design-agent/main/install.sh | bash
#
# It never asks for or writes a key. DESIGN_AGENT_DIR picks the folder (default ./design-agent);
# DESIGN_AGENT_REPO picks what to clone (a fork, say).
set -euo pipefail

REPO="${DESIGN_AGENT_REPO:-https://github.com/langchain-ai/design-agent.git}"
DIR="${DESIGN_AGENT_DIR:-design-agent}"

say() { printf '\033[1m%s\033[0m\n' "$*"; }
fail() { printf 'error: %s\n' "$*" >&2; exit 1; }

command -v git >/dev/null 2>&1 || fail "git is required: install it, then run this again."

if ! command -v uv >/dev/null 2>&1; then
  say "Installing uv (https://docs.astral.sh/uv/)"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
  command -v uv >/dev/null 2>&1 || fail "uv installed, but it is not on PATH: open a new terminal and run this again."
fi

if [ -e "$DIR" ]; then
  [ -f "$DIR/instructions.md" ] && [ -d "$DIR/.git" ] || fail "$DIR already exists and is not a Design Agent checkout."
  say "Updating $DIR"
  git -C "$DIR" pull --ff-only
else
  say "Cloning $REPO into $DIR"
  git clone --depth 1 "$REPO" "$DIR"
fi

say "Installing dependencies"
(cd "$DIR" && uv sync)

cat <<EOF

Installed in $DIR. Next, with Docker running:

  cd $DIR
  uv run design-agent sandbox build     # the agent's computer, as a local image
  uv run design-agent demo              # no keys needed
  uv run design-agent config set ANTHROPIC_API_KEY=sk-ant-...
  uv run design-agent doctor

To run it for a team, see docs/self-hosting.md.
EOF
