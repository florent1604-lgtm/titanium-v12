# Décisions prises

> Décisions détectées dans le code, les commentaires et les commits récents.

## 2026-07 · Collaboration à revue croisée
- **Décision :** Hermes orchestre, Claude Code implémente/architecture, Codex audite, Florent arbitre.
- **Pourquoi :** `collab/README.md` impose un livrable vérifiable et une revue croisée pour le code trading.
- **Écarté :** boucle de discussion IA↔IA sans tâche ni preuve.
- **Statut :** en vigueur.

## 2026-07 · PAPER ONLY
- **Décision :** `paper` et `disabled` sont les seuls modes exécutables.
- **Pourquoi :** la factory refuse explicitement `live` ; le provider MT5 est data-only.
- **Écarté :** une API Binance/live executor ; elle est signalée comme indisponible.
- **Statut :** en vigueur (`execution/executor.py`, `CLAUDE.md`).

## 2026-07 · Port Titanium 8090
- **Décision :** Titanium utilise 8090 ; JARVIS mobile garde 8080.
- **Pourquoi :** éviter la collision de ports et préserver les appels JARVIS.
- **Écarté :** retour à 8080.
- **Statut :** en vigueur (`CLAUDE.md`, `main.py`).

## 2026-07 · Un seul écrivain d’état
- **Décision :** contrôle de port + écritures atomiques, sans verrou PID dédié.
- **Pourquoi :** le commentaire de `main.py` juge le PID lock fragile après force-kill et redondant.
- **Écarté :** verrou PID séparé.
- **Statut :** en vigueur.

## 2026-07 · Filtres par actif
- **Décision :** certains filtres sont activés/écartés par symbole.
- **Pourquoi :** commentaires de validation walk-forward distincts BTC/PAXG.
- **Écarté :** règle uniforme pour tous les actifs.
- **Statut :** en vigueur (`utils/config.py`).

## 2026-07 · Score et seuils par actif
- **Décision :** le code configure 16 critères, un seuil global de 8 et des overrides BTC=7/PAXG=6.
- **Pourquoi :** configuration centralisée par actif dans `utils/config.py`.
- **Écarté :** appliquer le score /11 et le seuil 7 encore présents dans une partie de la documentation.
- **Statut :** en vigueur dans le code ; documentation à aligner.

## 2026-07 · Spectral en instrumentation prudente
- **Décision :** l’analyse spectrale est exposée ; la documentation indique que la voie non causale ne doit pas autoriser une décision live.
- **Pourquoi :** risque de lookahead.
- **Écarté :** utiliser `filtfilt/hilbert` comme signal causal.
- **Statut :** à valider par walk-forward (`CLAUDE.md`).