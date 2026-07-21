"""Tests d'acceptation CommandGateway C1 SHADOW — noyau pur (sans transport pipe/EventPlane).

Couvre le sous-ensemble applicable des tests C1 de la spec (section 9) :
4 durabilité, 5 idempotence, 6 déterminisme, 7 default-deny, 8 mur compte réel, 9 handlers
vides, 10 ALLOW→no-dispatch, 11 authorizations/outcomes vides, 13 panne store, 15 refus
d'état incohérent, 17 absence structurelle de sinks d'exécution.
"""
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from gateway import capability_registry as reg
from gateway import policy_kernel as policy
from gateway.command_gateway import CommandGateway
from gateway.contracts import (
    AttestedPrincipal, AttestedProposal, Proposal, TrustedState,
    R_APPROVAL_MISSING, R_CLOCK_INCOHERENT, R_EVENTPLANE_INTEGRITY_BROKEN, R_KILL_SWITCH_ACTIVE,
    R_MODE_NOT_ALLOWED, R_PROJECTION_STALE, R_REAL_ACCOUNT_ORDER_FORBIDDEN, R_SHADOW_NO_DISPATCH,
    R_STORE_UNAVAILABLE, R_TTL_EXPIRED, R_UNKNOWN_CAPABILITY, S_SHADOW_RECORDED,
    S_STORE_UNAVAILABLE, VERDICT_ALLOW, VERDICT_DENY,
)
from gateway.efferent_journal import EfferentJournal, IdempotencyConflict

_PRINCIPAL = AttestedPrincipal(sid="S-1-5-21-hermes", kind="HERMES_SERVICE")


def _now():
    return datetime(2026, 7, 20, 8, 0, 0, tzinfo=timezone.utc)


def _state(**over):
    base = dict(now=_now().isoformat(), account_mode="PAPER", account_is_real=False,
                kill_switch_active=False, eventplane_integrity_ok=True, projection_stale=False,
                projection_as_of=_now().isoformat())
    base.update(over)
    return TrustedState(**base)


def _proposal(**over):
    base = dict(
        request_id="req-1", capability_id="paper.position.open_intent", capability_version=1,
        requested_mode="PAPER", params={"instrument_id": "BTCUSD", "side": "long", "notional_pct": 1.0},
        idempotency_key="idem-1", created_at=(_now() - timedelta(seconds=5)).isoformat(),
        expires_at=(_now() + timedelta(seconds=25)).isoformat(),
        m2_proof="m2:ok", approval="appr:ok")
    base.update(over)
    return base


def _gw(tmp_path):
    return CommandGateway(EfferentJournal(db_path=tmp_path / "gw.sqlite3"))


# --- 10 : même ALLOW logique -> dispatch_permitted False + shadow -------------------------
def test_c1_allow_reste_shadow_sans_dispatch(tmp_path):
    r = _gw(tmp_path).submit(_proposal(), _PRINCIPAL, _state())
    assert r.status == S_SHADOW_RECORDED and r.verdict == VERDICT_ALLOW
    assert r.dispatch_permitted is False and r.reason_codes == (R_SHADOW_NO_DISPATCH,)
    assert r.proposal_id and r.decision_id


# --- 4 : proposition durable après réouverture du store avant reply -----------------------
def test_c1_proposition_durable_apres_reouverture(tmp_path):
    db = tmp_path / "gw.sqlite3"
    CommandGateway(EfferentJournal(db_path=db)).submit(_proposal(), _PRINCIPAL, _state())
    reopened = EfferentJournal(db_path=db)                       # nouveau handle, même fichier
    assert reopened.health()["n_proposals"] == 1
    assert reopened.health()["n_decisions"] == 1


# --- 5 : rejeu exact = mêmes IDs ; rejeu divergent = conflit ------------------------------
def test_c1_rejeu_exact_memes_ids(tmp_path):
    gw = _gw(tmp_path)
    r1 = gw.submit(_proposal(), _PRINCIPAL, _state())
    r2 = gw.submit(_proposal(request_id="req-2"), _PRINCIPAL, _state())   # même idem-key + contenu
    assert (r2.proposal_id, r2.decision_id) == (r1.proposal_id, r1.decision_id)


def test_c1_rejeu_divergent_conflit(tmp_path):
    gw = _gw(tmp_path)
    gw.submit(_proposal(), _PRINCIPAL, _state())
    divergent = _proposal(params={"instrument_id": "ETHUSD", "side": "short", "notional_pct": 2.0})
    r = gw.submit(divergent, _PRINCIPAL, _state())               # même idem-key, contenu différent
    assert r.status == "IDEMPOTENCY_CONFLICT" and r.proposal_id is None


# --- 6 : PolicyKernel déterministe + la justification n'influence pas le verdict ----------
def test_c1_policy_deterministe_justification_ignoree(tmp_path):
    att_a = AttestedProposal(Proposal.parse(_proposal(justification="raison A")), _PRINCIPAL, _now().isoformat())
    att_b = AttestedProposal(Proposal.parse(_proposal(justification="raison Z totalement autre")), _PRINCIPAL, _now().isoformat())
    da, db = policy.evaluate(att_a, _state()), policy.evaluate(att_b, _state())
    assert da == db and da.verdict == VERDICT_ALLOW


