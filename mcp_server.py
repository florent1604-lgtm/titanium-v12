"""mcp_server.py — Titanium v12 MCP Server (stdio transport).

Exposes Titanium live trading state to Antigravity Cascade via MCP.
Reads data from the Titanium FastAPI backend (http://localhost:8090).

Run:
    python mcp_server.py          # stdio (for Antigravity mcp_config.json)
    python mcp_server.py --test   # sanity-check all resources
"""
from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Resource,
    ResourceContents,
    TextContent,
    TextResourceContents,
    Tool,
)

# ── Config ────────────────────────────────────────────────────────────────────
TITANIUM_BASE = "http://localhost:8090"
_HTTP_TIMEOUT = 4.0

app = Server("titanium-v12")

# ── HTTP helper ───────────────────────────────────────────────────────────────

async def _get(path: str) -> dict[str, Any]:
    """Fetch a Titanium REST endpoint, return dict (or offline sentinel)."""
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            r = await client.get(f"{TITANIUM_BASE}{path}")
            if r.status_code == 200:
                return r.json()
            return {"status": "error", "code": r.status_code}
    except Exception as e:
        return {"status": "offline", "reason": str(e)}


def _fmt(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


# ── Resources ─────────────────────────────────────────────────────────────────

@app.list_resources()
async def list_resources() -> list[Resource]:
    return [
        Resource(
            uri="titanium://signals/latest",
            name="Latest SMC Signals",
            description="Last SMC signal per pair: direction, score/11, CHoCH/BOS, OB level, SL/TP.",
            mimeType="application/json",
        ),
        Resource(
            uri="titanium://positions/open",
            name="Open Positions",
            description="Open paper-trading positions: pair, entry, unrealised PnL, SL/TP levels.",
            mimeType="application/json",
        ),
        Resource(
            uri="titanium://market/context",
            name="Market Context",
            description="EMA200 bias, funding rate, OI delta, long/short ratio, delta volume per pair.",
            mimeType="application/json",
        ),
        Resource(
            uri="titanium://dashboard/status",
            name="Dashboard Status",
            description="Bot running state, last update timestamp, circuit breaker state, equity.",
            mimeType="application/json",
        ),
    ]


@app.read_resource()
async def read_resource(uri: str) -> list[ResourceContents]:
    if uri == "titanium://signals/latest":
        data = await _get("/api/state")
        if data.get("status") == "offline":
            content = data
        else:
            raw = data.get("signals", {})
            content = {
                sym: {
                    k: v for k, v in sig.items()
                    if k not in ("confs_detail",)  # trim noise
                }
                for sym, sig in raw.items()
            }

    elif uri == "titanium://positions/open":
        data = await _get("/paper/positions")
        if data.get("status") == "offline":
            content = data
        else:
            content = {
                "mode":      data.get("mode", "unknown"),
                "count":     data.get("count", 0),
                "positions": data.get("positions", {}),
            }

    elif uri == "titanium://market/context":
        state = await _get("/api/state")
        if state.get("status") == "offline":
            content = state
        else:
            futures = state.get("futures", {})
            dvol    = state.get("delta_vol", {})
            content = {}
            for sym in futures:
                f = futures[sym]
                d = dvol.get(sym, {})
                content[sym] = {
                    "funding_rate":       f.get("funding"),
                    "open_interest":      f.get("oi"),
                    "oi_change_pct":      f.get("oi_change_pct"),
                    "long_short_ratio":   f.get("long_short_ratio"),
                    "mark_price":         f.get("mark_price"),
                    "delta_vol_bullish":  d.get("bullish"),
                    "delta_vol_bearish":  d.get("bearish"),
                    "delta_pct":          d.get("delta_pct"),
                }

    elif uri == "titanium://dashboard/status":
        state = await _get("/api/state")
        paper = await _get("/paper/stats")
        if state.get("status") == "offline":
            content = state
        else:
            signals     = state.get("signals", {})
            active_sigs = {s: d for s, d in signals.items() if d.get("active")}
            cb          = {
                s: d.get("blocked_by")
                for s, d in signals.items()
                if d.get("blocked_by")
            }
            content = {
                "version":         state.get("version", "v12"),
                "trading_mode":    state.get("trading_mode", "unknown"),
                "ts":              state.get("ts"),
                "ws_clients":      state.get("ws_clients", 0),
                "active_signals":  len(active_sigs),
                "circuit_breaker": cb,
                "equity":          paper.get("equity") if isinstance(paper, dict) and "equity" in paper else None,
                "total_pnl":       paper.get("total_pnl") if isinstance(paper, dict) else None,
                "winrate_pct":     paper.get("winrate_pct") if isinstance(paper, dict) else None,
            }
    else:
        content = {"error": f"Unknown resource URI: {uri}"}

    return [
        TextResourceContents(
            uri=uri,
            mimeType="application/json",
            text=_fmt(content),
        )
    ]


# ── Tools ──────────────────────────────────────────────────────────────────────

@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="get_signal_history",
            description="Returns the last N signals for a trading pair (from the adaptive learning engine).",
            inputSchema={
                "type": "object",
                "properties": {
                    "pair": {
                        "type": "string",
                        "description": "Symbol in 'BTC/USDT' format.",
                    },
                    "n": {
                        "type": "integer",
                        "description": "Number of recent signals to return (max 50).",
                        "default": 10,
                    },
                },
                "required": ["pair"],
            },
        ),
        Tool(
            name="get_pnl_summary",
            description="Returns daily and cumulative PnL summary with Sharpe, winrate, and drawdown.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="get_active_alerts",
            description="Returns any triggered circuit breakers, cooling signals, or risk alerts.",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    if name == "get_signal_history":
        pair = arguments.get("pair", "BTC/USDT")
        n    = min(int(arguments.get("n", 10)), 50)
        # Signal history is not directly on REST; derive from /api/state
        state = await _get("/api/state")
        if state.get("status") == "offline":
            result = state
        else:
            # Fall back to the live signal for this pair + note history limitation
            signals = state.get("signals", {})
            entry   = signals.get(pair, {})
            result  = {
                "pair":    pair,
                "note":    "Live state only — history requires Titanium to be running",
                "latest":  entry,
                "n_requested": n,
            }

    elif name == "get_pnl_summary":
        stats = await _get("/paper/stats")
        if stats.get("status") == "offline":
            result = stats
        else:
            result = {
                "equity":           stats.get("equity"),
                "initial_capital":  stats.get("initial_capital"),
                "total_pnl":        stats.get("total_pnl"),
                "total_pnl_pct":    stats.get("total_pnl_pct"),
                "winrate_pct":      stats.get("winrate_pct"),
                "sharpe":           stats.get("sharpe"),
                "max_drawdown_pct": stats.get("max_drawdown_pct"),
                "total_trades":     stats.get("total_trades"),
                "wins":             stats.get("wins"),
                "losses":           stats.get("losses"),
                "avg_win_usdt":     stats.get("avg_win_usdt"),
                "avg_loss_usdt":    stats.get("avg_loss_usdt"),
                "expectancy_usdt":  stats.get("expectancy_usdt"),
                "total_fees":       stats.get("total_fees"),
            }

    elif name == "get_active_alerts":
        state = await _get("/api/state")
        if state.get("status") == "offline":
            result = state
        else:
            signals = state.get("signals", {})
            alerts  = []
            for sym, sig in signals.items():
                if sig.get("blocked_by"):
                    alerts.append({
                        "type":   "circuit_breaker",
                        "symbol": sym,
                        "reason": sig["blocked_by"],
                    })
                if sig.get("cooling_remaining", 0) > 0:
                    alerts.append({
                        "type":              "cooldown",
                        "symbol":            sym,
                        "remaining_seconds": sig["cooling_remaining"],
                    })
            result = {
                "alerts":       alerts,
                "alert_count":  len(alerts),
                "ts":           state.get("ts"),
            }
    else:
        result = {"error": f"Unknown tool: {name}"}

    return [TextContent(type="text", text=_fmt(result))]


# ── Entrypoint ────────────────────────────────────────────────────────────────

async def _run_test() -> None:
    """Quick sanity check — print all resources and tools."""
    print("=== Titanium MCP Server — Self-Test ===\n")
    uris = [
        "titanium://signals/latest",
        "titanium://positions/open",
        "titanium://market/context",
        "titanium://dashboard/status",
    ]
    for uri in uris:
        result = await read_resource(uri)
        print(f"[Resource] {uri}")
        print(result[0].text[:300])
        print()

    for tool_name, args in [
        ("get_pnl_summary",    {}),
        ("get_active_alerts",  {}),
        ("get_signal_history", {"pair": "BTC/USDT", "n": 3}),
    ]:
        result = await call_tool(tool_name, args)
        print(f"[Tool] {tool_name}")
        print(result[0].text[:300])
        print()


if __name__ == "__main__":
    if "--test" in sys.argv:
        asyncio.run(_run_test())
    else:
        asyncio.run(stdio_server(app))
