"""gateway/capability_registry.py — registre FERMÉ des capacités (C1 SHADOW).

Le registre est chargé depuis un JSON gelé dont le digest SHA-256 est vérifié au chargement
(même patron que core.event_registry). En C1 :
  - chaque capacité est décrite pour ÉVALUATION shadow ;
  - son statut exécutable est `SHADOW_ONLY` ;
  - la table interne `handler_id -> callable` est VIDE ;
  - toute tentative de résolution d'un handler est une VIOLATION CRITIQUE (test C1 n°9).

Aucune capacité de changement de policy/risque/compte/mode/registre/secret/kill-switch/
circuit-breaker/approval n'est présente : elles ne sont jamais exposées.
"""
from __future__ import annotations

import hashlib
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Callable, Dict, Optional

import json

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = ROOT / "docs" / "contracts" / "command-registry-v1.json"
DIGEST_PATH = ROOT / "docs" / "contracts" / "command-registry-v1.sha256"
EXPECTED_REGISTRY_SHA256 = (
    "AE2C9EACF67E4D6F6A654EAF6C4048F1CC3E7CCD2BDFC3E3D9BB05FDE5F980C2"
)

# Table de dispatch INTERNE. VIDE par invariant C1. Ne jamais peupler dans ce lot.
_HANDLERS: Dict[str, Callable] = {}


class RegistryViolation(ValueError):
    """Registre de capacités non conforme ou altéré."""


class CriticalShadowViolation(RuntimeError):
    """Tentative interdite en C1 (ex. résoudre un handler). Doit provoquer un arrêt fail-closed."""


class Capability:
    __slots__ = ("capability_id", "version", "effect_class", "allowed_modes",
                 "requires_order", "required_policy", "ttl_seconds", "rate_limit_per_min",
                 "m2_required", "approval_required", "executable_status", "handler_id",
                 "_param_validator")

    def __init__(self, spec: dict, *, defs_schema: dict):
        self.capability_id = spec["capability_id"]
        self.version = int(spec["version"])
        self.effect_class = spec["effect_class"]
        self.allowed_modes = tuple(spec["allowed_modes"])
        self.requires_order = bool(spec["requires_order"])
        self.required_policy = spec["required_policy"]
        self.ttl_seconds = int(spec["ttl_seconds"])
        self.rate_limit_per_min = int(spec["rate_limit_per_min"])
        self.m2_required = bool(spec["m2_required"])
        self.approval_required = bool(spec["approval_required"])
        self.executable_status = spec["executable_status"]
        self.handler_id = spec["handler_id"]
        self._param_validator = Draft202012Validator(dict(spec["param_schema"]))

    def validate_params(self, params) -> Optional[str]:
        """None si les paramètres respectent le schéma, sinon un chemin d'erreur court."""
        errors = sorted(self._param_validator.iter_errors(dict(params)),
                        key=lambda e: tuple(str(p) for p in e.path))
        if not errors:
            return None
        first = errors[0]
        path = ".".join(str(p) for p in first.path) or "$"
        return f"{path}:{first.validator}"


@lru_cache(maxsize=1)
def load_registry() -> dict:
    raw = REGISTRY_PATH.read_bytes()
    companion = DIGEST_PATH.read_text(encoding="ascii").split()[0].upper()
    actual = hashlib.sha256(raw).hexdigest().upper()
    if not secrets.compare_digest(companion, EXPECTED_REGISTRY_SHA256):
        raise RegistryViolation("REGISTRY_COMPANION_DIGEST_MISMATCH")
    if not secrets.compare_digest(actual, EXPECTED_REGISTRY_SHA256):
        raise RegistryViolation("REGISTRY_DIGEST_MISMATCH")
    reg = json.loads(raw.decode("utf-8"))
    if reg.get("registry_version") != "command-registry/1.0.0":
        raise RegistryViolation("REGISTRY_VERSION_MISMATCH")
    if reg.get("status") != "FROZEN":
        raise RegistryViolation("REGISTRY_NOT_FROZEN")
    if reg.get("palier") != "C1_SHADOW":
        raise RegistryViolation("REGISTRY_PALIER_MISMATCH")
    if not isinstance(reg.get("capabilities"), dict):
        raise RegistryViolation("REGISTRY_CAPABILITIES_INVALID")
    for cap in reg["capabilities"].values():
        if cap.get("executable_status") != "SHADOW_ONLY":
            raise RegistryViolation("CAPABILITY_NOT_SHADOW_ONLY")  # invariant C1 dur
    return reg


def registry_digest() -> str:
    """Digest SHA-256 (minuscule) du registre gelé, pour la traçabilité des décisions."""
    return EXPECTED_REGISTRY_SHA256.lower()


@lru_cache(maxsize=1)
def _capabilities() -> Dict[str, Capability]:
    reg = load_registry()
    defs = {}
    out: Dict[str, Capability] = {}
    for cap in reg["capabilities"].values():
        c = Capability(cap, defs_schema=defs)
        out[f"{c.capability_id}@{c.version}"] = c
    return out


def get_capability(capability_id: str, version: int) -> Optional[Capability]:
    """Capacité correspondante, ou None si inconnue (→ default-deny en amont)."""
    return _capabilities().get(f"{capability_id}@{version}")


def resolve_handler(handler_id: str):
    """INTERDIT en C1. La table de handlers est vide ; toute résolution est critique."""
    raise CriticalShadowViolation(f"HANDLER_RESOLUTION_FORBIDDEN_C1:{handler_id}")


def handler_count() -> int:
    """Doit valoir 0 en C1 (invariant vérifié au démarrage, en test et en santé)."""
    return len(_HANDLERS)
