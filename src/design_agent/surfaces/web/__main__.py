"""Run the web app: `uv run python -m design_agent.surfaces.web [--demo] [--port 8765]`.

`--demo` puts the scripted lead in place of a model, so the whole app runs with no API keys
(Docker and the sandbox image are still needed: `uv run design-agent sandbox build`).
"""

from __future__ import annotations

import argparse

import uvicorn

from design_agent.config import Settings, project_root
from design_agent.surfaces.web.app import create_app


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m design_agent.surfaces.web")
    parser.add_argument("--demo", action="store_true", help="the scripted lead, no API keys")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    app = create_app(project_root(), Settings(), demo=args.demo)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
