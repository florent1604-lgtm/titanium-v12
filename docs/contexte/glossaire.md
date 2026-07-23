# Glossaire et entités

## Termes du domaine
- **Signal** → proposition `ACHAT`, `VENTE` ou neutre, issue du score et enrichie de contexte/SL/TP.
- **Paper trading** → simulation de positions, frais, spread, slippage, funding et sorties partielles.
- **Guard** → contrôle pré-exécution qui accepte ou bloque ; une erreur bloque.
- **Blackout** → période configurée durant laquelle un trade est refusé.
- **Score macro** → risque agrégé issu des flux de news ; il peut réduire ou annuler un signal.
- **Walk-forward** → validation/optimisation séparant données d’apprentissage et hors échantillon.

## Entités principales
- **`PaperPosition`** → position simulée ouverte, avec taille, côté, prix et SL/TP (`execution/paper_trading.py`).
- **`ClosedTrade`** → opération paper finalisée, utilisée dans les statistiques/journaux.
- **`GuardResult`** → résultat `{passed, guard, reason}` des contrôles pré-exécution.
- **`MarketSnapshotAtClose`** → modèle de snapshot marché au moment de clôture (`domain/`).
- **`StrategyInput` / `DecisionIntent`** → entrée et résultat de la décision stratégie (`domain/strategy.py`).

## Sigles et noms internes
- **SMC** → Smart Money Concepts, base du scoring.
- **OB / FVG / BOS** → Order Block / Fair Value Gap / Break of Structure.
- **L2** → carnet d’ordres de profondeur analysé pour imbalance et walls.
- **TRIX** → indicateur recalibré par le moteur strict.
- **MT5** → MetaTrader 5, utilisé ici comme source de données.
- **JARVIS / Titan** → assistant vocal et composants d’assistance reliés à Titanium.
- **Hermes** → orchestrateur/contexte partagé du projet (`collab/README.md`).
- **Claude Code** → agent d’architecture et d’implémentation.
- **Codex** → agent d’audit/red-team et de revue critique.
- **Florent** → arbitre final des décisions et validations.