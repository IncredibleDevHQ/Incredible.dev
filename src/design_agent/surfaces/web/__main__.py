"""Run the web app: `uv run python -m design_agent.surfaces.web [--demo] [--port 8765]`.

`--demo` puts the scripted lead in place of a model, so the whole app runs with no API keys
(Docker and the sandbox image are still needed: `uv run design-agent sandbox build`).
"""

from __future__ import annotations

import argparse
import contextlib
from types import FrameType

import uvicorn

from design_agent.config import Settings, project_root
from design_agent.surfaces.web.app import create_app
from design_agent.surfaces.web.auth import Tenants
from design_agent.surfaces.web.hub import Hub

#: How long a stopping house waits for requests still open, once it has ended every page's live
#: stream (`House`); past it, whatever is left is cut.
STOP_SECONDS = 10


class House(uvicorn.Server):
    """The web app's server. Told to stop, it first ends every page's live stream: a stream never
    ends on its own, so the stop would otherwise wait on each open tab, still pinging the pages
    it has while refusing every new request. Ended, each page sees the house go (`live.ts`)."""

    def __init__(self, config: uvicorn.Config, hub: Hub | Tenants) -> None:
        super().__init__(config)
        self.hub = hub

    def handle_exit(self, sig: int, frame: FrameType | None) -> None:
        self.hub.close_streams()
        super().handle_exit(sig, frame)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m design_agent.surfaces.web")
    parser.add_argument("--demo", action="store_true", help="the scripted lead, no API keys")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    settings = Settings()
    app = create_app(project_root(), settings, demo=args.demo)
    config = uvicorn.Config(
        app,
        host=args.host,
        port=args.port,
        log_level="info",
        # OAuth callback URLs contain short-lived credentials.
        access_log=not (settings.auth_required or settings.supabase_url),
        timeout_graceful_shutdown=STOP_SECONDS,
    )
    # A stop by Ctrl-C ends as `uvicorn.run` ends one: the server raises it again once it has
    # shut down, and it ends the process quietly.
    with contextlib.suppress(KeyboardInterrupt):
        streams = getattr(app.state, "tenants", None) or app.state.host.hub
        House(config, streams).run()


if __name__ == "__main__":
    main()
