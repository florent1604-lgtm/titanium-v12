"""R3 rev.2 — plafonds de risque portefeuille FAIL-CLOSED (revue Codex 10/07/2026).

Couvre : gross/net signés par stratégie/cluster/portefeuille, NaN/inf, état
malformé (RISK_STATE_UNAVAILABLE), agrégation crypto paper, equity live après
drawdown, égalité exacte au plafond. Isolation des états : tout se fait via
`monkeypatch.setitem/setattr` (restauration automatique en fin de test) — les
fichiers d'état sur disque ne sont jamais touchés.
"""
import math
import threading
from concurrent.futures import ThreadPoolExecutor

import core.portfolio_risk as pr


# ── Doubles crypto (PaperEngine minimal) ─────────────────────────────────────

class _FakePos:
    def __init__(self, side, size_usdt):
        self.side = side
        self._size = size_usdt

    def current_size_usdt(self):
        return self._size


class _FakeCrypto:
    def __init__(self, positions=None, equity=10000.0):
        self.positions = positions or {}
        self._eq = equity

    def equity_with_unrealized(self):
        return self._eq


# ── Mise en place commune ────────────────────────────────────────────────────

def _env(monkeypatch, swing_pos=None, forex_pos=None, crypto=None,
         swing_eq=10000.0, forex_eq=10000.0,
         strategy=5000.0, cluster=5000.0, gross=5000.0, net=5000.0):
    """États moteurs contrôlés + plafonds explicites. monkeypatch restaure tout."""
    from core.swing_engine import swing_state
    from core.forex_engine import forex_state
    monkeypatch.setitem(swing_state, "positions", swing_pos or {})
    monkeypatch.setitem(swing_state, "equity", swing_eq)
    monkeypatch.setitem(forex_state, "positions", forex_pos or {})
    monkeypatch.setitem(forex_state, "equity", forex_eq)
    fake = crypto if crypto is not None else _FakeCrypto()
    monkeypatch.setattr(pr, "_crypto_engine", lambda: fake)
    monkeypatch.setattr(pr, "RISK_MAX_STRATEGY_PCT", strategy)
    monkeypatch.setattr(pr, "RISK_MAX_CLUSTER_PCT", cluster)
    monkeypatch.setattr(pr, "RISK_MAX_GROSS_PCT", gross)
    monkeypatch.setattr(pr, "RISK_MAX_NET_PCT", net)


# ── Plafonds gross historiques (audit) ───────────────────────────────────────

def test_cluster_cap_blocks_correlated_index(monkeypatch):
    _env(monkeypatch, cluster=60.0,   # 60 % de 10000 = 6000
         swing_pos={"USTECH": {"side": "long", "notional_eur": 4700.0}})

    # NAS100.fs = même cluster US_INDICES : 4700 + 4700 = 9400 > 6000 → bloqué
    ok, reason = pr.check_can_open("swing", "NAS100.fs", 4700.0, 10000.0, "long")
    assert not ok and "cluster" in reason.lower(), reason

    # XAUUSD = AUTRE cluster (GOLD) → autorisé
    ok2, _ = pr.check_can_open("swing", "XAUUSD", 4700.0, 10000.0, "long")
    assert ok2


def test_strategy_cap_blocks(monkeypatch):
    _env(monkeypatch, strategy=90.0,  # 90 % de 10000 = 9000
         swing_pos={"XAUUSD": {"side": "long", "notional_eur": 8000.0}})
    ok, reason = pr.check_can_open("swing", "HK50", 2000.0, 10000.0, "long")
    assert not ok and "stratégie" in reason.lower(), reason


def test_gross_cap_across_engines(monkeypatch):
    # Equity agrégée LIVE = 10000 (swing) + 10000 (forex) + 10000 (crypto) = 30000
    _env(monkeypatch, gross=100.0,    # 100 % de 30000 = 30000
         swing_pos={"USTECH": {"side": "long", "notional_eur": 20000.0}},
         forex_pos={"EURUSD": {"side": "long", "notional_eur": 9000.0}})
    # gross courant 29000 ; +2000 = 31000 > 30000 → bloqué
    ok, reason = pr.check_can_open("forex", "GBPUSD", 2000.0, 10000.0, "long")
    assert not ok and "gross" in reason.lower(), reason


# ── Net signé (nouveau, bloquant n°1 de la revue) ────────────────────────────

