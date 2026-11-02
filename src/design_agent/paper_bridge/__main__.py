"""`python -m design_agent.paper_bridge`: the same entry as `design-agent paper-bridge`."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from design_agent.paper_bridge.app import DEFAULT_PORT, BridgeConfigError, serve
from design_agent.tools.paper import LOCAL_HTTP, PaperConfigError


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="design-agent paper-bridge",
        description=(
            "Serve this machine's Paper Desktop to a remote Design Agent, behind a bearer token "
            "(PAPER_BRIDGE_TOKEN). Expose it only through a tunnel you own."
        ),
    )
    parser.add_argument(
        "--host", default="127.0.0.1", help="address to listen on (default 127.0.0.1)"
    )
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help=f"port (default {DEFAULT_PORT})"
    )
    parser.add_argument(
        "--allow-host",
        action="append",
        default=[],
        metavar="HOSTNAME",
        help="the tunnel's public hostname; repeatable. Loopback is always allowed.",
    )
    parser.add_argument(
        "--upstream",
        default="auto",
        help=f"auto (default: stdio `paper mcp` when installed), stdio, or {LOCAL_HTTP}",
    )
    args = parser.parse_args(argv)
    try:
        serve(host=args.host, port=args.port, allow_hosts=args.allow_host, upstream=args.upstream)
    except (BridgeConfigError, PaperConfigError) as error:
        print(f"paper-bridge: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
