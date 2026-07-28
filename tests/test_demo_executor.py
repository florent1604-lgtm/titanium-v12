"""Étape D — garde-fou FAIL-CLOSED de l'exécution DEMO.

Prouve : aucune exécution sauf compte DÉMO attendu ; le compte RÉEL et tout
login inattendu sont refusés ; désarmé par défaut ; kill-switch et marge.
"""
import pytest

from execution import demo_mt5_executor as dx


class _Info:
    def __init__(self, login, trade_mode, equity=1000.0, balance=1000.0, margin_free=1000.0, server="Axi", currency="USD"):
        self.login = login
        self.trade_mode = trade_mode
        self.equity = equity
        self.balance = balance
        self.margin_free = margin_free
        self.server = server
        self.currency = currency


class _FakeMT5:
    ACCOUNT_TRADE_MODE_DEMO = 0
    ACCOUNT_TRADE_MODE_REAL = 2

    def __init__(self, info):
        self._info = info

    def account_info(self):
        return self._info


def _guards(**kw):
    # construit des garde-fous armés pour le test (sans dépendre de l'env)
    base = dict(enabled=True, risk_pct=0.5, max_positions=3,
                daily_loss_limit_pct=5.0, max_spread_points=40, min_free_margin_pct=40.0)
    base.update(kw)
    return dx.DemoGuards(**base)


def test_demo_account_accepted():
    mt5 = _FakeMT5(_Info(login=dx.EXPECTED_DEMO_LOGIN, trade_mode=0))
    acc = dx.assert_demo_or_raise(mt5)
    assert acc["login"] == dx.EXPECTED_DEMO_LOGIN


def test_real_mode_refused():
    mt5 = _FakeMT5(_Info(login=999, trade_mode=2))   # mode RÉEL
    with pytest.raises(dx.DemoExecutionRefused) as e:
        dx.assert_demo_or_raise(mt5)
    assert "NOT_DEMO" in str(e.value)


def test_real_login_refused_even_if_mode_says_demo():
    # défense en profondeur : login réel connu → refus même si trade_mode=0
    mt5 = _FakeMT5(_Info(login=dx.REAL_ACCOUNT_LOGIN, trade_mode=0))
    with pytest.raises(dx.DemoExecutionRefused) as e:
        dx.assert_demo_or_raise(mt5)
    assert "REAL_LOGIN" in str(e.value)


def test_unexpected_demo_login_refused():
    mt5 = _FakeMT5(_Info(login=12345678, trade_mode=0))
    with pytest.raises(dx.DemoExecutionRefused) as e:
        dx.assert_demo_or_raise(mt5)
    assert "UNEXPECTED_LOGIN" in str(e.value)


def test_no_account_refused():
    mt5 = _FakeMT5(None)
    with pytest.raises(dx.DemoExecutionRefused) as e:
        dx.assert_demo_or_raise(mt5)
    assert "NO_ACCOUNT" in str(e.value)


def test_preflight_disabled_by_default():
    mt5 = _FakeMT5(_Info(login=dx.EXPECTED_DEMO_LOGIN, trade_mode=0))
    # garde par défaut (env non armé) → désarmé
    r = dx.preflight(mt5, guards=dx.DemoGuards(enabled=False))
    assert not r["ok"] and "désarmé" in r["reason"]


def test_preflight_ok_when_armed_and_demo():
    mt5 = _FakeMT5(_Info(login=dx.EXPECTED_DEMO_LOGIN, trade_mode=0))
    r = dx.preflight(mt5, guards=_guards(), day_start_equity=1000.0)
    assert r["ok"] and r["account"]["login"] == dx.EXPECTED_DEMO_LOGIN


def test_preflight_kill_switch_on_daily_loss():
    mt5 = _FakeMT5(_Info(login=dx.EXPECTED_DEMO_LOGIN, trade_mode=0, equity=940.0))
    r = dx.preflight(mt5, guards=_guards(daily_loss_limit_pct=5.0), day_start_equity=1000.0)
    assert not r["ok"] and "KILL_SWITCH" in r["reason"]


