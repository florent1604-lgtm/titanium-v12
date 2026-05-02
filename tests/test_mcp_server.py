"""tests/test_mcp_server.py — Tests for the Titanium MCP server.

Run:  cd C:\\Users\\flore\\Desktop\\v12 && venv\\Scripts\\pytest tests/test_mcp_server.py -v
"""
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Fixtures ──────────────────────────────────────────────────────────────────

MOCK_STATE = {
    "version": "v12",
    "trading_mode": "paper",
    "ts": "2026-05-02T18:00:00Z",
    "ws_clients": 1,
    "signals": {
        "BTC/USDT": {
            "score": 7, "score_max": 11, "side": "ACHAT",
            "active": True, "price": 95000.0,
            "sl": 94000.0, "tp1": 96500.0, "rr": 1.5,
            "confs": ["CHoCH", "OB"], "regime": "TREND",
        },
        "PAXG/USDT": {
            "score": 0, "side": "NEUTRE", "active": False,
        },
    },
    "futures": {
        "BTC/USDT": {
            "funding": 0.0001, "oi": 15000000.0,
            "oi_change_pct": 2.5, "long_short_ratio": 1.3,
            "mark_price": 95050.0,
        }
    },
    "delta_vol": {
        "BTC/USDT": {
            "bullish": True, "bearish": False, "delta_pct": 0.62,
        }
    },
}

MOCK_PAPER_STATS = {
    "equity": 1050.0, "initial_capital": 1000.0,
    "total_pnl": 50.0, "total_pnl_pct": 5.0,
    "winrate_pct": 60.0, "sharpe": 1.2,
    "max_drawdown_pct": -8.0, "total_trades": 15,
    "wins": 9, "losses": 6,
    "avg_win_usdt": 12.0, "avg_loss_usdt": -7.0,
    "expectancy_usdt": 3.0, "total_fees": 2.5,
}

MOCK_POSITIONS = {
    "mode": "paper", "count": 1,
    "positions": {
        "BTC/USDT": {
            "symbol": "BTC/USDT", "side": "LONG",
            "entry_price": 94500.0, "unrealized_pnl": 52.5,
            "sl": 94000.0, "tp1": 96500.0,
        }
    },
}

OFFLINE_RESPONSE = {"status": "offline", "reason": "Connection refused"}


def _make_mock_get(state=MOCK_STATE, stats=MOCK_PAPER_STATS, positions=MOCK_POSITIONS):
    async def _mock_get(path: str):
        if "/api/state" in path:
            return state
        if "/paper/stats" in path:
            return stats
        if "/paper/positions" in path:
            return positions
        return {}
    return _mock_get


# ── Resource Tests ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_resource_signals_latest():
    """Signals resource returns valid JSON with expected keys."""
    import mcp_server
    with patch.object(mcp_server, "_get", side_effect=_make_mock_get()):
        result = await mcp_server.read_resource("titanium://signals/latest")
    data = json.loads(result[0].text)
    assert "BTC/USDT" in data
    sig = data["BTC/USDT"]
    assert sig["score"] == 7
    assert sig["side"] == "ACHAT"
    assert sig["active"] is True


@pytest.mark.asyncio
async def test_resource_positions_open():
    """Positions resource returns mode, count, and positions dict."""
    import mcp_server
    with patch.object(mcp_server, "_get", side_effect=_make_mock_get()):
        result = await mcp_server.read_resource("titanium://positions/open")
    data = json.loads(result[0].text)
    assert data["mode"] == "paper"
    assert data["count"] == 1
    assert "BTC/USDT" in data["positions"]


@pytest.mark.asyncio
async def test_resource_market_context():
    """Market context resource returns funding, OI, delta vol per pair."""
    import mcp_server
    with patch.object(mcp_server, "_get", side_effect=_make_mock_get()):
        result = await mcp_server.read_resource("titanium://market/context")
    data = json.loads(result[0].text)
    assert "BTC/USDT" in data
    ctx = data["BTC/USDT"]
    assert ctx["funding_rate"] == 0.0001
    assert ctx["delta_vol_bullish"] is True


