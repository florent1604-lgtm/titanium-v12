"""gateway/contracts.py — contrats GELÉS du CommandGateway C1 SHADOW.

Types de données purs (dataclasses frozen) + codes de raison. Aucune I/O, aucun réseau,
aucun import d'exécution/MT5. Le champ `principal` d'une proposition est INFORMATIF : il ne
remplace jamais l'identité OS attestée (`AttestedPrincipal`). Le champ `justification` est
libre et ne DOIT JAMAIS influencer un verdict (déterminisme, test C1 n°6).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Tuple

REPLY_SCHEMA_VERSION = 1
POLICY_VERSION = "policy/1.0.0"

# --- Codes de raison (fail-closed / default-deny). Stables, sans contenu sensible. --------
R_SHADOW_NO_DISPATCH = "C1_SHADOW_NO_DISPATCH"
R_REJECTED_SCHEMA = "REJECTED_SCHEMA"
R_UNKNOWN_FIELD = "UNKNOWN_FIELD"
R_IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
R_STORE_UNAVAILABLE = "STORE_UNAVAILABLE"
R_STATE_UNAVAILABLE = "STATE_UNAVAILABLE"
R_UNKNOWN_CAPABILITY = "UNKNOWN_CAPABILITY"
R_MODE_NOT_ALLOWED = "MODE_NOT_ALLOWED"
R_REAL_ACCOUNT_ORDER_FORBIDDEN = "REAL_ACCOUNT_ORDER_FORBIDDEN"
R_TTL_EXPIRED = "TTL_EXPIRED"
R_CLOCK_INCOHERENT = "CLOCK_INCOHERENT"
R_PROJECTION_STALE = "PROJECTION_STALE"
R_EVENTPLANE_INTEGRITY_BROKEN = "EVENTPLANE_INTEGRITY_BROKEN"
R_KILL_SWITCH_ACTIVE = "KILL_SWITCH_ACTIVE"
R_M2_PROOF_MISSING = "M2_PROOF_MISSING"
R_APPROVAL_MISSING = "APPROVAL_MISSING"
R_PARAM_SCHEMA_VIOLATION = "PARAM_SCHEMA_VIOLATION"
R_POLICY_MISMATCH = "POLICY_MISMATCH"
R_AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"

# Statuts de réponse (sous-ensemble de la machine d'états, section 5 de la spec).
S_SHADOW_RECORDED = "SHADOW_RECORDED"
S_DEDUPLICATED = "DEDUPLICATED"
S_REJECTED_SCHEMA = "REJECTED_SCHEMA"
S_REJECTED_AUTH = "REJECTED_AUTH"
S_STORE_UNAVAILABLE = "STORE_UNAVAILABLE"
S_IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"

VERDICT_ALLOW = "ALLOW"
VERDICT_DENY = "DENY"
VERDICT_NO_DECISION = "NO_DECISION"


class SchemaError(ValueError):
    """Enveloppe de proposition mal formée (clé inconnue, type, taille)."""


# Clés autorisées d'une proposition (enveloppe). Toute autre clé = SchemaError (default-deny).
_PROPOSAL_KEYS = {
    "request_id", "capability_id", "capability_version", "requested_mode",
    "params", "idempotency_key", "created_at", "expires_at",
    "principal", "justification", "m2_proof", "approval",
}
_REQUIRED_KEYS = {
    "request_id", "capability_id", "capability_version", "requested_mode",
    "params", "idempotency_key", "created_at", "expires_at",
}
MAX_FRAME_BYTES = 64 * 1024


@dataclass(frozen=True)
class Proposal:
    """Proposition NON FIABLE (après parsing de l'enveloppe JSON). `principal`/`justification`
    sont informatifs et n'ont AUCUNE autorité."""
    request_id: str
    capability_id: str
    capability_version: int
    requested_mode: str
    params: Mapping[str, Any]
    idempotency_key: str
    created_at: str
    expires_at: str
    principal: Optional[str] = None
    justification: Optional[str] = None
    m2_proof: Optional[str] = None
    approval: Optional[str] = None

    @staticmethod
    def parse(raw: Mapping[str, Any]) -> "Proposal":
        """Valide l'enveloppe : type objet, clés connues, clés requises, types de base.
        Clé inconnue → SchemaError (les clés inconnues sont INTERDITES, section 4.3)."""
        if not isinstance(raw, Mapping):
            raise SchemaError("PROPOSAL_NOT_OBJECT")
        keys = set(raw.keys())
        unknown = keys - _PROPOSAL_KEYS
        if unknown:
            raise SchemaError(f"UNKNOWN_FIELD:{sorted(unknown)[0]}")
        missing = _REQUIRED_KEYS - keys
        if missing:
            raise SchemaError(f"MISSING_FIELD:{sorted(missing)[0]}")
        if not isinstance(raw["capability_version"], int) or isinstance(raw["capability_version"], bool):
            raise SchemaError("capability_version:int")
        if not isinstance(raw["params"], Mapping):
            raise SchemaError("params:object")
        for k in ("request_id", "capability_id", "requested_mode", "idempotency_key",
                  "created_at", "expires_at"):
            if not isinstance(raw[k], str) or not raw[k]:
                raise SchemaError(f"{k}:non-empty-string")
        for k in ("principal", "justification", "m2_proof", "approval"):
            if k in raw and raw[k] is not None and not isinstance(raw[k], str):
                raise SchemaError(f"{k}:string-or-null")
        return Proposal(
            request_id=raw["request_id"], capability_id=raw["capability_id"],
            capability_version=raw["capability_version"], requested_mode=raw["requested_mode"],
            params=dict(raw["params"]), idempotency_key=raw["idempotency_key"],
            created_at=raw["created_at"], expires_at=raw["expires_at"],
            principal=raw.get("principal"), justification=raw.get("justification"),
            m2_proof=raw.get("m2_proof"), approval=raw.get("approval"),
        )


@dataclass(frozen=True)
class AttestedPrincipal:
    """Identité OS ATTESTÉE (via impersonation du pipe dans un lot ultérieur ; injectée par
    l'appelant ici). C'est la SEULE source d'identité — jamais le champ JSON `principal`."""
    sid: str
    kind: str            # ex. "HERMES_SERVICE" | "GATEWAY_SERVICE" | "OPERATOR" | "AI_REVIEWER"


@dataclass(frozen=True)
class AttestedProposal:
    proposal: Proposal
    principal: AttestedPrincipal
    received_at: str


@dataclass(frozen=True)
class TrustedState:
    """Projection de confiance que le kernel LIT (jamais recalculée par lui). Tout champ requis
    absent = fail-closed en amont. `now` est fourni (le kernel n'appelle pas l'horloge)."""
    now: str
    account_mode: str            # "PAPER" | "DEMO" | "REAL"
    account_is_real: bool
    kill_switch_active: bool
    eventplane_integrity_ok: bool
    projection_stale: bool
    projection_as_of: str


@dataclass(frozen=True)
class PolicyDecision:
    """Décision du PolicyKernel. En C1, `dispatch_permitted` est TOUJOURS False et `shadow`
    TOUJOURS True, même pour un verdict logique ALLOW."""
    verdict: str                 # VERDICT_ALLOW | VERDICT_DENY | VERDICT_NO_DECISION
    dispatch_permitted: bool
    reason_codes: Tuple[str, ...]
    policy_version: str = POLICY_VERSION
    shadow: bool = True


@dataclass(frozen=True)
class GatewayReply:
    """Réponse stricte et stable (section 4.7). Aucun message libre, stack trace, chemin, SID
    complet ni contenu sensible."""
    request_id: str
    proposal_id: Optional[str]
    decision_id: Optional[str]
    status: str
    verdict: Optional[str]
    dispatch_permitted: bool
    reason_codes: Tuple[str, ...]
    policy_version: str
    registry_digest: str
    recorded_at: str
    correlation_id: str
    reply_schema_version: int = REPLY_SCHEMA_VERSION

    def to_dict(self) -> dict:
        return {
            "reply_schema_version": self.reply_schema_version,
            "request_id": self.request_id,
            "proposal_id": self.proposal_id,
            "decision_id": self.decision_id,
            "status": self.status,
            "verdict": self.verdict,
            "dispatch_permitted": self.dispatch_permitted,
            "reason_codes": list(self.reason_codes),
            "policy_version": self.policy_version,
            "registry_digest": self.registry_digest,
            "recorded_at": self.recorded_at,
            "correlation_id": self.correlation_id,
        }