def test_preflight_low_margin_refused():
    mt5 = _FakeMT5(_Info(login=dx.EXPECTED_DEMO_LOGIN, trade_mode=0, equity=1000.0, margin_free=100.0))
    r = dx.preflight(mt5, guards=_guards(min_free_margin_pct=40.0), day_start_equity=1000.0)
    assert not r["ok"] and "LOW_MARGIN" in r["reason"]


# ── Sizing + envoi d'ordre (fake MT5) ────────────────────────────────────────

class _SymInfo:
    def __init__(self, trade_mode=1, point=1.0, tick_size=1.0, tick_value=1.0,
                 vmin=0.01, vstep=0.01, vmax=100.0, digits=2):
        self.trade_mode = trade_mode
        self.point = point
        self.trade_tick_size = tick_size
        self.trade_tick_value = tick_value
        self.volume_min = vmin
        self.volume_step = vstep
        self.volume_max = vmax
        self.digits = digits


class _Tick:
    def __init__(self, bid, ask):
        self.bid = bid; self.ask = ask


class _Res:
    def __init__(self, retcode, comment=""):
        self.retcode = retcode; self.comment = comment


class _TradeMT5(_FakeMT5):
    SYMBOL_TRADE_MODE_DISABLED = 0
    TRADE_ACTION_DEAL = 1
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    ORDER_TIME_GTC = 0
    ORDER_FILLING_IOC = 1
    TRADE_RETCODE_DONE = 10009

    def __init__(self, info, sym=None, tick=None, retcode=10009):
        super().__init__(info)
        self._sym = sym or _SymInfo()
        self._tick = tick or _Tick(bid=100.0, ask=100.2)
        self._retcode = retcode
        self.sent_request = None

    def symbol_select(self, s, on): return True
    def symbol_info(self, s): return self._sym
    def symbol_info_tick(self, s): return self._tick
    def order_calc_profit(self, otype, sym, lot, entry, sl):
        return -1.0   # perte finie, dans le budget (rev.3 : verify_risk fail-closed)
    def order_check(self, req):
        class _C: retcode = 0; comment = ""
        return _C()
    def order_send(self, req):
        self.sent_request = req
        return _Res(self._retcode)


def test_compute_lot_from_risk():
    mt5 = _TradeMT5(_Info(login=dx.EXPECTED_DEMO_LOGIN, trade_mode=0),
                    sym=_SymInfo(tick_size=1.0, tick_value=1.0, vmin=0.01, vstep=0.01))
    # dist=10, money_per_lot=10 ; risk 50 → 5.0 lots
    assert dx.compute_lot(mt5, "USTECH", entry=100.0, sl=90.0, risk_money=50.0) == 5.0


def test_place_order_demo_ok_and_sizing_5pct():
    info = _Info(login=dx.EXPECTED_DEMO_LOGIN, trade_mode=0, equity=1000.0)
    mt5 = _TradeMT5(info, sym=_SymInfo(tick_size=1.0, tick_value=1.0), tick=_Tick(100.0, 100.1))
    r = dx.place_market_order(mt5, "USTECH", "long", atr=5.0, sl_atr_mult=2.0,
                              guards=_guards(risk_pct=5.0), day_start_equity=1000.0)
    assert r["sent"] and r["side"] == "long"
    assert r["risk_money"] == 50.0            # 5% de 1000
    assert mt5.sent_request["type"] == mt5.ORDER_TYPE_BUY


def test_place_order_refused_on_real_account():
    mt5 = _TradeMT5(_Info(login=dx.REAL_ACCOUNT_LOGIN, trade_mode=0))
    r = dx.place_market_order(mt5, "USTECH", "long", atr=5.0, guards=_guards())
    assert not r["sent"] and "REAL_LOGIN" in r["reason"]
    assert mt5.sent_request is None           # AUCUN ordre envoyé


