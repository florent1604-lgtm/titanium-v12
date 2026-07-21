"""Singleton Streamable HTTP launcher for the local Hermes bridge."""

from __future__ import annotations

import os
from pathlib import Path
import sys


HOST = "127.0.0.1"
PORT = 8766
PATH = "/mcp"
HERMES_AGENT_ROOT = Path(os.environ.get(
    "HERMES_AGENT_ROOT",
    Path(os.environ.get("LOCALAPPDATA", "")) / "hermes" / "hermes-agent",
)).resolve()


def build_server():
    if not HERMES_AGENT_ROOT.is_dir():
        raise RuntimeError(f"HERMES_AGENT_ROOT_MISSING:{HERMES_AGENT_ROOT}")
    root = str(HERMES_AGENT_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)

    from mcp_serve import EventBridge, create_mcp_server

    bridge = EventBridge()
    server = create_mcp_server(event_bridge=bridge)
    # A local MCP client may inspect pending permissions, but may never approve
    # them automatically. Approval remains an explicit Florent/supervisor act.
    server.remove_tool("permissions_respond")
    server.settings.host = HOST
    server.settings.port = PORT
    server.settings.streamable_http_path = PATH
    server.settings.stateless_http = True
    server.settings.json_response = True
    return bridge, server


def main() -> None:
    bridge, server = build_server()
    bridge.start()
    try:
        server.run(transport="streamable-http")
    finally:
        bridge.stop()


if __name__ == "__main__":
    main()
