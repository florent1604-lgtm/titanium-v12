"""Tests du Lot C (M2-1) — observateur SHADOW signal <-> gate.

Vérifie : le mapping des sens, la classification de divergence, le fail-safe
absolu (aucune exception ne remonte), l'écriture NDJSON contrefactuelle et le
dépouillement. Aucun état de trading n'est touché ; ``gate_entry`` est simulé.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import core.shadow_divergence as sd


def _fake_gate(allow, side=0, conviction=0.0, reasons=("BRAIN_ALLOW",)):
    return SimpleNamespace(allow=allow, side=side, conviction=conviction,
                           reason_codes=reasons)


def test_proposed_side_mapping():
    assert sd._proposed_side("ACHAT") == 1
    assert sd._proposed_side("vente") == -1
    assert sd._proposed_side("LONG") == 1
    assert sd._proposed_side(-4) == -1
    assert sd._proposed_side(0) == 0
    assert sd._proposed_side("n'importe quoi") == 0


def test_classify_labels():
    assert sd._classify(True, 1, False, 0) == "EMIT_BUT_BRAIN_BLOCK"
    assert sd._classify(True, 1, True, -1) == "EMIT_BUT_BRAIN_OPPOSITE"
    assert sd._classify(False, 1, True, 1) == "NOEMIT_BUT_BRAIN_ALLOW"
    assert sd._classify(True, 1, True, 1) == "AGREE_ALLOW"
    assert sd._classify(False, 1, False, 0) == "AGREE_BLOCK"


def test_observe_non_directional_is_noop(tmp_path, monkeypatch):
    """Sens non directionnel -> None, aucun appel gate_entry, aucune écriture."""
    journal = tmp_path / "shadow.ndjson"
    monkeypatch.setattr(sd, "_JOURNAL", str(journal))

    def _boom(*a, **k):  # gate_entry ne DOIT pas être appelé
        raise AssertionError("gate_entry appelé pour un sens neutre")

    monkeypatch.setattr("core.brain_gate.gate_entry", _boom, raising=False)
    assert sd.observe("BTCUSDT", "FLAT", 0, emitted=False) is None
    assert not journal.exists()


def test_observe_writes_divergence(tmp_path, monkeypatch):
    """Un signal émis alors que le cerveau bloquerait -> EMIT_BUT_BRAIN_BLOCK journalisé."""
    journal = tmp_path / "shadow.ndjson"
    monkeypatch.setattr(sd, "_JOURNAL", str(journal))
    monkeypatch.setattr("core.brain_gate.gate_entry",
                        lambda sym, side: _fake_gate(False, 0, 0.0, ("BRAIN_NO_COVERAGE",)),
                        raising=False)

    label = sd.observe("BTCUSDT", "ACHAT", 7, emitted=True, score_min=5)
    assert label == "EMIT_BUT_BRAIN_BLOCK"

    rows = [json.loads(l) for l in journal.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(rows) == 1
    rec = rows[0]
    assert rec["symbol"] == "BTCUSDT" and rec["proposed"] == 1
    assert rec["emitted"] is True and rec["brain_allow"] is False
    assert rec["divergence"] == "EMIT_BUT_BRAIN_BLOCK"
    assert rec["reason_codes"] == ["BRAIN_NO_COVERAGE"]


def test_observe_is_failsafe_on_gate_error(tmp_path, monkeypatch):
    """Si gate_entry explose, observe NE LÈVE PAS et retourne None."""
    journal = tmp_path / "shadow.ndjson"
    monkeypatch.setattr(sd, "_JOURNAL", str(journal))

    def _explode(sym, side):
        raise RuntimeError("cerveau illisible")

    monkeypatch.setattr("core.brain_gate.gate_entry", _explode, raising=False)
    # Ne doit pas lever malgré l'erreur interne.
    assert sd.observe("ETHUSDT", "VENTE", 6, emitted=True) is None


def test_divergence_summary_counts(tmp_path, monkeypatch):
    journal = tmp_path / "shadow.ndjson"
    monkeypatch.setattr(sd, "_JOURNAL", str(journal))
    monkeypatch.setattr("core.brain_gate.gate_entry",
                        lambda sym, side: _fake_gate(False, 0, 0.0, ("BRAIN_NO_COVERAGE",)),
                        raising=False)
    for _ in range(3):
        sd.observe("BTCUSDT", "ACHAT", 7, emitted=True)      # EMIT_BUT_BRAIN_BLOCK
    monkeypatch.setattr("core.brain_gate.gate_entry",
                        lambda sym, side: _fake_gate(True, 1, 0.8), raising=False)
    sd.observe("BTCUSDT", "ACHAT", 7, emitted=True)          # AGREE_ALLOW

    summary = sd.divergence_summary(str(journal))
    assert summary["total"] == 4
    assert summary["counts"]["EMIT_BUT_BRAIN_BLOCK"] == 3
    assert summary["counts"]["AGREE_ALLOW"] == 1
    assert summary["disagreement_rate"] == 0.75