def test_tests_never_write_the_production_day_ref(tmp_path, monkeypatch):
    """Incident 15/07/2026 : un test avec un faux MT5 (equity=1000.0) écrivait la
    référence journalière de PRODUCTION → le kill-switch se serait appuyé sur une
    base inventée (1000.0 alors que le compte réel était à 950.08).
    `day_ref_path` doit être injectable et la prod rester intouchée."""
    prod = tmp_path / "prod_day_ref.json"
    monkeypatch.setattr(dx, "DAY_REF_PATH", prod)
    isolated = tmp_path / "isolated.json"
    info = _Info(login=dx.EXPECTED_DEMO_LOGIN, trade_mode=0, equity=1000.0)
    mt5 = _TradeMT5(info, sym=_SymInfo(tick_size=1.0, tick_value=1.0), tick=_Tick(100.0, 100.1))
    r = dx.place_market_order(mt5, "USTECH", "long", atr=5.0, guards=_guards(risk_pct=5.0),
                              day_ref_path=isolated)          # pas de day_start_equity
    assert r["sent"]
    assert isolated.exists()                                   # le test écrit CHEZ LUI
    assert not prod.exists()                                   # et JAMAIS en production


def test_place_order_market_closed():
    info = _Info(login=dx.EXPECTED_DEMO_LOGIN, trade_mode=0)
    mt5 = _TradeMT5(info, sym=_SymInfo(trade_mode=0))   # SYMBOL_TRADE_MODE_DISABLED
    # day_start_equity fourni : sinon ce test écrirait la référence de PRODUCTION.
    r = dx.place_market_order(mt5, "HSI.fs", "long", atr=5.0, guards=_guards(),
                              day_start_equity=1000.0)
    assert not r["sent"] and "MARKET_CLOSED" in r["reason"]


def test_spread_guard_en_pourcentage_bloque_large():
    # spread 1% (bid 100 / ask 101) > 0.5% → refusé, message en %
    info = _Info(login=dx.EXPECTED_DEMO_LOGIN, trade_mode=0, equity=1000.0)
    mt5 = _TradeMT5(info, sym=_SymInfo(tick_size=1.0, tick_value=1.0),
                    tick=_Tick(100.0, 101.0))
    r = dx.place_market_order(mt5, "USTECH", "long", atr=5.0,
                              guards=_guards(max_spread_pct=0.5), day_start_equity=1000.0)
    assert not r["sent"] and "RISK_SPREAD" in r["reason"] and "%" in r["reason"]


def test_spread_crypto_etroit_passe_le_garde():
    # BTC : 12 USD sur ~64240 = 0.019% (1200 « points » mais % minuscule) → NE bloque plus
    info = _Info(login=dx.EXPECTED_DEMO_LOGIN, trade_mode=0, equity=1000.0)
    mt5 = _TradeMT5(info, sym=_SymInfo(point=0.01, tick_size=0.01, tick_value=0.01, digits=2),
                    tick=_Tick(64235.73, 64247.73))
    r = dx.place_market_order(mt5, "BTCUSD", "short", atr=50.0,
                              guards=_guards(max_spread_pct=0.5), day_start_equity=1000.0)
    assert r["sent"] and r["side"] == "short"


# ══ Corrections revue Codex 2026-07-13 (P0/P1) ══════════════════════════════

import math as _math
import pytest as _pytest


def _sym_calc(loss):
    """Fabrique un fake mt5 avec order_calc_profit renvoyant `loss` (négatif)."""
    class M(_TradeMT5):
        def order_calc_profit(self, otype, sym, lot, entry, sl): return loss
    return M


def test_invalid_side_refused_no_short_default():
    mt5 = _TradeMT5(_Info(login=dx.EXPECTED_DEMO_LOGIN, trade_mode=0))
    r = dx.place_market_order(mt5, "EURUSD", "peut-être", atr=0.001, guards=_guards())
    assert not r["sent"] and "INVALID_SIDE" in r["reason"]
    assert mt5.sent_request is None


def test_compute_lot_rounds_down_not_up():
    mt5 = _TradeMT5(_Info(login=dx.EXPECTED_DEMO_LOGIN, trade_mode=0),
                    sym=_SymInfo(tick_size=1.0, tick_value=1.0, vmin=0.01, vstep=0.1))
    # dist=10 → money_per_lot=10 ; risk=57 → raw=5.7 → floor au pas 0.1 = 5.7 (ok)
    # risk=54 → raw=5.4 → 5.4 ; risk=55 → 5.5. Vérifie qu'on n'arrondit pas au-dessus.
    assert dx.compute_lot(mt5, "X", 100.0, 90.0, risk_money=59.0) == 5.9
    assert dx.compute_lot(mt5, "X", 100.0, 90.0, risk_money=55.0) == 5.5


