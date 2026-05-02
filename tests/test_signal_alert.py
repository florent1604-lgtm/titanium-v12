"""tests/test_signal_alert.py — Tests pour SignalAlertEngine."""
import asyncio
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


SIGNAL_ACTIVE_7 = {
    "symbol": "BTC/USDT", "score": 7, "score_max": 11,
    "side": "ACHAT", "active": True,
    "price": 95000.0, "sl": 94000.0, "tp1": 96500.0, "rr": 1.5,
    "confs": ["CHoCH", "OB"], "regime": "TREND",
}
SIGNAL_ACTIVE_5 = {**SIGNAL_ACTIVE_7, "score": 5}
SIGNAL_INACTIVE  = {**SIGNAL_ACTIVE_7, "active": False}


# ── _build_message ────────────────────────────────────────────────────────────

def test_build_message_achat():
    from assistant.signal_alert import SignalAlertEngine
    eng = SignalAlertEngine()
    msg = eng._build_message("BTC/USDT", SIGNAL_ACTIVE_7)
    assert "Bitcoin" in msg
    assert "achat" in msg.lower()
    assert "7" in msg
    assert any(p in msg for p in ("95 000", "95000", "95,000"))


def test_build_message_vente():
    from assistant.signal_alert import SignalAlertEngine
    eng = SignalAlertEngine()
    sig = {**SIGNAL_ACTIVE_7, "side": "VENTE"}
    msg = eng._build_message("BTC/USDT", sig)
    assert "vente" in msg.lower()


def test_build_message_score_premium():
    from assistant.signal_alert import SignalAlertEngine
    eng = SignalAlertEngine()
    msg = eng._build_message("BTC/USDT", {**SIGNAL_ACTIVE_7, "score": 9})
    assert "premium" in msg.lower()


def test_build_message_paxg():
    from assistant.signal_alert import SignalAlertEngine
    eng = SignalAlertEngine()
    msg = eng._build_message("PAXG/USDT", SIGNAL_ACTIVE_7)
    assert "Gold" in msg or "PAX" in msg


# ── _is_on_cooldown ───────────────────────────────────────────────────────────

def test_cooldown_fresh():
    from assistant.signal_alert import SignalAlertEngine
    eng = SignalAlertEngine()
    assert eng._is_on_cooldown("BTC/USDT") is False


def test_cooldown_active():
    from assistant.signal_alert import SignalAlertEngine
    eng = SignalAlertEngine()
    eng._cooldowns["BTC/USDT"] = time.monotonic()
    assert eng._is_on_cooldown("BTC/USDT") is True


def test_cooldown_expired():
    from assistant.signal_alert import SignalAlertEngine
    eng = SignalAlertEngine()
    eng._cooldowns["BTC/USDT"] = time.monotonic() - 400  # > 300s
    assert eng._is_on_cooldown("BTC/USDT") is False


# ── _check_signals ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_check_triggers_alert():
    """Score ≥ 7 + active + first time → alerte déclenchée."""
    from assistant.signal_alert import SignalAlertEngine
    eng = SignalAlertEngine()
    eng._trigger_alert = AsyncMock()

    with patch("assistant.signal_alert.SYMBOLS", ["BTC/USDT"]), \
         patch("execution.signal_manager.signals", {"BTC/USDT": SIGNAL_ACTIVE_7}):
        await eng._check_signals()

    eng._trigger_alert.assert_awaited_once_with("BTC/USDT", SIGNAL_ACTIVE_7)


@pytest.mark.asyncio
async def test_check_no_trigger_low_score():
    """Score < 7 → pas d'alerte."""
    from assistant.signal_alert import SignalAlertEngine
    eng = SignalAlertEngine()
    eng._trigger_alert = AsyncMock()

    with patch("assistant.signal_alert.SYMBOLS", ["BTC/USDT"]), \
         patch("execution.signal_manager.signals", {"BTC/USDT": SIGNAL_ACTIVE_5}):
        await eng._check_signals()

    eng._trigger_alert.assert_not_awaited()


