"""tools/perception_sentinel.py — LA SENTINELLE : veille sur la vision de Cloe.

Florent 28/07 : « je compte sur toi pour la surveiller ». Une session se ferme ; une
sentinelle, non. Ce module vérifie en continu qu'AUCUN organe ne devient aveugle en
silence — le mode de panne le plus dangereux, parce qu'il ne lève aucune erreur : le
champ passe simplement à `null` et Cloe croit voir.

C'est exactement ce qui s'était produit : l'émotion renvoyait `null` sur 159/159 entrées
pendant que l'organe fonctionnait parfaitement. Rien n'avait alerté.

Vérifie, sur la fenêtre récente du journal :
  · le TAUX DE NULL par organe (émotion, régime, fisher, fondamentaux, macro, coût…) ;
  · que les FANTÔMES (refus) portent la même perception que les entrées — ils pèsent ~27×
    leur volume et constituent le principal gisement d'apprentissage ;
  · que le cœur bat (journal qui grossit, cycle de fusion récent) ;
  · que le réflexe de Cloe est RÉSIDENT en mémoire (sinon chaque appel repart à froid).

Lecture seule, fail-safe : n'écrit qu'un rapport et des WARNING. Ne touche à rien.
Usage : venv\\Scripts\\python.exe -m tools.perception_sentinel
"""
from __future__ import annotations

import json
import logging
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "journal" / "titanium_journal.sqlite3"
OUT = ROOT / "data" / "perception_sentinel.json"

# Organes surveillés → chemin dans le payload. Un organe sous le seuil = CÉCITÉ.
_ORGANES = {
    "emotion.label":     lambda d: (d.get("emotion") or {}).get("label"),
    "emotion.valence":   lambda d: (d.get("emotion") or {}).get("valence"),
    "emotion.arousal":   lambda d: (d.get("emotion") or {}).get("arousal"),
    "regime_geo":        lambda d: d.get("regime_geo"),
    "lyapunov":          lambda d: d.get("lyapunov"),
    "fisher":            lambda d: d.get("fisher"),
    "curvature":         lambda d: d.get("curvature"),
    "trend_h4":          lambda d: d.get("trend_h4"),
    "fondamentaux":      lambda d: (d.get("fundamentals") or {}).get("score"),
    "macro.fear_greed":  lambda d: (d.get("macro") or {}).get("fear_greed"),
    "cout_AR":           lambda d: d.get("roundtrip_cost"),
    "equity":            lambda d: d.get("equity"),
}
SEUIL_CECITE = 0.30       # < 30 % de valeurs présentes ⇒ organe considéré AVEUGLE
SEUIL_PARTIEL = 0.90


def _scan(cur, kind: str, since: str) -> Dict[str, Any]:
    rows = cur.execute(
        "SELECT payload FROM journal_events WHERE kind=? AND ts_utc>=? "
        "ORDER BY ts_utc DESC LIMIT 500", (kind, since)).fetchall()
    n = len(rows)
    if not n:
        return {"n": 0, "organes": {}}
    vus = {k: 0 for k in _ORGANES}
    for (p,) in rows:
        try:
            d = json.loads(p)
        except Exception:  # noqa: BLE001
            continue
        for nom, get in _ORGANES.items():
            try:
                if get(d) is not None:
                    vus[nom] += 1
            except Exception:  # noqa: BLE001
                pass
    return {"n": n, "organes": {k: round(v / n, 3) for k, v in vus.items()}}


def check(minutes: int = 30) -> Dict[str, Any]:
    """Un passage de veille. Retourne le rapport (et l'écrit). Ne lève jamais."""
    rap: Dict[str, Any] = {"ts_utc": datetime.now(timezone.utc).isoformat(),
                           "fenetre_min": minutes, "alertes": [], "ok": True}
    try:
        since = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=5)
        try:
            cur = con.cursor()
            for kind in ("fill", "ghost"):
                rap[kind] = _scan(cur, kind, since)
        finally:
            con.close()

        # 1) organes aveugles / partiels (on n'alerte que s'il y a de la matière à juger)
        for kind in ("fill", "ghost"):
            bloc = rap.get(kind) or {}
            if bloc.get("n", 0) < 5:
                continue
            for organe, taux in (bloc.get("organes") or {}).items():
                if taux < SEUIL_CECITE:
                    rap["alertes"].append(
                        f"CECITE [{kind}] {organe} : {taux:.0%} de valeurs présentes "
                        f"(sur {bloc['n']} évén.)")
                elif taux < SEUIL_PARTIEL:
                    rap["alertes"].append(
                        f"partiel [{kind}] {organe} : {taux:.0%}")

        # 2) les refus doivent porter la MÊME perception que les entrées (régression connue)
        f, g = rap.get("fill") or {}, rap.get("ghost") or {}
        if f.get("n", 0) >= 5 and g.get("n", 0) >= 5:
            manquants = [o for o in _ORGANES
                         if (f["organes"].get(o, 0) >= SEUIL_PARTIEL
                             and g["organes"].get(o, 0) < SEUIL_CECITE)]
            if manquants:
                rap["alertes"].append(
                    "DIVERGENCE entrées/refus — organes absents des refus : "
                    + ", ".join(manquants))

        # 3) le cœur bat-il ? (rien de journalisé = moteur muet)
        if (rap.get("fill") or {}).get("n", 0) == 0 and (rap.get("ghost") or {}).get("n", 0) == 0:
            rap["alertes"].append(
                f"SILENCE : aucun événement journalisé depuis {minutes} min "
                "(bot arrêté, marché fermé, ou moteur bloqué ?)")

        # 4) le réflexe de Cloe est-il résident ? (sinon chaque appel repart à froid)
        try:
            import requests
            ps = requests.get("http://localhost:11434/api/ps", timeout=4).json()
            noms = [m.get("name", "") for m in (ps.get("models") or [])]
            rap["cloe_resident"] = noms
            if not noms:
                rap["alertes"].append(
                    "Cloe NON RÉSIDENTE : aucun modèle chargé → chaque appel repart à froid")
        except Exception:  # noqa: BLE001
            rap["cloe_resident"] = "ollama injoignable"

        rap["ok"] = not any(a.startswith(("CECITE", "DIVERGENCE", "SILENCE"))
                            for a in rap["alertes"])
        try:
            OUT.write_text(json.dumps(rap, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        for a in rap["alertes"]:
            (logger.warning if a[:1].isupper() and a.split()[0].isupper()
             else logger.info)("[SENTINELLE] %s", a)
    except Exception as exc:  # noqa: BLE001 — une sentinelle ne casse jamais son hôte
        rap["erreur"] = repr(exc)
    return rap


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    r = check(int(sys.argv[1]) if len(sys.argv) > 1 else 30)
    print(f"SENTINELLE — fenêtre {r['fenetre_min']} min — "
          f"{'✅ vision claire' if r.get('ok') else '⚠️ ANOMALIE'}")
    for kind in ("fill", "ghost"):
        b = r.get(kind) or {}
        if not b.get("n"):
            continue
        print(f"\n  {kind.upper()} ({b['n']} évén.)")
        for organe, taux in sorted(b["organes"].items(), key=lambda x: x[1]):
            etat = "AVEUGLE" if taux < SEUIL_CECITE else ("partiel" if taux < SEUIL_PARTIEL else "ok")
            print(f"    {organe:20s} {taux:6.0%}  {etat}")
    print("\n  Cloe résidente :", r.get("cloe_resident"))
    if r["alertes"]:
        print("\n  ALERTES :")
        for a in r["alertes"]:
            print("   -", a)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
