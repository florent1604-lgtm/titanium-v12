"""domain/agent_registry.py — Registre de capacités FERMÉ (patron A, slices 1-2).

Frontière d'exécution du cerveau JARVIS/Hermes (audit MSJARVIS, patron A validé
par Florent le 2026-07-12). Principe non négociable (Claude + Hermes + Codex) :

    Le plan produit par un LLM est une donnée NON FIABLE. Seules les capacités
    déclarées ici, avec un schéma strict et un handler CODÉ, peuvent s'exécuter.
    Aucune URL, commande ou nom de fonction fourni par le LLM n'est exécuté.

Modes :
  - READ   : lecture seule (endpoints GET Titanium) — aucun effet.
  - MUTATE : action non destructive (endpoints POST protégés `require_admin`).
    Slice 2 : uniquement scans/relance (jamais reset de compte, jamais d'ordre
    réel). L'orchestrateur exige `allow_mutate=True` ET un jeton admin valide,
    et l'endpoint applique lui-même `require_admin` (défense en profondeur).

Validation fail-closed du schéma : capacité inconnue → refus ; clé non déclarée,
requis manquant, mauvais type → PARAMS_INVALID.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Tuple

HttpGet = Callable[[str], dict]
HttpPost = Callable[[str], dict]     # POST déjà porteur du jeton admin (voir Deps)

_BASE_URL = "http://127.0.0.1:8090"


def default_http_get(path: str) -> dict:
    """GET JSON sur l'API Titanium locale (lecture seule)."""
    req = urllib.request.Request(_BASE_URL + path, method="GET")
    with urllib.request.urlopen(req, timeout=4) as resp:
        return json.loads(resp.read().decode("utf-8"))


def make_http_post(admin_token: str) -> HttpPost:
    """Fabrique un POST porteur de l'en-tête `X-Admin-Token` (mutations protégées)."""
    def _post(path: str) -> dict:
        req = urllib.request.Request(_BASE_URL + path, method="POST",
                                     headers={"X-Admin-Token": admin_token or ""})
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {"status": "ok"}
    return _post


@dataclass
class Deps:
    """Dépendances injectables passées aux handlers (testables, sûres)."""
    get: HttpGet
    post: HttpPost


# ── Schéma de paramètres (minimal, strict) ───────────────────────────────────

@dataclass(frozen=True)
class Param:
    name: str
    type: type
    required: bool = True


@dataclass(frozen=True)
class Capability:
    id: str
    mode: str                       # "READ" | "MUTATE"
    description: str
    params: Tuple[Param, ...]
    handler: Callable[[Dict[str, Any], "Deps"], dict]
    synth: Callable[[dict], str]

    def validate_params(self, params: Dict[str, Any]) -> Tuple[bool, str]:
        if not isinstance(params, dict):
            return False, f"PARAMS_INVALID: params doit être un objet ({type(params).__name__})"
        declared = {p.name: p for p in self.params}
        for key in params:
            if key not in declared:
                return False, f"PARAMS_INVALID: paramètre inconnu '{key}'"
        for p in self.params:
            if p.required and p.name not in params:
                return False, f"PARAMS_INVALID: paramètre requis manquant '{p.name}'"
            if p.name in params and not isinstance(params[p.name], p.type):
                return False, (f"PARAMS_INVALID: '{p.name}' doit être "
                               f"{p.type.__name__}, reçu {type(params[p.name]).__name__}")
        return True, "ok"


# ── Handlers LECTURE (GET) ────────────────────────────────────────────────────

def _h_pnl(_p, d): return d.get("/paper/stats")
def _h_positions(_p, d): return {"positions": d.get("/paper/positions")}
def _h_swing(_p, d): return d.get("/swing/status")
def _h_opportunities(_p, d): return d.get("/opportunities/status")
def _h_risk(_p, d): return d.get("/swing/risk/exposure")

# ── Handlers ACTION (POST protégé — non destructif) ──────────────────────────

def _h_run_swing_scan(_p, d): return d.post("/swing/scan")
def _h_run_opportunity_scan(_p, d): return d.post("/opportunities/run")
def _h_reset_circuit_breaker(_p, d): return d.post("/paper/reset-circuit-breaker")


# ── Synthèses (data -> phrase ; défensives) ──────────────────────────────────

def _s_pnl(d):
    return (f"Compte paper crypto : equity {d.get('equity', '?')} USDT, "
            f"P&L réalisé {d.get('realized_pnl', '?')} USDT, "
            f"winrate {d.get('winrate', '?')} % sur {d.get('total_trades', '?')} trades.")

def _s_positions(d):
    pos = d.get("positions") or {}
    n = len(pos) if hasattr(pos, "__len__") else 0
    return f"{n} position(s) paper ouverte(s)." if n else "Aucune position paper ouverte."

def _s_swing(d):
    cfgs = d.get("configs") or {}
    return (f"Moteur swing {'actif' if d.get('enabled') else 'inactif'}, "
            f"{len(cfgs)} actif(s) suivi(s) ; MT5 "
            f"{'connecté (données seulement)' if (d.get('mt5') or {}).get('connected') else 'déconnecté'}.")

def _s_opportunities(d):
    return f"Scan d'opportunités : {json.dumps(d, ensure_ascii=False)[:180]}"

def _s_risk(d):
    if not d.get("ok", True):
        return "Risque portefeuille INDISPONIBLE (garde fail-closed actif)."
    return (f"Risque portefeuille : gross {d.get('gross_eur', '?')} €, "
            f"net {d.get('net_eur', '?')} €.")

def _s_run_swing(d):
    sig = d.get("signals") or {}
    return f"Scan swing lancé (paper). {len(sig)} signal(aux)." if isinstance(sig, dict) else "Scan swing lancé (paper)."

def _s_run_opp(d):
    return "Scan d'opportunités lancé (paper)."

def _s_reset_cb(d):
    return "Circuit-breaker réinitialisé."


# ── Le registre FERMÉ ─────────────────────────────────────────────────────────

_REGISTRY: Dict[str, Capability] = {
    c.id: c for c in (
        # READ
        Capability("get_pnl", "READ", "État du compte paper crypto (equity, P&L, winrate).",
                   (), _h_pnl, _s_pnl),
        Capability("get_positions", "READ", "Positions paper ouvertes.",
                   (), _h_positions, _s_positions),
        Capability("get_swing_status", "READ", "État du moteur swing MT5 (paper).",
                   (), _h_swing, _s_swing),
        Capability("get_opportunities", "READ", "État du scan d'opportunités.",
                   (), _h_opportunities, _s_opportunities),
        Capability("get_risk_exposure", "READ", "Exposition et plafonds de risque R3.",
                   (), _h_risk, _s_risk),
        # MUTATE (non destructif, admin requis)
        Capability("run_swing_scan", "MUTATE", "Force un cycle de scan swing (paper).",
                   (), _h_run_swing_scan, _s_run_swing),
        Capability("run_opportunity_scan", "MUTATE", "Lance le scan d'opportunités (paper).",
                   (), _h_run_opportunity_scan, _s_run_opp),
        Capability("reset_circuit_breaker", "MUTATE", "Réinitialise le circuit-breaker paper.",
                   (), _h_reset_circuit_breaker, _s_reset_cb),
    )
}


def list_capabilities() -> List[dict]:
    return [{"id": c.id, "mode": c.mode, "description": c.description,
             "params": [{"name": p.name, "type": p.type.__name__, "required": p.required}
                        for p in c.params]}
            for c in _REGISTRY.values()]


def get_capability(cap_id: str) -> Capability | None:
    return _REGISTRY.get(cap_id)