def test_lot_min_exceeds_risk_refused():
    mt5 = _TradeMT5(_Info(login=dx.EXPECTED_DEMO_LOGIN, trade_mode=0),
                    sym=_SymInfo(tick_size=1.0, tick_value=1.0, vmin=1.0, vstep=1.0))
    # money_per_lot=10 ; risk=5 → raw=0.5 → floor=0 < vmin=1 → refus
    with _pytest.raises(dx.DemoExecutionRefused) as e:
        dx.compute_lot(mt5, "X", 100.0, 90.0, risk_money=5.0)
    assert "LOT_MIN_EXCEEDS" in str(e.value)


def test_order_calc_profit_over_budget_refused():
    info = _Info(login=dx.EXPECTED_DEMO_LOGIN, trade_mode=0, equity=1000.0)
    Mcls = _sym_calc(loss=-500.0)   # perte réelle 500 >> budget 50 (5%)
    mt5 = Mcls(info, sym=_SymInfo(tick_size=1.0, tick_value=1.0), tick=_Tick(100.0, 100.1))
    r = dx.place_market_order(mt5, "X", "long", atr=5.0, guards=_guards(risk_pct=5.0),
                              day_start_equity=1000.0)
    assert not r["sent"] and "RISK_EXCEEDED" in r["reason"]
    assert mt5.sent_request is None


def test_reassert_demo_before_send_catches_switch():
    # compte démo au préflight puis bascule RÉEL avant l'envoi
    class Switcher(_TradeMT5):
        def __init__(self, *a, **k):
            super().__init__(*a, **k); self._n = 0
        def account_info(self):
            self._n += 1
            demo = _Info(login=dx.EXPECTED_DEMO_LOGIN, trade_mode=0, equity=1000.0)
            real = _Info(login=dx.REAL_ACCOUNT_LOGIN, trade_mode=0, equity=1000.0)
            return demo if self._n <= 1 else real   # préflight=démo, re-assert=réel
    mt5 = Switcher(_Info(login=dx.EXPECTED_DEMO_LOGIN, trade_mode=0, equity=1000.0),
                   sym=_SymInfo(tick_size=1.0, tick_value=1.0), tick=_Tick(100.0, 100.1))
    r = dx.place_market_order(mt5, "X", "long", atr=5.0, guards=_guards(risk_pct=5.0),
                              day_start_equity=1000.0)
    assert not r["sent"] and "RACE_ACCOUNT_CHANGED" in r["reason"]
    assert mt5.sent_request is None


def test_order_check_rejection_blocks_send():
    class Rej(_TradeMT5):
        def order_check(self, req):
            class C: retcode = 10019; comment = "No money"
            return C()
    mt5 = Rej(_Info(login=dx.EXPECTED_DEMO_LOGIN, trade_mode=0, equity=1000.0),
              sym=_SymInfo(tick_size=1.0, tick_value=1.0), tick=_Tick(100.0, 100.1))
    r = dx.place_market_order(mt5, "X", "long", atr=5.0, guards=_guards(risk_pct=5.0),
                              day_start_equity=1000.0)
    assert not r["sent"] and "ORDER_CHECK_REJECTED" in r["reason"]
    assert mt5.sent_request is None


def test_filling_mode_retry_on_10030():
    """Régression bug nuit 28/07 : les futures `.fs` rejettent IOC (retcode 10030
    « Unsupported filling mode »). L'exécuteur doit basculer sur un mode SUPPORTÉ
    (FOK) et envoyer l'ordre — au lieu de perdre l'entrée."""
    class _FS(_TradeMT5):
        ORDER_FILLING_FOK = 0
        ORDER_FILLING_IOC = 1
        ORDER_FILLING_RETURN = 2

        def order_check(self, req):
            rc = 10030 if req.get("type_filling") == self.ORDER_FILLING_IOC else 0
            class _C:
                retcode = rc
                comment = "Unsupported filling mode" if rc == 10030 else ""
            return _C()
    info = _Info(login=dx.EXPECTED_DEMO_LOGIN, trade_mode=0, equity=1000.0)
    mt5 = _FS(info, sym=_SymInfo(tick_size=1.0, tick_value=1.0), tick=_Tick(100.0, 100.1))
    r = dx.place_market_order(mt5, "SPI200.fs", "long", atr=5.0,
                              guards=_guards(risk_pct=5.0), day_start_equity=1000.0)
    assert r["sent"]                                       # l'ordre part malgré le 10030
    assert mt5.sent_request["type_filling"] == _FS.ORDER_FILLING_FOK   # mode supporté retenu


