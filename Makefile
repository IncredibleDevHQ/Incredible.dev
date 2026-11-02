# Shortcuts for the commands everyone runs. Each line is what CI runs, nothing more.
.PHONY: setup demo check test lint format doctor sandbox render

setup:        ## install everything
	uv sync --all-extras --dev

sandbox:      ## build the designer's computer for the local Docker runner
	uv run design-agent sandbox build

demo:         ## a still in three sizes through the real graph, no keys (needs the sandbox image)
	uv run design-agent demo

check:        ## the CI gate: lint, format, types, offline tests
	uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest -q -m "not render and not live"

render:       ## render smoke tests inside the sandbox image
	uv run pytest -q -m render

lint:
	uv run ruff check . --fix && uv run ruff format .

test:
	uv run pytest -q -m "not render and not live"

doctor:
	uv run design-agent doctor
