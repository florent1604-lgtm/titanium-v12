"""gateway/policy_kernel.py — PolicyKernel : fonction PURE et DÉTERMINISTE.

`evaluate(AttestedProposal, TrustedState) -> PolicyDecision`

Aucun réseau, aucune I/O, aucun appel LLM, aucune horloge (elle vient de `state.now`). Le
kernel valide identité/schéma/TTL/mode/compte/fraîcheur/intégrité EventPlane/policy/M2/
approval/kill-switch. Tout champ inconnu ou preuve absente produit DENY ou NO_DECISION
(default-deny). Le champ `justification` n'est JAMAIS lu (déterminisme, test C1 n°6).

En C1, même un verdict logique ALLOW devient un ShadowDecision : `dispatch_permitted=False`,
`shadow=True`, avec le code `C1_SHADOW_NO_DISPATCH`. AUCUN chemin ne permet le dispatch.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Optional

from gateway import capability_registry as _reg
from gateway.contracts import (
    AttestedProposal, PolicyDecision, TrustedState, POLICY_VERSION,
    R_APPROVAL_MISSING, R_CLOCK_INCOHERENT, R_EVENTPLANE_INTEGRITY_BROKEN,
    R_KILL_SWITCH_ACTIVE, R_M2_PROOF_MISSING, R_MODE_NOT_ALLOWED, R_PARAM_SCHEMA_VIOLATION,
    R_POLICY_MISMATCH, R_PROJECTION_STALE, R_REAL_ACCOUNT_ORDER_FORBIDDEN, R_SHADOW_NO_DISPATCH,
    R_STATE_UNAVAILABLE, R_TTL_EXPIRED, R_UNKNOWN_CAPABILITY, VERDICT_ALLOW, VERDICT_DENY,
    VERDICT_NO_DECISION,
)


def _deny(*codes: str) -> PolicyDecision:
    return PolicyDecision(VERDICT_DENY, False, tuple(codes), POLICY_VERSION, True)


def _no_decision(*codes: str) -> PolicyDecision:
    return PolicyDecision(VERDICT_NO_DECISION, False, tuple(codes), POLICY_VERSION, True)


def _parse(ts) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def evaluate(attested: AttestedProposal, state: Optional[TrustedState], *,
             cap_lookup: Optional[Callable] = None) -> PolicyDecision:
    """Décision SHADOW pure. `cap_lookup(capability_id, version)` injectable (tests) ; défaut =
    registre gelé. Ordre strictement fail-closed : la première violation gagne."""
    if state is None:
        return _no_decision(R_STATE_UNAVAILABLE)
    getcap = cap_lookup or _reg.get_capability
    p = attested.proposal

    # 1. Cohérence d'horloge + TTL (le kernel n'appelle pas l'horloge : tout vient de state).
    now, created, expires = _parse(state.now), _parse(p.created_at), _parse(p.expires_at)
    if now is None or created is None or expires is None or created > expires:
        return _deny(R_CLOCK_INCOHERENT)
    if now < created:
        return _deny(R_CLOCK_INCOHERENT)
    if now > expires:
        return _deny(R_TTL_EXPIRED)

    # 2. Santé de l'état projeté (intégrité EventPlane + fraîcheur).
    if not state.eventplane_integrity_ok:
        return _deny(R_EVENTPLANE_INTEGRITY_BROKEN)
    if state.projection_stale:
        return _deny(R_PROJECTION_STALE)

    # 3. Kill-switch : rien ne passe.
    if state.kill_switch_active:
        return _deny(R_KILL_SWITCH_ACTIVE)

    # 4. Capacité connue + version.
    cap = getcap(p.capability_id, p.capability_version)
    if cap is None:
        return _deny(R_UNKNOWN_CAPABILITY)

    # 5. Sûreté compte EN PREMIER : une capacité porteuse d'ordre sur un compte RÉEL est
    #    interdite, toujours, sans exception (test C1 n°8) — vérifiée avant tout le reste pour
    #    qu'un mode malformé ne masque jamais ce mur. Le mur démo↔réel reste absolu.
    if cap.requires_order and state.account_is_real:
        return _deny(R_REAL_ACCOUNT_ORDER_FORBIDDEN)

    # 6. Mode demandé autorisé par la capacité ET cohérent avec le mode du compte.
    if p.requested_mode not in cap.allowed_modes or state.account_mode != p.requested_mode:
        return _deny(R_MODE_NOT_ALLOWED)

    # 7. Policy attendue par la capacité.
    if cap.required_policy != POLICY_VERSION:
        return _deny(R_POLICY_MISMATCH)

    # 8. Schéma des paramètres (clé inconnue / type / borne).
    err = cap.validate_params(p.params)
    if err is not None:
        return _deny(R_PARAM_SCHEMA_VIOLATION)

    # 9. Preuves obligatoires : M2 puis approval. Absentes → DENY (jamais supposées présentes).
    if cap.m2_required and not p.m2_proof:
        return _deny(R_M2_PROOF_MISSING)
    if cap.approval_required and not p.approval:
        return _deny(R_APPROVAL_MISSING)

    # 10. Verdict logique ALLOW — mais C1 SHADOW : aucun dispatch, jamais.
    return PolicyDecision(VERDICT_ALLOW, False, (R_SHADOW_NO_DISPATCH,), POLICY_VERSION, True)
