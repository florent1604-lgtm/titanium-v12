"""Singleton Streamable HTTP MCP surface for Titanium (read-only)."""

from __future__ import annotations

from pathlib import Path
import sys

from mcp.server.fastmcp import FastMCP

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import mcp_server as legacy


HOST = "127.0.0.1"
PORT = 8091
PATH = "/mcp"

mcp = FastMCP(
    "titanium-v12-readonly",
    host=HOST,
    port=PORT,
    streamable_http_path=PATH,
    stateless_http=True,
    json_response=True,
)


async def _call(name: str, arguments: dict) -> str:
    result = await legacy.call_tool(name, arguments)
    return result[0].text


async def _resource(uri: str) -> str:
    result = await legacy.read_resource(uri)
    return result[0].text


@mcp.resource("titanium://signals/latest")
async def signals_latest() -> str:
    return await _resource("titanium://signals/latest")


@mcp.resource("titanium://positions/open")
async def positions_open() -> str:
    return await _resource("titanium://positions/open")


@mcp.resource("titanium://market/context")
async def market_context() -> str:
    return await _resource("titanium://market/context")


@mcp.resource("titanium://dashboard/status")
async def dashboard_status() -> str:
    return await _resource("titanium://dashboard/status")


@mcp.tool()
async def get_signal_history(pair: str, n: int = 10) -> str:
    """Return the latest signal state for a pair (read-only)."""
    return await _call("get_signal_history", {"pair": pair, "n": n})


@mcp.tool()
async def get_pnl_summary() -> str:
    """Return PAPER/DEMO PnL summaries (read-only)."""
    return await _call("get_pnl_summary", {})


@mcp.tool()
async def get_active_alerts() -> str:
    """Return circuit-breaker and risk alerts (read-only)."""
    return await _call("get_active_alerts", {})


@mcp.tool()
async def get_backtest_results(pair: str = "") -> str:
    """Return the latest walk-forward results (read-only)."""
    return await _call("get_backtest_results", {"pair": pair})


@mcp.tool()
async def read_recent_logs(lines: int = 50, filter: str = "") -> str:
    """Return a bounded, optionally filtered log tail (read-only)."""
    return await _call("read_recent_logs", {"lines": lines, "filter": filter})


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
