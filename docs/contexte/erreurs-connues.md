# Erreurs connues (pièges)

## Titanium ne redémarre pas
- **Se produit quand :** le port Uvicorn est occupé sous Windows.
- **Cause réelle :** un listener local bloque le bind ; `SO_REUSEADDR` peut donner un faux positif.
- **Solution :** laisser `main.py` vérifier/libérer le listener ; ne pas tuer une connexion sortante vers ce port.

## JARVIS semble vivant mais ne répond plus
- **Se produit quand :** sa console cp1252 reçoit de l’Unicode via `print()`.
- **Cause réelle :** la thread voix s’arrête alors que le WebSocket reste ouvert.
- **Solution :** conserver la configuration UTF-8 documentée dans `CLAUDE.md` et vérifier la thread voix.

## Dashboard JARVIS en reconnexion
- **Se produit quand :** il est servi depuis 5173.
- **Cause réelle :** ses appels relatifs/WebSocket visent Titanium sur 8090.
- **Solution :** charger `http://localhost:8090`.

## Documentation et code divergent
- **Se produit quand :** on suit le README ou un ancien schéma.
- **Cause réelle :** ils citent score `/11`, seuil `7` et port `8080`; le code configure 16 critères, seuil 8, et le contexte projet 8090.
- **Solution :** vérifier `utils/config.py` et `CLAUDE.md` avant de changer un seuil ou une URL.

## Scan sans signal
- **Se produit quand :** les fetchs échouent ou que la H4 manque.
- **Cause réelle :** `scan_symbol()` retourne avant le scoring ; les modules optionnels peuvent ne produire qu’un warning.
- **Solution :** contrôler sources et logs avant de modifier le scoring.

## Analyse ou revue trompeuse
- **Se produit quand :** on lit seulement le dernier commit, ou la sortie spectrale non causale.
- **Cause réelle :** le worktree comporte des composants actifs non suivis ; `compute_spectral_features` a du lookahead.
- **Solution :** partir de `git status` et réserver cette sortie à l’instrumentation/validation.

## Choses qui semblent cassées mais sont volontaires
- `TRADING_MODE=live` échoue : aucun exécuteur live n’est implémenté.
- Une guard en erreur bloque : fail-safe voulu.
- Une tâche reste `REVIEW` sans verdict Codex et validation Florent.