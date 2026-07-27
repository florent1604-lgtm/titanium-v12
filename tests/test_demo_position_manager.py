"""Gestion dynamique des positions démo : breakeven + trailing, sans jamais élargir le risque."""
import types
import pytest

from execution import demo_position_manager as pm


class _Pos:
    def __init__(self, ticket, type_, entry, cur, sl, tp, symbol="EURUSD",
                 magic=pm.MAGIC, comment="titanium-conf|p3"):
        self.ticket = ticket; self.type = type_; self.price_open = entry
        self.price_current = cur; self.sl = sl; self.tp = tp; self.symbol = symbol
        self.magic = magic; self.comment = comment


class _FakeMT5:
    TRADE_ACTION_SLTP = 6
    TRADE_RETCODE_DONE = 10009
    ACCOUNT_TRADE_MODE_DEMO = 0

    def __init__(self, positions, login=50061786):
        self._pos = positions
        self._login = login
        self.sent = []

    # compte démo attendu (assert_demo_or_raise)
    def account_info(self):
        return types.SimpleNamespace(login=self._login, server="Axi-US50-Demo",
                                     currency="USD", balance=1000.0, equity=1000.0,
                                     margin_free=900.0, trade_mode=0)

    def positions_get(self, symbol=None):
        return list(self._pos)

    def symbol_info(self, s):
        return types.SimpleNamespace(point=0.0001, trade_stops_level=0, digits=5)

    def symbol_info_tick(self, s):
        return types.SimpleNamespace(bid=1.1000, ask=1.1001)

    def order_send(self, req):
        self.sent.append(req)
        return types.SimpleNamespace(retcode=self.TRADE_RETCODE_DONE, comment="ok")


@pytest.fixture(autouse=True)
def _demo_login(monkeypatch, tmp_path):
    # login démo attendu + état isolé (pas d'écriture dans le vrai data/)
    monkeypatch.setattr(pm.dx, "EXPECTED_DEMO_LOGIN", 50061786, raising=False)
    monkeypatch.setattr(pm.dx, "REAL_ACCOUNT_LOGIN", 60261188, raising=False)
    monkeypatch.setattr(pm, "STATE_PATH", tmp_path / "state.json")


def test_breakeven_deplace_le_sl_a_l_entree_long():
    # long entré 1.1000, SL 1.0980 (R=0.0020), prix +1.0R (1.1020) → SL remonte ~à l'entrée
    pos = _Pos(1, 0, entry=1.1000, cur=1.1020, sl=1.0980, tp=1.1060)
    mt5 = _FakeMT5([pos])
    rep = pm.manage_once(mt5, breakeven_r=0.8, trail_start_r=1.2, trail_dist_r=0.8)
    assert rep["moved"] == 1
    new_sl = mt5.sent[-1]["sl"]
    assert new_sl >= 1.1000          # au moins à l'entrée (breakeven), sens favorable


def test_pas_de_breakeven_avant_le_seuil():
    # +0.5R seulement → pas encore de breakeven
    pos = _Pos(1, 0, entry=1.1000, cur=1.1010, sl=1.0980, tp=1.1060)
    mt5 = _FakeMT5([pos])
    rep = pm.manage_once(mt5, breakeven_r=0.8, trail_start_r=1.2, trail_dist_r=0.8)
    assert rep["moved"] == 0 and mt5.sent == []


def test_jamais_elargir_le_risque_short():
    # short entré 1.1000, SL 1.1020 (R=0.0020). Un SL candidat plus HAUT (élargir) est refusé.
    # Ici prix +1.5R (1.0970) → trailing calcule un SL plus bas (favorable) : autorisé.
    pos = _Pos(1, 1, entry=1.1000, cur=1.0970, sl=1.1020, tp=1.0940)
    mt5 = _FakeMT5([pos])
    rep = pm.manage_once(mt5, breakeven_r=0.8, trail_start_r=1.2, trail_dist_r=0.8)
    assert rep["moved"] == 1
    assert mt5.sent[-1]["sl"] < 1.1020        # SL resserré vers le bas (short favorable)


def test_refus_hors_compte_demo():
    pos = _Pos(1, 0, entry=1.1000, cur=1.1016, sl=1.0980, tp=1.1060)
    mt5 = _FakeMT5([pos], login=60261188)     # login RÉEL → refus absolu
    rep = pm.manage_once(mt5, breakeven_r=0.8, trail_start_r=1.2, trail_dist_r=0.8)
    assert rep["moved"] == 0 and "NOT_DEMO" in rep.get("reason", "")


def test_ignore_positions_etrangeres():
    pos = _Pos(1, 0, entry=1.1000, cur=1.1016, sl=1.0980, tp=1.1060,
               magic=999, comment="autre-bot")
    mt5 = _FakeMT5([pos])
    rep = pm.manage_once(mt5, breakeven_r=0.8, trail_start_r=1.2, trail_dist_r=0.8)
    assert rep["managed"] == 0 and rep["moved"] == 0