def test_day_ref_rollover_and_corruption(tmp_path):
    p = tmp_path / "day_ref.json"
    # 1er appel : initialise
    assert dx.establish_day_ref(1000.0, path=p, today="2026-07-13") == 1000.0
    # même jour : retourne la réf, pas l'equity courante
    assert dx.establish_day_ref(950.0, path=p, today="2026-07-13") == 1000.0
    # rollover : nouveau jour → nouvelle réf
    assert dx.establish_day_ref(950.0, path=p, today="2026-07-14") == 950.0
    # corruption → refus fail-closed
    p.write_text("{cassé", encoding="utf-8")
    with _pytest.raises(dx.DemoExecutionRefused) as e:
        dx.establish_day_ref(950.0, path=p, today="2026-07-14")
    assert "DAYREF_CORRUPT" in str(e.value)


def test_kill_switch_active_via_place_order():
    # equity 900 vs réf 1000 = -10% ≥ kill 5% → refus AVANT tout order_send
    info = _Info(login=dx.EXPECTED_DEMO_LOGIN, trade_mode=0, equity=900.0)
    mt5 = _TradeMT5(info, sym=_SymInfo(tick_size=1.0, tick_value=1.0), tick=_Tick(100.0, 100.1))
    r = dx.place_market_order(mt5, "X", "long", atr=5.0,
                              guards=_guards(risk_pct=5.0, daily_loss_limit_pct=5.0),
                              day_start_equity=1000.0)
    assert not r["sent"] and "KILL_SWITCH" in r["reason"]
    assert mt5.sent_request is None


# ══ rev.3 — CRITICAL revue Codex : fail-closed calc_profit / order_check / race ══

def _mk(**kw):
    """fake démo prêt à envoyer, surchargé par kw (order_calc_profit/order_check)."""
    info = _Info(login=dx.EXPECTED_DEMO_LOGIN, trade_mode=0, equity=1000.0)
    base = _TradeMT5(info, sym=_SymInfo(tick_size=1.0, tick_value=1.0), tick=_Tick(100.0, 100.1))
    for k, v in kw.items():
        setattr(base, k, v)
    return base


def _order(mt5):
    return dx.place_market_order(mt5, "X", "long", atr=5.0,
                                 guards=_guards(risk_pct=5.0), day_start_equity=1000.0)


def test_calc_profit_absent_refused():
    mt5 = _mk(order_calc_profit=None)   # attr d'instance None masque la méthode
    r = _order(mt5)
    assert not r["sent"] and "RISK_CALC_UNAVAILABLE" in r["reason"]
    assert mt5.sent_request is None


def test_calc_profit_raises_refused():
    def boom(*a): raise RuntimeError("x")
    mt5 = _mk(order_calc_profit=boom)
    r = _order(mt5)
    assert not r["sent"] and "RISK_CALC_ERROR" in r["reason"]
    assert mt5.sent_request is None


def test_calc_profit_none_refused():
    mt5 = _mk(order_calc_profit=lambda *a: None)
    r = _order(mt5)
    assert not r["sent"] and "RISK_CALC_NONE" in r["reason"]
    assert mt5.sent_request is None


def test_calc_profit_nan_refused():
    mt5 = _mk(order_calc_profit=lambda *a: float("nan"))
    r = _order(mt5)
    assert not r["sent"] and "RISK_CALC_NONFINITE" in r["reason"]
    assert mt5.sent_request is None


def test_order_check_absent_refused():
    mt5 = _mk(order_check=None)   # attr d'instance None masque la méthode
    r = _order(mt5)
    assert not r["sent"] and "ORDER_CHECK_UNAVAILABLE" in r["reason"]
    assert mt5.sent_request is None


def test_order_check_raises_refused():
    def boom(req): raise RuntimeError("x")
    mt5 = _mk(order_check=boom)
    r = _order(mt5)
    assert not r["sent"] and "ORDER_CHECK_ERROR" in r["reason"]
    assert mt5.sent_request is None


