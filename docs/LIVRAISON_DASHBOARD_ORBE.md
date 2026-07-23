# Livraison — Cockpit ORBE JARVIS/Hermes (dashboard Titanium v12)

*Livré le 2026-07-11. Interface par défaut du bot. Vérifiée end-to-end (Playwright).*

## Accès

| URL | Contenu |
|-----|---------|
| `http://localhost:8090/` | **Cockpit ORBE** (interface livrée) — s'affiche aussi dans la fenêtre JARVIS |
| `http://localhost:8090/classic` | Ancien dashboard v12 (préservé, réversible) |
| `http://localhost:8090/orbe` | Même cockpit (route dédiée conservée) |

## Ce que l'interface fait

- **Orbe JARVIS plein écran** (canvas 2D, portage de `frontend/src/orb.ts`, zéro CDN) :
  nuage de particules vivant — repos / réflexion (pendant les rafraîchissements) /
  parole (WS JARVIS 8765) — qui **se teinte** cyan→ambre→rouge selon la santé réelle.
- **Mode RÉSEAU NEURONAL** (bouton) : graphe d'appels RÉEL du bot depuis le registre
  **GitNexus** (`GET /orbe/map`, 180 symboles / 205 axones ; repli AST hors-ligne),
  neurones colorés par couche, hubs étiquetés, **influx lumineux** sur les modules
  actifs (deltas `scan_count`/`trades`/`equity` entre cycles). Survol = type + fichier
  + connexions.
- **HUD** : équité totale, heure UTC, ratio gross/plafond ; badges FLUX/MT5/HERMES.
- **3 widgets moteurs séparés** (swing/forex/crypto) avec statut LIVE/STALE/INDISPONIBLE
  par flux, positions et P&L ; **anneau R3** (jauges gross/net + clusters saturés en
  rouge) ; **journal** fusionné des 3 moteurs ; **sous-titres** typés annonçant le
  dernier trade. Badge **PAPER ONLY** permanent.
- **Fail-visible** : toute donnée absente/périmée est barrée/rouge, jamais un chiffre
  rassurant (règle Hermes). Aucune mutation depuis la page, aucun token stocké.

## Routes API ajoutées

- `GET /orbe`, `GET /` → cockpit ; `GET /classic` → ancien dashboard.
- `GET /orbe/map` → topologie (registre GitNexus, repli AST). Regénérer :
  `venv\Scripts\python.exe tools\gen_neural_map.py`.
- `GET /swing/risk/exposure` → snapshot risque R3 (lecture seule) pour l'anneau.

## Sécurité (inchangée, volontairement)

Bind `127.0.0.1`, auth fail-closed `ADMIN_TOKEN` sur toute mutation, **paper-only**,
MT5 données-seulement. L'interface est en lecture seule : elle n'expose aucun ordre.

## Vérification

- 36/36 tests verts (`portfolio_risk` + `bar_dedup` + `atomic_state` + `paper_trading`).
- Rendu testé au navigateur (Playwright) : 2 modes OK, données live, seule erreur
  console = WS JARVIS 8765 quand JARVIS n'est pas lancé (géré : badge HORS LIGNE +
  reconnexion auto).

## Réversibilité

Revenir à l'ancien dashboard par défaut = remettre `_DASHBOARD_HTML` dans la route `/`
de `api/api_server.py` (une ligne). Fichiers conservés : `titanium_v12_dashboard.html`,
`titanium_orbe_v1.html` (première version de l'orbe).