def test_net_cap_long_blocked_short_allowed(monkeypatch):
    _env(monkeypatch, net=100.0,      # |net| ≤ 100 % de 30000 = 30000
         swing_pos={"USTECH": {"side": "long", "notional_eur": 20000.0}},
         forex_pos={"EURUSD": {"side": "long", "notional_eur": 9500.0}})
    # net courant +29500 ; +1000 long = 30500 > 30000 → bloqué
    ok, reason = pr.check_can_open("forex", "GBPUSD", 1000.0, 10000.0, "long")
    assert not ok and "net" in reason.lower(), reason
    # le même notionnel en SHORT réduit le net (28500) → autorisé
    ok2, r2 = pr.check_can_open("forex", "GBPUSD", 1000.0, 10000.0, "short")
    assert ok2, r2


def test_shorts_count_in_gross_not_net(monkeypatch):
    _env(monkeypatch,
         swing_pos={"USTECH": {"side": "long", "notional_eur": 5000.0},
                    "HK50": {"side": "short", "notional_eur": 5000.0}})
    snap = pr.exposure_snapshot()
    assert snap["ok"]
    assert snap["gross_eur"] == 10000.0
    assert snap["net_eur"] == 0.0
    assert snap["by_strategy"]["swing"]["net_eur"] == 0.0


# ── Entrées invalides (bloquant n°2) ─────────────────────────────────────────

def test_invalid_inputs_fail_closed(monkeypatch):
    _env(monkeypatch)
    cases = [
        ("notional NaN", ("swing", "USTECH", math.nan, 10000.0, "long")),
        ("notional inf", ("swing", "USTECH", math.inf, 10000.0, "long")),
        ("notional 0", ("swing", "USTECH", 0.0, 10000.0, "long")),
        ("notional négatif", ("swing", "USTECH", -100.0, 10000.0, "long")),
        ("notional str", ("swing", "USTECH", "abc", 10000.0, "long")),
        ("equity NaN", ("swing", "USTECH", 100.0, math.nan, "long")),
        ("equity 0", ("swing", "USTECH", 100.0, 0.0, "long")),
        ("side inconnu", ("swing", "USTECH", 100.0, 10000.0, "hold")),
        ("side None", ("swing", "USTECH", 100.0, 10000.0, None)),
    ]
    for label, args in cases:
        ok, reason = pr.check_can_open(*args)
        assert not ok and "RISK_INPUT_INVALID" in reason, f"{label}: {reason}"


def test_invalid_cap_config_fail_closed(monkeypatch):
    _env(monkeypatch)
    monkeypatch.setattr(pr, "RISK_MAX_GROSS_PCT", math.nan)
    ok, reason = pr.check_can_open("swing", "USTECH", 100.0, 10000.0, "long")
    assert not ok and "RISK_INPUT_INVALID" in reason, reason


# ── État malformé (bloquant n°3) : champ manquant ≠ zéro ─────────────────────

def test_malformed_position_fail_closed(monkeypatch):
    for bad in ({"side": "long"},                              # notional absent
                {"notional_eur": 1000.0},                      # side absent
                {"side": "long", "notional_eur": math.nan},    # NaN stocké
                {"side": "achat", "notional_eur": 1000.0},     # side inconnu
                "pas-un-dict"):
        _env(monkeypatch, swing_pos={"USTECH": bad} if isinstance(bad, dict) else bad)
        ok, reason = pr.check_can_open("forex", "GBPUSD", 100.0, 10000.0, "long")
        assert not ok and "RISK_STATE_UNAVAILABLE" in reason, f"{bad!r}: {reason}"
        snap = pr.exposure_snapshot()
        assert not snap["ok"] and snap["errors"]


def test_crypto_state_unreadable_fail_closed(monkeypatch):
    _env(monkeypatch)

    def boom():
        raise RuntimeError("paper_state corrompu")
    monkeypatch.setattr(pr, "_crypto_engine", boom)
    ok, reason = pr.check_can_open("swing", "USTECH", 100.0, 10000.0, "long")
    assert not ok and "RISK_STATE_UNAVAILABLE" in reason, reason


# ── Agrégation crypto (bloquant n°4) ─────────────────────────────────────────

