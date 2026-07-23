"""Alertes Telegram du moteur de confluence : gating par piliers, anti-spam,
priorité absolue quand une position démo s'ouvre. Aucun réseau (_tg_post stubé)."""
import asyncio

from notifications import telegram as tg


def _summary(verdict="BLOCK", side=-1, passed=("trend_sr", "fair_value"),
             placed=None, family="continuation"):
    names = ("data_valid", "trend_sr", "fair_value", "liquidity", "ote_ob", "candle_confirmed")
    gates = [{"name": n, "passed": (n == "data_valid" or n in passed), "code": n} for n in names]
    return {"symbol": "EURUSD", "verdict": verdict, "side": side, "setup_family": family,
            "gates": gates, "reasons": ["confluence incomplète"],
            "trace": {"pillars": {"sr": {"on_level_kind": "resistance", "on_level": 1.1446,
                                         "on_level_strength": 1.0},
                                  "candle": {"patterns": ["marubozu"], "direction": -1},
                                  "trend": -1},
                      "setup": {"trend_context": -1}},
            "placed": placed}


def _arm(monkeypatch, min_pillars=4, interval=900):
    monkeypatch.setattr(tg, "TELEGRAM_CONFLUENCE_ENABLED", True)
    monkeypatch.setattr(tg, "TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setattr(tg, "TELEGRAM_CHAT_IDS", ["1"])
    monkeypatch.setattr(tg, "TELEGRAM_CONFLUENCE_MIN_PILLARS", min_pillars)
    monkeypatch.setattr(tg, "TELEGRAM_CONFLUENCE_INTERVAL", interval)
    sent = []
    async def fake_post(text):
        sent.append(text)
    monkeypatch.setattr(tg, "_tg_post", fake_post)
    tg._conf_last_sent.clear()
    return sent


def test_pas_dalerte_sous_le_seuil(monkeypatch):
    sent = _arm(monkeypatch, min_pillars=4)
    ok = asyncio.run(tg.send_confluence_alert("EURUSD", _summary(passed=("trend_sr", "fair_value"))))
    assert ok is False and sent == []


def test_alerte_setup_en_formation(monkeypatch):
    sent = _arm(monkeypatch, min_pillars=4)
    ok = asyncio.run(tg.send_confluence_alert(
        "EURUSD", _summary(passed=("trend_sr", "fair_value", "liquidity", "candle_confirmed"))))
    assert ok is True and "4/5" in sent[0] and "Setup en formation" in sent[0]


def test_position_ouverte_toujours_alerte_et_bypass_antispam(monkeypatch):
    sent = _arm(monkeypatch, min_pillars=5, interval=99999)
    placed = {"sent": True, "side": "short", "lot": 0.1, "price": 1.1446}
    s = _summary(verdict="ENTER",
                 passed=("trend_sr", "fair_value", "liquidity", "ote_ob", "candle_confirmed"),
                 placed=placed)
    ok1 = asyncio.run(tg.send_confluence_alert("EURUSD", s))
    ok2 = asyncio.run(tg.send_confluence_alert("EURUSD", s))   # position → bypass anti-spam
    assert ok1 and ok2 and len(sent) == 2 and "POSITION DÉMO OUVERTE" in sent[0]


def test_antispam_bloque_le_second_setup(monkeypatch):
    sent = _arm(monkeypatch, min_pillars=4, interval=99999)
    s = _summary(passed=("trend_sr", "fair_value", "liquidity", "candle_confirmed"))
    a = asyncio.run(tg.send_confluence_alert("EURUSD", s))
    b = asyncio.run(tg.send_confluence_alert("EURUSD", s))
    assert a is True and b is False and len(sent) == 1


def test_alerte_inclut_le_plan_de_trade(monkeypatch):
    sent = _arm(monkeypatch, min_pillars=4)
    s = _summary(passed=("trend_sr", "fair_value", "liquidity", "candle_confirmed"))
    s["levels"] = {"side": "short", "entry": 1.14460, "sl": 1.14800, "sl_atr": 1.5, "atr": 0.0023,
                   "tps": [{"n": 1, "price": 1.14120, "atr_mult": 1.5, "rr": 1.0},
                           {"n": 2, "price": 1.13890, "atr_mult": 2.5, "rr": 1.67},
                           {"n": 3, "price": 1.13540, "atr_mult": 4.0, "rr": 2.67}]}
    ok = asyncio.run(tg.send_confluence_alert("EURUSD", s))
    assert ok and "Plan de trade" in sent[0]
    assert "Entrée" in sent[0] and "TP1" in sent[0] and "TP3" in sent[0] and "SL" in sent[0]


def test_erreur_et_desactive_non_alertes(monkeypatch):
    sent = _arm(monkeypatch)
    assert asyncio.run(tg.send_confluence_alert("X", {"verdict": "ERROR", "error": "x"})) is False
    monkeypatch.setattr(tg, "TELEGRAM_CONFLUENCE_ENABLED", False)
    assert asyncio.run(tg.send_confluence_alert(
        "EURUSD", _summary(passed=("trend_sr", "fair_value", "liquidity", "ote_ob")))) is False
    assert sent == []
