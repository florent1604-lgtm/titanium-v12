"""Régressions M2 du réflexe Cloe placé avant l'exécution DEMO."""
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from core.cloe import reflex
from fusion import confluence_demo_engine as demo_engine


def _complete_context() -> dict:
    return {
        "symbol": "BTCUSD",
        "side": 1,
        "n_pillars": 3,
        "pillars": ["trend_sr", "fair_value", "liquidity"],
        "trend_h4": 1,
        "regime_geo": "CLASSIC",
        "lyapunov": 18.0,
        "fisher": 0.12,
        "topo_alert": False,
        "emotion": {
            "available": True,
            "label": "NEUTRE",
            "valence": 0.0,
            "arousal": 0.25,
        },
        "fundamentals": {"score": 29.7, "level": "low"},
        "roundtrip_cost": "1.25",
        "exposure_gross_pct": 12.5,
        "confidence": 0.6,
    }


def test_incomplete_context_fails_open_without_calling_ollama(monkeypatch):
    monkeypatch.setenv("CLOE_REFLEX_ENABLED", "1")
    called = False

    def forbidden_post(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("Ollama ne doit pas être appelé avec un contexte incomplet")

    monkeypatch.setattr("requests.post", forbidden_post)
    ctx = _complete_context()
    ctx["fundamentals"] = None

    result = reflex.judge(ctx)

    assert called is False
    assert result["verdict"] == "OK"
    assert result["available"] is False
    assert result["size_factor"] == 1.0
    assert result["raison"].startswith("contexte incomplet")


def test_configured_timeout_is_hard_capped(monkeypatch):
    monkeypatch.setenv("CLOE_REFLEX_ENABLED", "1")
    monkeypatch.setenv("CLOE_REFLEX_TIMEOUT_S", "25")
    observed = {}

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {"message": {"content": '{"verdict":"STOP","raison":"preuve cohérente"}'}}

    def fake_post(*args, **kwargs):
        observed["timeout"] = kwargs["timeout"]
        return Response()

    monkeypatch.setattr("requests.post", fake_post)

    result = reflex.judge(_complete_context())

    assert observed["timeout"] <= 2.0
    assert result["available"] is True
    assert result["verdict"] == "STOP"


def test_cloe_context_reuses_complete_system_perception():
    build = getattr(demo_engine, "_cloe_context", None)
    assert callable(build), "le mapper de contexte Cloe doit exister"

    state = SimpleNamespace(
        regime=SimpleNamespace(
            trend=1,
            regime="CLASSIC",
            lyapunov_horizon=18.0,
            topology_alert=False,
            fisher_distance=0.12,
            curvature=0.01,
            geo_available=True,
        ),
        fundamentals=SimpleNamespace(
            risk_score=29.7,
            level="low",
            fear_greed=42,
            fear_greed_label="Fear",
            top_news="test",
        ),
        notes={"roundtrip_cost": "1.25"},
        risk=SimpleNamespace(gross_exposure_pct=12.5, equity=127.0),
        emotion=SimpleNamespace(
            label="NEUTRE",
            valence=0.0,
            arousal=0.25,
            available=True,
            would_fade=False,
            would_block=False,
        ),
    )
    decision = SimpleNamespace(
        gates=[
            SimpleNamespace(name="data_valid", passed=True),
            SimpleNamespace(name="trend_sr", passed=True),
            SimpleNamespace(name="fair_value", passed=True),
        ]
    )

    ctx = build(
        symbol="BTCUSD",
        side=1,
        decision=decision,
        state=state,
        confidence=0.6,
    )

    assert ctx["fundamentals"] == {"score": 29.7, "level": "low"}
    assert ctx["roundtrip_cost"] == "1.25"
    assert ctx["exposure_gross_pct"] == 12.5
    assert ctx["emotion"]["available"] is True
    assert ctx["n_pillars"] == 2


def test_slow_reflex_does_not_block_the_async_event_loop():
    call = getattr(demo_engine, "_judge_cloe", None)
    assert callable(call), "l'adaptateur asynchrone Cloe doit exister"

    def slow_judge(ctx):
        time.sleep(0.08)
        return {"verdict": "OK", "available": True, "size_factor": 1.0}

    async def scenario():
        task = asyncio.create_task(call({}, judge_fn=slow_judge))
        await asyncio.sleep(0.01)
        event_loop_remained_live = not task.done()
        result = await task
        return event_loop_remained_live, result

    live, result = asyncio.run(scenario())
    assert live is True
    assert result["verdict"] == "OK"
