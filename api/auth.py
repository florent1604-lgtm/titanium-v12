"""api/auth.py — Garde d'authentification pour les routes de MUTATION sensibles.

Modèle FAIL-CLOSED (audit 10/07/2026, renforcé par la revue Codex) :
  - toute mutation protégée est REFUSÉE par défaut ;
  - elle n'est autorisée que si `ADMIN_TOKEN` est défini (dans .env, jamais en dur)
    ET que la requête présente l'en-tête `X-Admin-Token` correspondant ;
  - comparaison à temps constant (anti-timing) ; le token n'est jamais loggé.

Usage :
    from api.auth import require_admin
    @router.post("/dangereux", dependencies=[Depends(require_admin)])
"""
from __future__ import annotations

import os
import secrets

from fastapi import Header, HTTPException

ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")


async def require_admin(x_admin_token: str = Header(default="")) -> None:
    # Fail-closed : pas de token serveur configuré → tout est refusé.
    if not ADMIN_TOKEN:
        raise HTTPException(status_code=403,
                            detail="Mutation désactivée : ADMIN_TOKEN non configuré côté serveur.")
    if not x_admin_token or not secrets.compare_digest(str(x_admin_token), str(ADMIN_TOKEN)):
        raise HTTPException(status_code=403, detail="Jeton admin invalide ou manquant.")