def test_order_check_none_refused():
    mt5 = _mk(order_check=lambda req: None)
    r = _order(mt5)
    assert not r["sent"] and "ORDER_CHECK_NONE" in r["reason"]
    assert mt5.sent_request is None


def test_switch_to_real_during_order_check_blocked():
    # démo au préflight, puis bascule RÉEL détectée par le re-assert APRÈS order_check
    info = _Info(login=dx.EXPECTED_DEMO_LOGIN, trade_mode=0, equity=1000.0)
    mt5 = _TradeMT5(info, sym=_SymInfo(tick_size=1.0, tick_value=1.0), tick=_Tick(100.0, 100.1))
    state = {"n": 0}
    def acct():
        state["n"] += 1
        demo = _Info(login=dx.EXPECTED_DEMO_LOGIN, trade_mode=0, equity=1000.0)
        real = _Info(login=dx.REAL_ACCOUNT_LOGIN, trade_mode=0, equity=1000.0)
        return demo if state["n"] <= 1 else real   # 1=préflight démo, 2=re-assert final réel
    mt5.account_info = acct
    r = _order(mt5)
    assert not r["sent"] and "RACE_ACCOUNT_CHANGED" in r["reason"]
    assert mt5.sent_request is None


def test_config_non_finite_refused():
    mt5 = _mk()
    r = dx.place_market_order(mt5, "X", "long", atr=5.0,
                              guards=_guards(risk_pct=float("nan")), day_start_equity=1000.0)
    assert not r["sent"] and "CONFIG_INVALID" in r["reason"]
    assert mt5.sent_request is None


# ══ Constat 29/07 : le stop ne doit JAMAIS être atteignable par le seul spread ══

def test_stop_jamais_dans_le_spread():
    """Régression majeure (enregistreur d'excursions, 20/20 trades) : le spread valait
    57 % à 650 % du risque total. Un stop de short se déclenche sur l'ASK → le spread
    allait chercher le stop SEUL, sans mouvement de prix (AUDNZD : MAE −0.00R, clôturé
    à −1R). Le SL doit rester à bonne distance du spread."""
    info = _Info(login=dx.EXPECTED_DEMO_LOGIN, trade_mode=0, equity=1000.0)
    # spread ÉNORME (2.0) face à un ATR minuscule (0.1) → le SL naïf serait dans le spread
    mt5 = _TradeMT5(info, sym=_SymInfo(point=0.01, tick_size=0.01, tick_value=1.0, digits=2),
                    tick=_Tick(bid=99.0, ask=101.0))
    # plafond de SANITÉ relevé : on teste un spread volontairement extrême
    r = dx.place_market_order(mt5, "CHFSEK", "short", atr=0.1, sl_atr_mult=1.5,
                              tp_atr_mult=2.25,
                              guards=_guards(risk_pct=5.0, max_spread_pct=5.0),
                              day_start_equity=1000.0)
    assert r["sent"], r.get("reason")
    spread = 101.0 - 99.0
    risque = abs(r["price"] - r["sl"])
    assert risque >= 3.5 * spread, (
        f"stop à {risque:.2f} pour un spread de {spread:.2f} — le spread le déclencherait seul")


def test_elargir_le_stop_preserve_le_ratio_RR():
    """Élargir le SL sans toucher au TP écraserait le R:R et rendrait la cible
    inatteignable en proportion du risque. La géométrie doit être conservée."""
    info = _Info(login=dx.EXPECTED_DEMO_LOGIN, trade_mode=0, equity=1000.0)
    mt5 = _TradeMT5(info, sym=_SymInfo(point=0.01, tick_size=0.01, tick_value=1.0, digits=2),
                    tick=_Tick(bid=99.0, ask=101.0))
    r = dx.place_market_order(mt5, "CHFSEK", "long", atr=0.1, sl_atr_mult=1.5,
                              tp_atr_mult=3.0,
                              guards=_guards(risk_pct=5.0, max_spread_pct=5.0),
                              day_start_equity=1000.0)
    assert r["sent"]
    rr = abs(r["tp"] - r["price"]) / abs(r["price"] - r["sl"])
    assert 1.8 <= rr <= 2.2, f"R:R visé 2.0 (3.0/1.5), obtenu {rr:.2f}"