@pytest.mark.asyncio
async def test_resource_dashboard_status():
    """Dashboard status resource returns version, equity, active signals."""
    import mcp_server
    with patch.object(mcp_server, "_get", side_effect=_make_mock_get()):
        result = await mcp_server.read_resource("titanium://dashboard/status")
    data = json.loads(result[0].text)
    assert data["version"] == "v12"
    assert data["active_signals"] == 1
    assert data["equity"] == 1050.0


@pytest.mark.asyncio
async def test_resource_offline_degradation():
    """All resources return offline sentinel when Titanium is down."""
    import mcp_server
    with patch.object(mcp_server, "_get", return_value=OFFLINE_RESPONSE):
        for uri in [
            "titanium://signals/latest",
            "titanium://positions/open",
            "titanium://market/context",
            "titanium://dashboard/status",
        ]:
            result = await mcp_server.read_resource(uri)
            data = json.loads(result[0].text)
            assert data.get("status") == "offline", f"URI {uri} did not return offline sentinel"


@pytest.mark.asyncio
async def test_resource_unknown_uri():
    """Unknown URI returns error dict, not an exception."""
    import mcp_server
    result = await mcp_server.read_resource("titanium://nonexistent/resource")
    data = json.loads(result[0].text)
    assert "error" in data


# ── Tool Tests ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tool_get_pnl_summary():
    """get_pnl_summary returns equity, winrate, sharpe."""
    import mcp_server
    with patch.object(mcp_server, "_get", side_effect=_make_mock_get()):
        result = await mcp_server.call_tool("get_pnl_summary", {})
    data = json.loads(result[0].text)
    assert data["equity"] == 1050.0
    assert data["winrate_pct"] == 60.0
    assert data["sharpe"] == 1.2


@pytest.mark.asyncio
async def test_tool_get_active_alerts_no_alerts():
    """get_active_alerts returns empty list when no circuit breakers active."""
    import mcp_server
    with patch.object(mcp_server, "_get", side_effect=_make_mock_get()):
        result = await mcp_server.call_tool("get_active_alerts", {})
    data = json.loads(result[0].text)
    assert data["alert_count"] == 0
    assert data["alerts"] == []


@pytest.mark.asyncio
async def test_tool_get_active_alerts_with_cb():
    """get_active_alerts detects circuit breaker in signal state."""
    import mcp_server
    state_with_cb = {**MOCK_STATE}
    state_with_cb["signals"] = {
        "BTC/USDT": {
            "score": 0, "active": False,
            "blocked_by": "max_drawdown_exceeded",
        }
    }

    async def _mock(path):
        return state_with_cb if "state" in path else {}

    with patch.object(mcp_server, "_get", side_effect=_mock):
        result = await mcp_server.call_tool("get_active_alerts", {})
    data = json.loads(result[0].text)
    assert data["alert_count"] == 1
    assert data["alerts"][0]["type"] == "circuit_breaker"
    assert data["alerts"][0]["reason"] == "max_drawdown_exceeded"


@pytest.mark.asyncio
async def test_tool_get_signal_history():
    """get_signal_history returns pair info and note."""
    import mcp_server
    with patch.object(mcp_server, "_get", side_effect=_make_mock_get()):
        result = await mcp_server.call_tool(
            "get_signal_history", {"pair": "BTC/USDT", "n": 5}
        )
    data = json.loads(result[0].text)
    assert data["pair"] == "BTC/USDT"
    assert data["n_requested"] == 5
    assert "latest" in data


@pytest.mark.asyncio
async def test_tool_unknown():
    """Unknown tool name returns error dict, not exception."""
    import mcp_server
    result = await mcp_server.call_tool("nonexistent_tool", {})
    data = json.loads(result[0].text)
    assert "error" in data
