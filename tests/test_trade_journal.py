"""tests/test_trade_journal.py — Tests du journal "Trading-as-Git" (Phase J).

Vérifie l'immutabilité (append-only — le fichier n'est jamais tronqué/réécrit) et la
reconstruction correcte du statut courant de chaque trade en rejouant le journal.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch

from execution import trade_journal as tj


def _journal_at(tmp_path):
    journal_file = tmp_path / "journal.jsonl"
    patcher = patch.object(tj, "TRADE_JOURNAL_FILE", journal_file)
    patcher.start()
    tj._pending_signals.clear()
    return journal_file, patcher


def test_stage_then_commit_reconstructs_as_filled(tmp_path):
    jf, patcher = _journal_at(tmp_path)
    try:
        h = tj.stage({"symbol": "BTC/USDT", "side": "ACHAT", "score": 9, "score_max": 16, "confs": []})
        tj.commit(h, {"entry_price": 100.0})
        trades = tj.get_journal()
        assert len(trades) == 1
        assert trades[0]["hash"] == h
        assert trades[0]["status"] == "filled"
        assert trades[0]["position"] == {"entry_price": 100.0}
    finally:
        patcher.stop()


def test_stage_then_reject_reconstructs_as_rejected(tmp_path):
    jf, patcher = _journal_at(tmp_path)
    try:
        h = tj.stage({"symbol": "BTC/USDT", "side": "ACHAT"})
        tj.reject(h, "stop_loss_required: sans SL")
        trades = tj.get_journal()
        assert trades[0]["status"] == "rejected"
        assert "stop_loss_required" in trades[0]["reason"]
    finally:
        patcher.stop()


def test_journal_file_is_append_only(tmp_path):
    """Le fichier ne fait que grandir — jamais de réécriture du contenu déjà présent."""
    jf, patcher = _journal_at(tmp_path)
    try:
        h1 = tj.stage({"symbol": "BTC/USDT", "side": "ACHAT"})
        tj.commit(h1, {"entry_price": 100.0})
        content_after_first = jf.read_text(encoding="utf-8")

        h2 = tj.stage({"symbol": "PAXG/USDT", "side": "VENTE"})
        tj.reject(h2, "test")
        content_after_second = jf.read_text(encoding="utf-8")

        assert content_after_second.startswith(content_after_first)
        assert len(content_after_second) > len(content_after_first)
    finally:
        patcher.stop()


def test_get_journal_returns_most_recent_first(tmp_path):
    jf, patcher = _journal_at(tmp_path)
    try:
        h1 = tj.stage({"symbol": "BTC/USDT", "side": "ACHAT"})
        tj.commit(h1, {"entry_price": 100.0})
        h2 = tj.stage({"symbol": "PAXG/USDT", "side": "VENTE"})
        tj.commit(h2, {"entry_price": 2000.0})

        trades = tj.get_journal()
        assert trades[0]["hash"] == h2
        assert trades[1]["hash"] == h1
    finally:
        patcher.stop()


def test_staging_enabled_keeps_signal_pending_until_approved(tmp_path):
    jf, patcher = _journal_at(tmp_path)
    try:
        with patch.object(tj, "JOURNAL_STAGING_ENABLED", True):
            signal = {"symbol": "BTC/USDT", "side": "ACHAT"}
            h = tj.stage(signal)
            assert tj.pop_pending(h) == signal
            assert tj.pop_pending(h) is None  # retiré une seule fois
    finally:
        patcher.stop()
