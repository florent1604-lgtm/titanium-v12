"""core/cloe/reflex.py — LE RÉFLEXE DE CLOE : son verdict avant l'exécution.

Florent 29/07 : « donne le contrôle à Cloe ». C'est ici qu'elle passe d'observatrice
à décideuse — sur le dernier maillon, celui qui compte : juste avant de placer.

CONTRAT NON NÉGOCIABLE (condition de Florent : « aucune latence ») :
  · petit modèle RÉSIDENT (qwen2.5:3b, ~1,3 s à chaud, jamais déchargé) ;
  · AUCUN outil, AUCUN réseau, AUCUN MCP dans ce chemin ;
  · TIMEOUT DUR + **FAIL-OPEN** : pas de réponse, modèle absent, JSON illisible,
    Ollama éteint → on laisse passer la décision déterministe. Cloe ne peut JAMAIS
    bloquer le bot par sa lenteur ou sa panne. Elle ne peut que REFUSER un trade
    en connaissance de cause.
  · elle ne peut jamais OUVRIR un trade que le moteur n'a pas déjà validé : son
    pouvoir est un VETO, pas une initiative (invariant de sécurité).

Elle reçoit la perception complète et réparée (piliers, régime géométrix, ÉMOTION,
fondamentaux, coût, exposition) — la même que celle du journal.
"""
from __future__ import annotations

import json
import math
import os
import re
from typing import Any, Dict, Optional

_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
_HARD_TIMEOUT_CAP_S = 2.0


def _cfg(name: str, default: str) -> str:
    return os.getenv(name, default)


def _cfg_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


SYSTEM = (
    "Tu es Cloe, le réflexe de décision du bot Titanium. Tu juges UN setup déjà validé "
    "par les moteurs déterministes. Ton rôle : repérer ce qu'ils ne voient pas — "
    "incohérence entre les organes, contexte qui ne tient pas, régime dangereux.\n"
    "Réponds UNIQUEMENT par du JSON compact, rien d'autre :\n"
    '{"verdict":"OK|DOUTE|STOP","raison":"<10 mots max>"}\n'
    "OK = laisse passer. DOUTE = laisse passer mais taille réduite. "
    "STOP = refuse (réserve-le aux vraies incohérences). "
    "N'invente jamais une donnée absente : None ou inconnu n'est PAS une incohérence "
    "et ne justifie jamais STOP."
)


def _prompt(ctx: Dict[str, Any]) -> str:
    emo = ctx.get("emotion") or {}
    fon = ctx.get("fundamentals") or {}
    return (
        f"Actif {ctx.get('symbol')} | sens {'LONG' if (ctx.get('side') or 0) > 0 else 'SHORT'} "
        f"| {ctx.get('n_pillars')} piliers {ctx.get('pillars')}\n"
        f"Tendance H4 {ctx.get('trend_h4')} | régime {ctx.get('regime_geo')} "
        f"(lyapunov {ctx.get('lyapunov')}, fisher {ctx.get('fisher')}, "
        f"alerte topo {ctx.get('topo_alert')})\n"
        f"Émotion marché : {emo.get('label')} (valence {emo.get('valence')}, "
        f"énergie {emo.get('arousal')})\n"
        f"Fondamentaux : {fon.get('level')} ({fon.get('score')})\n"
        f"Coût aller-retour {ctx.get('roundtrip_cost')} | exposition "
        f"{ctx.get('exposure_gross_pct')}% | confiance mesurée {ctx.get('confidence')}\n"
        "Verdict ?"
    )


def _parse(txt: str) -> Optional[Dict[str, str]]:
    m = re.search(r"\{.*?\}", txt or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        return None
    v = str(d.get("verdict", "")).upper().strip()
    if v not in ("OK", "DOUTE", "STOP"):
        return None
    return {"verdict": v, "raison": str(d.get("raison", ""))[:80]}


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _missing_context(ctx: Dict[str, Any]) -> list[str]:
    """Liste les perceptions indispensables à un veto fondé."""
    missing: list[str] = []
    if not isinstance(ctx.get("symbol"), str) or not ctx["symbol"].strip():
        missing.append("symbol")
    if ctx.get("side") not in (-1, 1):
        missing.append("side")
    if not isinstance(ctx.get("pillars"), list) or not ctx["pillars"]:
        missing.append("pillars")
    if not _finite(ctx.get("n_pillars")):
        missing.append("n_pillars")
    if ctx.get("trend_h4") not in (-1, 0, 1):
        missing.append("trend_h4")
    if not ctx.get("regime_geo"):
        missing.append("regime_geo")
    for field in ("lyapunov", "fisher", "roundtrip_cost",
                  "exposure_gross_pct", "confidence"):
        if not _finite(ctx.get(field)):
            missing.append(field)
    if not isinstance(ctx.get("topo_alert"), bool):
        missing.append("topo_alert")

    emotion = ctx.get("emotion")
    if not isinstance(emotion, dict) or emotion.get("available") is not True:
        missing.append("emotion")
    else:
        if not emotion.get("label"):
            missing.append("emotion.label")
        for field in ("valence", "arousal"):
            if not _finite(emotion.get(field)):
                missing.append(f"emotion.{field}")

    fundamentals = ctx.get("fundamentals")
    if not isinstance(fundamentals, dict):
        missing.append("fundamentals")
    else:
        if not _finite(fundamentals.get("score")):
            missing.append("fundamentals.score")
        if not fundamentals.get("level"):
            missing.append("fundamentals.level")
    return missing


def judge(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Verdict de Cloe sur un setup. FAIL-OPEN absolu.

    Retour : {verdict, raison, size_factor, latency_ms, available}
    `size_factor` module la taille (DOUTE → réduction), jamais au-dessus de 1.0.
    """
    out = {"verdict": "OK", "raison": "cloe indisponible", "size_factor": 1.0,
           "available": False, "latency_ms": 0}
    if _cfg("CLOE_REFLEX_ENABLED", "0") != "1":
        out["raison"] = "reflexe desarme"
        return out
    missing = _missing_context(ctx)
    if missing:
        out["raison"] = f"contexte incomplet:{','.join(missing)}"[:80]
        return out
    try:
        import time

        import requests
        t0 = time.time()
        r = requests.post(
            f"{_URL}/api/chat",
            json={"model": _cfg("CLOE_REFLEX_MODEL", "qwen2.5:3b"),
                  "messages": [{"role": "system", "content": SYSTEM},
                               {"role": "user", "content": _prompt(ctx)}],
                  "stream": False, "keep_alive": -1,
                  "options": {"num_predict": 48, "temperature": 0.1,
                              "num_thread": int(_cfg_float("CLOE_REFLEX_THREADS", 5))}},
            timeout=min(
                _HARD_TIMEOUT_CAP_S,
                max(0.1, _cfg_float("CLOE_REFLEX_TIMEOUT_S", _HARD_TIMEOUT_CAP_S)),
            ))
        out["latency_ms"] = int((time.time() - t0) * 1000)
        if r.status_code != 200:
            out["raison"] = f"http {r.status_code}"
            return out
        parsed = _parse((r.json().get("message") or {}).get("content", ""))
        if not parsed:
            out["raison"] = "reponse illisible"
            return out
        out.update(parsed)
        out["available"] = True
        out["size_factor"] = {"OK": 1.0,
                              "DOUTE": _cfg_float("CLOE_REFLEX_DOUBT_SIZE", 0.5),
                              "STOP": 0.0}[out["verdict"]]
    except Exception as exc:  # noqa: BLE001 — jamais de remontée vers le trading
        out["raison"] = f"erreur {type(exc).__name__}"
    return out