def test_crypto_counts_in_gross_and_cluster(monkeypatch):
    crypto = _FakeCrypto(positions={
        "BTC/USDT": _FakePos("LONG", 5000.0),
        "ETH/USDT": _FakePos("SHORT", 3000.0),
    })
    _env(monkeypatch, crypto=crypto, gross=100.0)   # cap gross = 30000
    snap = pr.exposure_snapshot()
    assert snap["by_strategy"]["crypto"]["gross_eur"] == 8000.0
    assert snap["by_strategy"]["crypto"]["net_eur"] == 2000.0
    assert snap["by_cluster"]["CRYPTO"]["gross_eur"] == 8000.0

    # cluster CRYPTO partagé avec un symbole MT5 : BTCUSD (swing) s'y agrège
    monkeypatch.setattr(pr, "RISK_MAX_CLUSTER_PCT", 60.0)   # 60 % de 10000 = 6000
    ok, reason = pr.check_can_open("swing", "BTCUSD", 1000.0, 10000.0, "long")
    assert not ok and "cluster" in reason.lower(), reason   # 8000 + 1000 > 6000

    # et le gross portefeuille inclut la poche crypto : 8000 + 23000 > 30000
    monkeypatch.setattr(pr, "RISK_MAX_CLUSTER_PCT", 5000.0)
    ok2, r2 = pr.check_can_open("swing", "USTECH", 23000.0, 10000.0, "long")
    assert not ok2 and "gross" in r2.lower(), r2


# ── Equity live (drawdown) et frontière exacte ───────────────────────────────

def test_drawdown_tightens_portfolio_caps(monkeypatch):
    pos = {"USTECH": {"side": "long", "notional_eur": 36000.0}}
    # Avant drawdown : equity live 10000+10000+10000=30000, gross cap 150 % = 45000
    _env(monkeypatch, swing_pos=dict(pos), gross=150.0)
    ok, _ = pr.check_can_open("forex", "GBPUSD", 2000.0, 10000.0, "long")
    assert ok
    # Swing en drawdown à 5000 : equity live 25000, cap 37500 < 36000+2000 → bloqué
    _env(monkeypatch, swing_pos=dict(pos), swing_eq=5000.0, gross=150.0)
    ok2, reason = pr.check_can_open("forex", "GBPUSD", 2000.0, 10000.0, "long")
    assert not ok2 and "gross" in reason.lower(), reason


def test_exact_cap_equality_passes(monkeypatch):
    _env(monkeypatch, strategy=90.0,   # 90 % de 10000 = 9000
         swing_pos={"XAUUSD": {"side": "long", "notional_eur": 7000.0}})
    ok, reason = pr.check_can_open("swing", "HK50", 2000.0, 10000.0, "long")
    assert ok, f"égalité exacte au plafond doit passer: {reason}"
    ok2, r2 = pr.check_can_open("swing", "HK50", 2000.01, 10000.0, "long")
    assert not ok2 and "stratégie" in r2.lower(), r2


def test_concurrent_swing_forex_open_is_atomic(monkeypatch):
    """Deux ouvertures du même cluster ne peuvent valider le même snapshot."""
    _env(monkeypatch, cluster=60.0)
    from core.swing_engine import _open_position as open_swing, swing_state
    from core.forex_engine import _open_position as open_forex, forex_state

    # Piège de régression pour l'ancien câblage : il forçait les deux appels
    # check_can_open() à finir avant leurs insertions séparées.
    original_check = pr.check_can_open
    old_wiring_barrier = threading.Barrier(2)

    def synchronized_legacy_check(*args):
        result = original_check(*args)
        old_wiring_barrier.wait(timeout=2)
        return result

    monkeypatch.setattr(pr, "check_can_open", synchronized_legacy_check)
    start = threading.Barrier(3)

    def swing_attempt():
        start.wait(timeout=2)
        return open_swing(
            "USTECH", "long", 100.0, 1.0,
            {"sl_atr": 2.0, "tp_ladder": [1.5, 2.5, 4.0]},
        )

    def forex_attempt():
        start.wait(timeout=2)
        return open_forex("NAS100.fs", "long", 100.0, 1.0)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(swing_attempt), pool.submit(forex_attempt)]
        start.wait(timeout=2)
        accepted = [future.result(timeout=3) for future in futures]

    assert accepted.count(True) == 1, accepted
    assert len(swing_state["positions"]) + len(forex_state["positions"]) == 1
