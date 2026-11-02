"""The bundled Paper bridge for Bridged mode (`app.py`); run with `design-agent paper-bridge`."""

from design_agent.paper_bridge.app import BridgeConfigError, create_app, serve

__all__ = ["BridgeConfigError", "create_app", "serve"]
