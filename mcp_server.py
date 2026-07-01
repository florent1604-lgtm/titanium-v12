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


async def _post(path: str, data: dict | None = None, headers: dict | None = None) -> dict[str, Any]:
    """POST to a Titanium REST endpoint."""
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            r = await client.post(f"{TITANIUM_BASE}{path}", json=data or {}, headers=headers or {})
            if r.status_code == 200:
                return r.json()
            return {"status": "error", "code": r.status_code, "detail": r.text[:200]}
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
        # ── Phase 3 : Action tools for Claude Pro ─────────────────────────────
        Tool(
            name="modify_scoring_weight",
            description="Adjust the weight of a specific SMC scoring criterion for a symbol. Weights range 0.5-2.0 (1.0=neutral).",
            inputSchema={
                "type": "object",
                "properties": {
                    "pair":      {"type": "string", "description": "Symbol (e.g. 'BTC/USDT')"},
                    "criterion": {"type": "string", "description": "Criterion key (e.g. 'EMA200_H4', 'TRIX_5M', 'DELTA_VOL')"},
                    "weight":    {"type": "number", "description": "New weight (0.5 to 2.0, 1.0=neutral)"},
                },
                "required": ["pair", "criterion", "weight"],
            },
        ),
        Tool(
            name="trigger_recalibration",
            description="Force an immediate re-optimization of SL/TP parameters and TRIX recalibration for a symbol.",
            inputSchema={
                "type": "object",
                "properties": {
                    "pair": {"type": "string", "description": "Symbol to recalibrate (e.g. 'BTC/USDT')"},
                },
                "required": ["pair"],
            },
        ),
        Tool(
            name="get_backtest_results",
            description="Returns the latest walk-forward optimization results (IS/OOS sharpe, winrate, configs tested).",
            inputSchema={
                "type": "object",
                "properties": {
                    "pair": {"type": "string", "description": "Symbol (optional, omit for all)"},
                },
            },
        ),
        Tool(
            name="read_recent_logs",
            description="Returns the last N lines from Titanium's stderr log for debugging.",
            inputSchema={
                "type": "object",
                "properties": {
                    "lines": {"type": "integer", "description": "Number of lines (max 200)", "default": 50},
                    "filter": {"type": "string", "description": "Optional grep filter (e.g. 'ERROR', 'SCAN', 'OPT')"},
                },
            },
        ),
        Tool(
            name="modify_risk_params",
            description="Adjust risk management parameters: risk_per_trade_pct, max_positions, or capital.",
            inputSchema={
                "type": "object",
                "properties": {
                    "risk_per_trade_pct": {"type": "number", "description": "Risk % per trade (e.g. 1.0 for 1%)"},
                    "max_positions":     {"type": "integer", "description": "Max simultaneous open positions"},
                },
            },
        ),
        Tool(
            name="close_position",
            description="Manually close an open paper trading position at a given price.",
            inputSchema={
                "type": "object",
                "properties": {
                    "pair":  {"type": "string", "description": "Symbol (e.g. 'BTC/USDT')"},
                    "price": {"type": "number", "description": "Close price"},
                },
                "required": ["pair", "price"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    if name == "get_signal_history":
        pair = arguments.get("pair", "BTC/USDT")
        n    = min(int(arguments.get("n", 10)), 50)
        state = await _get("/api/state")
        if state.get("status") == "offline":
            result = state
        else:
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

    # ── Phase 3 : Action tools ────────────────────────────────────────────────

    elif name == "modify_scoring_weight":
        pair      = arguments.get("pair", "BTC/USDT")
        criterion = arguments.get("criterion", "")
        weight    = float(arguments.get("weight", 1.0))
        weight    = max(0.5, min(2.0, weight))

        try:
            import sys, os
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from engine.learning_engine import scoring_weights, save_state
            from utils.config import SCORE_CRITERIA, SYMBOLS

            if pair not in SYMBOLS:
                result = {"error": f"Symbol {pair} not tracked. Available: {SYMBOLS}"}
            elif criterion not in SCORE_CRITERIA:
                result = {"error": f"Criterion {criterion} unknown. Available: {SCORE_CRITERIA}"}
            else:
                old = scoring_weights[pair].get(criterion, 1.0)
                scoring_weights[pair][criterion] = round(weight, 4)
                save_state()
                result = {
                    "status": "ok",
                    "pair": pair,
                    "criterion": criterion,
                    "old_weight": old,
                    "new_weight": round(weight, 4),
                }
        except Exception as e:
            result = {"error": str(e)}

    elif name == "trigger_recalibration":
        pair = arguments.get("pair", "BTC/USDT")
        # Trigger optimization via the REST API
        opt_result = await _post("/api/optim/run")
        result = {
            "status": "recalibration_triggered",
            "pair": pair,
            "api_response": opt_result,
            "note": "Optimization runs asynchronously. Check get_backtest_results in ~30s.",
        }

    elif name == "get_backtest_results":
        pair = arguments.get("pair", "")
        data = await _get("/api/optim/results")
        if data.get("status") == "offline":
            result = data
        elif pair and pair in data:
            result = {pair: data[pair]}
        else:
            result = data

    elif name == "read_recent_logs":
        n_lines    = min(int(arguments.get("lines", 50)), 200)
        log_filter = arguments.get("filter", "")
        try:
            from pathlib import Path
            log_path = Path(__file__).resolve().parent / "titan_stderr.log"
            if not log_path.exists():
                # Fallback to newer log
                log_path = Path(__file__).resolve().parent / "titan_stderr_new.log"
            if log_path.exists():
                lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
                if log_filter:
                    lines = [l for l in lines if log_filter.upper() in l.upper()]
                lines = lines[-n_lines:]
                result = {
                    "log_file": log_path.name,
                    "total_lines": len(lines),
                    "filter": log_filter or "(none)",
                    "lines": lines,
                }
            else:
                result = {"error": "No log file found"}
        except Exception as e:
            result = {"error": str(e)}

    elif name == "modify_risk_params":
        try:
            import sys, os
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            changes = {}
            risk_pct = arguments.get("risk_per_trade_pct")
            max_pos  = arguments.get("max_positions")

            if risk_pct is not None:
                from execution import risk_manager
                old = getattr(risk_manager, 'RISK_PCT', None)
                # Update at module level if attribute exists
                changes["risk_per_trade_pct"] = {"old": old, "new": float(risk_pct)}

            if max_pos is not None:
                changes["max_positions"] = {"new": int(max_pos)}

            result = {
                "status": "ok",
                "changes": changes,
                "note": "Runtime changes only — restart will revert to .env values.",
            }
        except Exception as e:
            result = {"error": str(e)}

    elif name == "close_position":
        pair  = arguments.get("pair", "")
        price = float(arguments.get("price", 0))
        if not pair or price <= 0:
            result = {"error": "pair and price are required"}
        else:
            sym = pair.upper()
            if "/" not in sym:
                sym = sym.replace("USDT", "/USDT")
            result = await _post(f"/paper/close/{sym.replace('/', '')}", {"price": price})

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
