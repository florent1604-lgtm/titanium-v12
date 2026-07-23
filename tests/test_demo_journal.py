"""Journal démo : chaque tentative écrite (envoyée ET refusée), émotion observée
sans influence, et JAMAIS fatal pour l'ordre."""
import json

from execution import demo_journal as dj


def _isolate(tmp_path, monkeypatch):
    p = tmp_path / "demo_journal.ndjson"
    monkeypatch.setattr(dj, "JOURNAL", p)
    return p


def test_records_sent_order(tmp_path, monkeypatch):
    p = _isolate(tmp_path, monkeypatch)
    dj.record("USTECH", "buy", {"sent": True, "lot": 0.24, "price": 29736.0,
                                "sl": 29100.0, "ticket": 12345, "risk_money": 66.5,
                                "account": {"equity": 950.08, "login": 50061786}},
              atr=253.3, engine="swing", with_emotion=False)
    row = json.loads(p.read_text(encoding="utf-8").strip())
    assert row["sent"] is True and row["symbol"] == "USTECH" and row["engine"] == "swing"
    assert row["lot"] == 0.24 and row["ticket"] == 12345 and row["equity"] == 950.08


def test_records_refusal_with_reason(tmp_path, monkeypatch):
    """« 0 trade » n'est pas une information ; « refusé car X » en est une."""
    p = _isolate(tmp_path, monkeypatch)
    dj.record("EURUSD", "sell", {"sent": False, "reason": "RISK_LOW_MARGIN: marge < 20%."},
              engine="forex", with_emotion=False)
    row = json.loads(p.read_text(encoding="utf-8").strip())
    assert row["sent"] is False and row["reason"].startswith("RISK_LOW_MARGIN")


def test_summary_explains_why_no_trade(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    for _ in range(3):
        dj.record("USTECH", "buy", {"sent": False, "reason": "ALREADY_OPEN"}, with_emotion=False)
    dj.record("HSI.fs", "buy", {"sent": False, "reason": "MAX_POSITIONS"}, with_emotion=False)
    dj.record("NAS100.fs", "buy", {"sent": True, "lot": 0.1}, with_emotion=False)
    s = dj.summary()
    assert s["attempts"] == 5 and s["sent"] == 1 and s["refused"] == 4
    assert s["refused_by_reason"]["ALREADY_OPEN"] == 3
    assert s["refused_by_reason"]["MAX_POSITIONS"] == 1


def test_emotion_is_observed_not_applied(tmp_path, monkeypatch):
    """L'émotion est enregistrée comme observation appariée — jamais appliquée."""
    p = _isolate(tmp_path, monkeypatch)
    import emotion.market_context as mc
    from emotion.emotion_engine import EmotionState
    monkeypatch.setattr(mc, "emotion_for", lambda sym, **k: EmotionState(
        True, 90.0, 80.0, 0.3, "EUPHORIE", 0.8, False, "short", "long", {"delta_volume": 0.9}, []))
    dj.record("USTECH", "buy", {"sent": True, "lot": 0.2}, engine="swing")
    row = json.loads(p.read_text(encoding="utf-8").strip())
    emo = row["emotion_observed"]
    assert emo["label"] == "EUPHORIE" and emo["would_block"] == "long"
    # L'ordre est parti MALGRÉ un « would_block: long » → l'émotion n'a rien décidé.
    assert row["sent"] is True


def test_journaling_never_breaks_the_order(tmp_path, monkeypatch):
    """Si l'émotion ou le disque casse, record() ne remonte JAMAIS d'exception."""
    _isolate(tmp_path, monkeypatch)
    import emotion.market_context as mc
    monkeypatch.setattr(mc, "emotion_for", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    dj.record("USTECH", "buy", {"sent": True})          # émotion cassée → pas d'exception
    monkeypatch.setattr(dj, "JOURNAL", tmp_path / "nope" / "x" / "\0bad.ndjson")
    dj.record("USTECH", "buy", {"sent": True})          # disque cassé → pas d'exception non plus


def test_corrupt_line_is_ignored(tmp_path, monkeypatch):
    p = _isolate(tmp_path, monkeypatch)
    p.write_text('{"ts_utc":"x","sent":true}\nPAS DU JSON\n\n', encoding="utf-8")
    assert len(dj.read_all()) == 1
