"""Consensus trois moteurs : détection pure, aucun ordre ni décision de trading."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import numpy as np
import pandas as pd


def _frame(now, minutes, n=260, up=True):
    end = pd.Timestamp(now).floor(f"{minutes}min") - pd.Timedelta(minutes=minutes)
    idx = pd.date_range(end=end, periods=n, freq=f"{minutes}min", tz="UTC")
    close = np.linspace(100, 120, n) if up else np.linspace(120, 100, n)
    return pd.DataFrame({
        "open": close - 0.1, "high": close + 0.5, "low": close - 0.5,
        "close": close, "v": np.full(n, 100.0),
    }, index=idx)


def _assert_no_case_collisions(value):
    if isinstance(value, dict):
        folded = [str(key).casefold() for key in value]
        assert len(folded) == len(set(folded)), value
        for child in value.values():
            _assert_no_case_collisions(child)
    elif isinstance(value, list):
        for child in value:
            _assert_no_case_collisions(child)


def test_symbol_mapping_is_explicit_and_fail_closed():
    from core.consensus_engine import scoring_symbol

    assert scoring_symbol("BTCUSD") == "BTC/USDT"
    assert scoring_symbol("ethusd") == "ETH/USDT"
    assert scoring_symbol("XAUUSD") == "XAUUSD"
    assert scoring_symbol("EURUSD") == "EURUSD"
    assert scoring_symbol("BTC/USDT") == "BTC/USDT"


def test_correlated_liquidity_evidence_is_capped_to_one_family():
    from core.consensus_engine import build_consensus

    confluence = {
        "available": True, "side": 1,
        "criteria": {"trend_sr": False, "fair_value": False, "liquidity": True,
                     "ote_ob": False, "candle_confirmed": False},
    }
    scoring = {
        "available": True, "side": 1, "score": 4, "score_max": 16,
        "criteria": {"OB_FVG_30M": True, "OB_FVG_15M_CONFIRM": True,
                     "LIQ_SWEEP": True, "DISPLACEMENT": True},
    }
    emotion = {"available": False}
    one = build_consensus("BTCUSD", confluence, scoring, emotion)

    # Ajouter quatre doublons corrélés ne peut jamais dépasser le poids de la famille.
    family = one["families"]["location_liquidity"]
    assert family["weighted_contribution"] <= family["weight"]
    assert family["engines"] == ["confluence", "scoring"]
    assert abs(one["consensus_score"]) <= 100


def test_agreement_and_conflict_are_explicit_between_engines():
    from core.consensus_engine import build_consensus

    conf = {"available": True, "side": -1,
            "criteria": {"trend_sr": True, "fair_value": True,
                         "liquidity": True, "ote_ob": True,
                         "candle_confirmed": False}}
    score = {"available": True, "side": -1, "score": 8, "score_max": 16,
             "criteria": {"EMA200_H4": True, "STRUCT_H2H1": True,
                          "OB_FVG_30M": True}}
    emo_ok = {"available": True, "direction": -1, "confidence": 0.8,
              "valence": -50, "arousal": 60, "label": "PEUR"}
    agreed = build_consensus("BTCUSD", conf, score, emo_ok)
    assert agreed["agreement"] is True and agreed["conflict"] is False
    assert set(agreed["agreeing_engines"]) == {"confluence", "scoring", "emotion"}
    assert agreed["status"] == "CONFIRMED"
    assert agreed["consensus_score"] < 0

    emo_bad = dict(emo_ok, direction=1, label="CAPITULATION")
    conflicted = build_consensus("BTCUSD", conf, score, emo_bad)
    assert conflicted["conflict"] is True
    assert conflicted["status"] == "CONFLICT"
    assert "emotion" in conflicted["opposing_engines"]


def test_no_direction_is_insufficient_and_non_decisional():
    from core.consensus_engine import build_consensus

    out = build_consensus(
        "XAUUSD",
        {"available": False}, {"available": False}, {"available": False},
    )
    assert out["status"] == "INSUFFICIENT"
    assert out["consensus_score"] == 0
    assert out["m2_required"] is True
    assert out["decision_capability"] is False
    assert out["orders_capability"] is False


def test_scan_isolates_symbol_errors_and_never_accepts_a_place_dependency(monkeypatch):
    from core import consensus_engine as ce

    now = datetime(2026, 7, 20, 12, 5, tzinfo=timezone.utc)
    minutes = {"M1": 1, "M5": 5, "M15": 15, "M30": 30,
               "H1": 60, "H2": 120, "H4": 240, "D1": 1440}

    def rates(symbol, tf, n):
        if symbol == "BOOM":
            raise RuntimeError("provider down")
        return _frame(now, minutes[tf], n=max(n, 260))

    class Decision:
        side = 1
        verdict = "ENTER"
        code = "ENTER_CONFLUENCE"
        gates = [SimpleNamespace(name="trend_sr", passed=True),
                 SimpleNamespace(name="fair_value", passed=False),
                 SimpleNamespace(name="liquidity", passed=True),
                 SimpleNamespace(name="ote_ob", passed=True),
                 SimpleNamespace(name="candle_confirmed", passed=False)]

    monkeypatch.setattr(ce, "_run_confluence", lambda *a, **k: (Decision(), {"data_valid": True}))
    monkeypatch.setattr(ce, "_run_scoring", lambda *a, **k: (7, "ACHAT", [], {
        "score_max": 16, "EMA200_H4": True, "STRUCT_H2H1": True,
        "OB_FVG_30M": True, "ema200_h4": 101.25,
    }))
    emotion = SimpleNamespace(available=True, valence=30.0, arousal=50.0,
                              label="OPTIMISME", confidence=0.8, stale=False,
                              contrarian=None, filter_block=None)

    report = asyncio.run(ce.run_once(
        [{"symbol": "BOOM", "ltf": "M15", "htf": "H4", "venue": "cfd"},
         {"symbol": "BTCUSD", "ltf": "M15", "htf": "H4", "venue": "crypto"}],
        now=now, rates_fn=rates, emotion_fn=lambda symbol: emotion,
    ))
    by_symbol = {row["symbol"]: row for row in report["results"]}
    assert by_symbol["BOOM"]["status"] == "ERROR"
    assert by_symbol["BTCUSD"]["status"] in {"CONFIRMED", "UNCONFIRMED", "CONFLICT"}
    assert by_symbol["BTCUSD"]["scoring_symbol"] == "BTC/USDT"
    scoring = by_symbol["BTCUSD"]["engines"]["scoring"]
    assert scoring["criteria"]["EMA200_H4"] is True
    assert scoring["context"]["ema200_h4"] == 101.25
    _assert_no_case_collisions(by_symbol["BTCUSD"])
    assert ce.status_snapshot()["heartbeat"]["n_orders"] == 0


def test_scan_executes_real_confluence_and_scoring_with_closed_frames():
    """Intégration locale des vrais moteurs ; seules les données/émotion sont injectées."""
    from core import consensus_engine as ce

    now = datetime(2026, 7, 20, 12, 5, tzinfo=timezone.utc)
    minutes = {"M5": 5, "M15": 15, "H1": 60, "H4": 240, "D1": 1440}

    def rates(symbol, tf, n):
        return _frame(now, minutes[tf], n=max(n, 320))

    emotion = SimpleNamespace(available=True, valence=25.0, arousal=45.0,
                              label="OPTIMISME", confidence=0.75, stale=False,
                              contrarian=None, filter_block=None)
    report = asyncio.run(ce.run_once(
        [{"symbol": "BTCUSD", "ltf": "M15", "htf": "H4", "venue": "crypto"}],
        now=now, rates_fn=rates, emotion_fn=lambda symbol: emotion,
    ))
    row = report["results"][0]
    assert row["status"] != "ERROR"
    assert row["engines"]["confluence"]["available"] is True
    assert row["engines"]["scoring"]["score_max"] == 16
    assert row["orders_capability"] is False


def test_status_route_is_read_only_snapshot():
    # L'interpréteur embeddable de validation ne contient volontairement pas FastAPI :
    # contrat statique de route + contrat dynamique du snapshot, sans serveur.
    from pathlib import Path
    from core.consensus_engine import status_snapshot

    route_source = Path("api/consensus_routes.py").read_text(encoding="utf-8")
    server_source = Path("api/api_server.py").read_text(encoding="utf-8")
    assert '@router.get("/consensus/status")' in route_source
    assert "app.include_router(consensus_router)" in server_source
    body = status_snapshot()
    assert body["detection_only"] is True
    assert body["m2_required"] is True
    assert body["orders_capability"] is False


# --- Calibration Hermes/Florent du 21/07/2026 ------------------------------------------

def test_familles_a_poids_egaux():
    """Équilibre commun voulu par Florent : aucune famille ne domine."""
    from core.consensus_engine import FAMILY_WEIGHTS
    assert len(set(FAMILY_WEIGHTS.values())) == 1
    assert abs(sum(FAMILY_WEIGHTS.values()) - 1.0) < 1e-9


def test_emotion_seule_est_plafonnee_a_la_moitie_de_la_famille():
    """À poids égaux l'émotion nourrit DEUX familles : seule, elle pourrait piloter 40 % du
    score et redevenir le pilier. Plafonnée à la moitié d'une famille → 20 % agrégés max."""
    from core.consensus_engine import _family, FAMILY_WEIGHTS
    w = FAMILY_WEIGHTS["behavioral"]
    seule = _family("behavioral", {"emotion": 1.0})
    assert abs(seule["weighted_contribution"]) <= w * 0.5 + 1e-9
    # accompagnée d'une preuve INDÉPENDANTE, la famille peut aller au-delà du plafond solo
    accompagnee = _family("behavioral", {"emotion": 1.0, "scoring": 1.0})
    assert abs(accompagnee["weighted_contribution"]) > abs(seule["weighted_contribution"])


def test_disponibilite_distincte_de_la_preuve_directionnelle():
    """Un moteur qui vote ZÉRO est disponible mais n'apporte aucune évidence."""
    from core.consensus_engine import _family
    muet = _family("timing", {"scoring": 0.0})
    parlant = _family("timing", {"scoring": 0.8})
    assert muet["engines"] == ["scoring"]        # il a bien répondu (disponibilité)
    assert muet["directional"] is False          # mais il n'a rien dit (preuve)
    assert parlant["directional"] is True