@pytest.mark.asyncio
async def test_check_no_trigger_inactive():
    """Signal inactif → pas d'alerte."""
    from assistant.signal_alert import SignalAlertEngine
    eng = SignalAlertEngine()
    eng._trigger_alert = AsyncMock()

    with patch("assistant.signal_alert.SYMBOLS", ["BTC/USDT"]), \
         patch("execution.signal_manager.signals", {"BTC/USDT": SIGNAL_INACTIVE}):
        await eng._check_signals()

    eng._trigger_alert.assert_not_awaited()


@pytest.mark.asyncio
async def test_check_no_trigger_cooldown():
    """Signal qualifié mais en cooldown → pas d'alerte."""
    from assistant.signal_alert import SignalAlertEngine
    eng = SignalAlertEngine()
    eng._cooldowns["BTC/USDT"] = time.monotonic()
    eng._trigger_alert = AsyncMock()

    with patch("assistant.signal_alert.SYMBOLS", ["BTC/USDT"]), \
         patch("execution.signal_manager.signals", {"BTC/USDT": SIGNAL_ACTIVE_7}):
        await eng._check_signals()

    eng._trigger_alert.assert_not_awaited()


@pytest.mark.asyncio
async def test_check_no_double_trigger():
    """Signal déjà actif au check précédent → pas de double alerte."""
    from assistant.signal_alert import SignalAlertEngine
    eng = SignalAlertEngine()
    eng._last_active["BTC/USDT"] = True  # était déjà actif
    eng._trigger_alert = AsyncMock()

    with patch("assistant.signal_alert.SYMBOLS", ["BTC/USDT"]), \
         patch("execution.signal_manager.signals", {"BTC/USDT": SIGNAL_ACTIVE_7}):
        await eng._check_signals()

    eng._trigger_alert.assert_not_awaited()


@pytest.mark.asyncio
async def test_check_queue_limit():
    """File pleine (MAX_QUEUE) → alerte ignorée."""
    from assistant.signal_alert import SignalAlertEngine
    eng = SignalAlertEngine()
    eng._queue_count = eng.MAX_QUEUE
    eng._trigger_alert = AsyncMock()

    with patch("assistant.signal_alert.SYMBOLS", ["BTC/USDT"]), \
         patch("execution.signal_manager.signals", {"BTC/USDT": SIGNAL_ACTIVE_7}):
        await eng._check_signals()

    eng._trigger_alert.assert_not_awaited()


# ── _trigger_alert ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_trigger_cancels_if_signal_disappeared():
    """Alerte annulée si le signal disparaît entre la détection et l'envoi."""
    from assistant.signal_alert import SignalAlertEngine
    eng = SignalAlertEngine()
    eng._send_to_jarvis = AsyncMock()

    # Signal inactif au moment de l'envoi
    with patch("execution.signal_manager.signals", {"BTC/USDT": SIGNAL_INACTIVE}):
        await eng._trigger_alert("BTC/USDT", SIGNAL_ACTIVE_7)

    eng._send_to_jarvis.assert_not_awaited()


@pytest.mark.asyncio
async def test_trigger_sets_cooldown():
    """Après une alerte envoyée, le cooldown est posé."""
    from assistant.signal_alert import SignalAlertEngine
    eng = SignalAlertEngine()
    eng._send_to_jarvis = AsyncMock()

    with patch("execution.signal_manager.signals", {"BTC/USDT": SIGNAL_ACTIVE_7}):
        await eng._trigger_alert("BTC/USDT", SIGNAL_ACTIVE_7)

    assert "BTC/USDT" in eng._cooldowns
    eng._send_to_jarvis.assert_awaited_once()


@pytest.mark.asyncio
async def test_trigger_resilient_to_jarvis_down():
    """Pas d'exception levée si JARVIS est hors ligne."""
    from assistant.signal_alert import SignalAlertEngine
    eng = SignalAlertEngine()

    async def _fail(*a, **kw):
        raise ConnectionRefusedError("JARVIS offline")

    eng._send_to_jarvis = _fail

    with patch("execution.signal_manager.signals", {"BTC/USDT": SIGNAL_ACTIVE_7}):
        # Ne doit pas lever d'exception
        await eng._trigger_alert("BTC/USDT", SIGNAL_ACTIVE_7)
