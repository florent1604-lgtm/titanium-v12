"""gateway/command_gateway.py — orchestrateur CommandGateway C1 SHADOW (process-local).

Enchaîne : parsing d'enveloppe → JOURNALISATION (avant réponse) → PolicyKernel pur → décision
enregistrée → ARRÊT shadow (aucun dispatch) → réponse stricte. Idempotent (rejeu exact = mêmes
IDs). Fail-closed : une panne journal ne produit JAMAIS de réponse positive.

Ce lot est le NOYAU process-local. Le transport named-pipe + attestation SID (l'identité OS
`AttestedPrincipal`) est un lot ultérieur : ici l'appelant fournit le principal attesté et
l'état de confiance. AUCUN dispatch, AUCUN handler, `authorizations` reste vide (invariant).
"""
from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Mapping, Optional, Tuple

from gateway import capability_registry as _reg
from gateway import policy_kernel as _policy
from gateway.contracts import (
    AttestedPrincipal, AttestedProposal, GatewayReply, Proposal, SchemaError, TrustedState,
    POLICY_VERSION, R_IDEMPOTENCY_CONFLICT, R_REJECTED_SCHEMA, R_STORE_UNAVAILABLE,
    S_DEDUPLICATED, S_IDEMPOTENCY_CONFLICT, S_REJECTED_SCHEMA, S_SHADOW_RECORDED,
    S_STORE_UNAVAILABLE,
)
from gateway.efferent_journal import EfferentJournal, IdempotencyConflict


def _state_digest(state: TrustedState) -> str:
    material = {
        "now": state.now, "account_mode": state.account_mode,
        "account_is_real": state.account_is_real, "kill_switch_active": state.kill_switch_active,
        "eventplane_integrity_ok": state.eventplane_integrity_ok,
        "projection_stale": state.projection_stale, "projection_as_of": state.projection_as_of,
    }
    return hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


class CommandGateway:
    def __init__(self, journal: EfferentJournal):
        self.journal = journal

    def _reply(self, request_id: Optional[str], proposal_id, decision_id, status,
               verdict, reason_codes: Tuple[str, ...], recorded_at: str) -> GatewayReply:
        # dispatch_permitted est TOUJOURS False en C1, quel que soit le verdict.
        return GatewayReply(
            request_id=request_id or "unknown", proposal_id=proposal_id, decision_id=decision_id,
            status=status, verdict=verdict, dispatch_permitted=False,
            reason_codes=tuple(reason_codes), policy_version=POLICY_VERSION,
            registry_digest=_reg.registry_digest(), recorded_at=recorded_at,
            correlation_id=uuid.uuid4().hex)

    def submit(self, raw: Mapping[str, Any], principal: AttestedPrincipal,
               state: TrustedState) -> GatewayReply:
        """Traite une proposition NON FIABLE. `principal` = identité OS attestée (fournie par le
        transport dans un lot ultérieur). `state` = projection de confiance lue par le kernel."""
        req_id = raw.get("request_id") if isinstance(raw, Mapping) else None

        # 1. Enveloppe : clés connues, requises, types, taille. Échec → rejet SANS persistance.
        try:
            proposal: Proposal = Proposal.parse(raw)
        except SchemaError:
            return self._reply(req_id, None, None, S_REJECTED_SCHEMA, None,
                               (R_REJECTED_SCHEMA,), state.now)

        attested = AttestedProposal(proposal=proposal, principal=principal, received_at=state.now)

        # 2. JOURNALISER AVANT DE RÉPONDRE (dedup idempotent). Panne = STORE_UNAVAILABLE.
        try:
            proposal_id, duplicate = self.journal.persist_proposal(attested)
        except IdempotencyConflict:
            return self._reply(proposal.request_id, None, None, S_IDEMPOTENCY_CONFLICT, None,
                               (R_IDEMPOTENCY_CONFLICT,), state.now)
        except Exception:
            return self._reply(proposal.request_id, None, None, S_STORE_UNAVAILABLE, None,
                               (R_STORE_UNAVAILABLE,), state.now)

        # 3. Rejeu exact : renvoyer la décision déjà enregistrée (mêmes IDs, même reply).
        if duplicate:
            prev = self.journal.load_decision(proposal_id)
            if prev is not None:
                return self._reply(proposal.request_id, proposal_id, prev["decision_id"],
                                   S_DEDUPLICATED, prev["verdict"], prev["reason_codes"], state.now)

        # 4. PolicyKernel PUR (aucune I/O). Le verdict ne dépend jamais de la justification.
        decision = _policy.evaluate(attested, state)

        # 5. Enregistrer la décision. Panne = STORE_UNAVAILABLE (pas de réponse positive).
        try:
            decision_id = self.journal.record_decision(
                proposal_id, decision, registry_digest=_reg.registry_digest(),
                state_digest=_state_digest(state))
        except Exception:
            return self._reply(proposal.request_id, proposal_id, None, S_STORE_UNAVAILABLE, None,
                               (R_STORE_UNAVAILABLE,), state.now)

        # 6. C1 : STOP ABSOLU. Aucun dispatch. Invariant authorizations/outcomes vides revérifié.
        self.journal.assert_c1_invariants()

        return self._reply(proposal.request_id, proposal_id, decision_id, S_SHADOW_RECORDED,
                           decision.verdict, decision.reason_codes, state.now)