# --- 7 : capacité/mode/preuve inconnus -> default-deny ------------------------------------
@pytest.mark.parametrize("mut,expect", [
    (dict(capability_id="does.not.exist"), R_UNKNOWN_CAPABILITY),
    (dict(capability_version=999), R_UNKNOWN_CAPABILITY),
    (dict(requested_mode="DEMO"), R_MODE_NOT_ALLOWED),          # PAPER-only cap
    (dict(m2_proof=None), "M2_PROOF_MISSING"),
    (dict(approval=None), R_APPROVAL_MISSING),
    (dict(params={"instrument_id": "BTCUSD", "side": "long"}), "PARAM_SCHEMA_VIOLATION"),
])
def test_c1_default_deny(tmp_path, mut, expect):
    r = _gw(tmp_path).submit(_proposal(**mut), _PRINCIPAL, _state())
    assert r.verdict == VERDICT_DENY and expect in r.reason_codes and r.dispatch_permitted is False


# --- 8 : compte RÉEL + capacité d'ordre -> interdit --------------------------------------
def test_c1_compte_reel_ordre_interdit(tmp_path):
    prop = _proposal(capability_id="demo.order.place_intent", requested_mode="DEMO",
                     params={"instrument_id": "BTCUSD", "side": "long", "volume": 0.1})
    st = _state(account_mode="DEMO", account_is_real=True)       # compte réel opéré en mode DEMO
    r = _gw(tmp_path).submit(prop, _PRINCIPAL, st)
    assert r.verdict == VERDICT_DENY and R_REAL_ACCOUNT_ORDER_FORBIDDEN in r.reason_codes


# --- 9 : table de handlers vide + résolution interdite -----------------------------------
def test_c1_handlers_vides(tmp_path):
    assert reg.handler_count() == 0
    with pytest.raises(reg.CriticalShadowViolation):
        reg.resolve_handler("paper.position.open")


# --- 11 : authorizations + outcomes vides sous charge ------------------------------------
def test_c1_authorizations_outcomes_vides_sous_charge(tmp_path):
    gw = _gw(tmp_path)
    for i in range(25):
        gw.submit(_proposal(idempotency_key=f"idem-{i}", request_id=f"r-{i}"), _PRINCIPAL, _state())
    h = gw.journal.health()
    assert h["authorization_count"] == 0 and h["outcome_count"] == 0 and h["n_proposals"] == 25
    gw.journal.assert_c1_invariants()                           # ne lève pas


# --- 13 : panne journal avant commit -> STORE_UNAVAILABLE, aucune réponse positive --------
def test_c1_panne_store(tmp_path):
    class _BoomJournal:
        def persist_proposal(self, attested):
            raise RuntimeError("disk full")
    r = CommandGateway(_BoomJournal()).submit(_proposal(), _PRINCIPAL, _state())
    assert r.status == S_STORE_UNAVAILABLE and r.verdict is None
    assert r.dispatch_permitted is False and R_STORE_UNAVAILABLE in r.reason_codes


# --- 15 : horloge incohérente / TTL expiré / projection stale / intégrité cassée ---------
@pytest.mark.parametrize("prop_mut,state_mut,expect", [
    (dict(created_at=(_now() + timedelta(seconds=60)).isoformat()), {}, R_CLOCK_INCOHERENT),
    (dict(expires_at=(_now() - timedelta(seconds=1)).isoformat()), {}, R_TTL_EXPIRED),
    ({}, dict(projection_stale=True), R_PROJECTION_STALE),
    ({}, dict(eventplane_integrity_ok=False), R_EVENTPLANE_INTEGRITY_BROKEN),
    ({}, dict(kill_switch_active=True), R_KILL_SWITCH_ACTIVE),
])
def test_c1_etat_incoherent_refuse(tmp_path, prop_mut, state_mut, expect):
    r = _gw(tmp_path).submit(_proposal(**prop_mut), _PRINCIPAL, _state(**state_mut))
    assert r.verdict == VERDICT_DENY and expect in r.reason_codes


# --- 17 : absence structurelle de sinks d'exécution dans le paquet gateway ----------------
def test_c1_pas_de_sinks_execution():
    forbidden = [
        re.compile(r"order_send"), re.compile(r"\bsubprocess\b"), re.compile(r"os\.system"),
        re.compile(r"__import__"), re.compile(r"\bimportlib\b"),
        re.compile(r"\beval\("), re.compile(r"\bexec\("),        # pas le builtin (execute() OK)
        re.compile(r"\.post\("), re.compile(r"requests\."), re.compile(r"httpx\."),
        re.compile(r"MetaTrader5"), re.compile(r"\bmt5\b"),
    ]
    pkg = Path(reg.__file__).resolve().parent
    for f in pkg.glob("*.py"):
        src = f.read_text(encoding="utf-8")
        for pat in forbidden:
            assert not pat.search(src), f"sink interdit {pat.pattern} dans {f.name}"
