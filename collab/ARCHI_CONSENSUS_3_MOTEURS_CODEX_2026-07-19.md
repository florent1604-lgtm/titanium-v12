# Consensus 3 moteurs — architecture Codex (détection seule)

Statut : **PAPER/DEMO ONLY**, observation pré-M2. Ce module n'émet aucune décision de
trading, ne place aucun ordre et ne modifie aucun flag d'exécution.

## But

Pour chaque symbole MT5 suivi par la confluence, recalculer sur les mêmes bougies
clôturées :

1. la sortie CONFLUENCE (5 piliers SMC, mode détection) ;
2. le SCORING `/16` via `core.scoring_engine.score_setup` ;
3. l'ÉMOTION via `emotion.market_context.emotion_for`.

Le résultat expose un `consensus_score` signé dans `[-100, +100]`, un côté, la
couverture, les moteurs en accord et les conflits. Il reste descriptif : aucun seuil
ne doit être consommé par l'exécuteur avant protocole M2 et go explicite de Florent.

## Mapping symbole

Le symbole canonique de sortie reste le symbole MT5. Les crypto CFD sont traduits vers
le format Binance pour les moteurs qui l'attendent : `BTCUSD -> BTC/USDT`,
`ETHUSD -> ETH/USDT`, etc. Les CFD non crypto restent inchangés. Le mapping est
explicite et fail-closed pour éviter de transformer arbitrairement `EURUSD` en crypto.

## Anti-double-comptage

Les indicateurs bruts ne sont jamais additionnés. Ils sont rabattus dans cinq familles
orthogonales, chacune plafonnée à une contribution :

| Famille | Poids | CONFLUENCE | SCORING | ÉMOTION |
|---|---:|---|---|---|
| structure | 0,30 | trend/SR | EMA200, BOS H2/H1, daily | — |
| location_liquidity | 0,25 | VPOC, liquidité, OTE | OB/FVG, sweep, displacement | — |
| timing | 0,15 | bougie confirmée | rejet, TRIX, RSI divergence | — |
| participation_regime | 0,15 | — | ADX, delta/volume, L2 | arousal |
| behavioral | 0,15 | — | — | valence, filtre/contrarian |

Dans une famille, chaque moteur produit au plus un vote directionnel `-1/0/+1`.
Les doublons corrélés (`liquidité/FVG`, `RSI/ADX`, chandeliers/momentum, volume/arousal)
sont donc moyennés/plafonnés dans leur famille au lieu de créer plusieurs points.
Une famille n'apporte la totalité de son poids que lorsque plusieurs moteurs
indépendants concordent ; un moteur seul apporte une preuve partielle.

Le score signé est la somme normalisée des contributions disponibles. La couverture
est publiée séparément pour empêcher un score fort sur peu de données d'être confondu
avec une confirmation robuste.

## Accord, conflit et gardes statistiques

- `CONFIRMED` : au moins deux moteurs directionnels indépendants alignés, aucune
  opposition et couverture suffisante. Un vote moteur n'est qualifié qu'à partir de
  4/5 piliers avec `trend_sr` pour CONFLUENCE, de 8/16 pour SCORING, ou d'une émotion
  actionnable/non stale pour ÉMOTION. Cela reste une étiquette d'observation.
- `CONFLICT` : au moins un vote long et un vote short entre moteurs ou familles.
- `UNCONFIRMED` : une direction existe mais la redondance indépendante manque.
- `INSUFFICIENT` : données invalides ou aucun moteur directionnel exploitable.

Les sorties incluent `m2_required=true`, `decision_capability=false` et
`orders_capability=false`. La boucle isole les erreurs par actif, garde un heartbeat et
conserve un historique borné. La route `GET /consensus/status` ne fait que lire ce
cache.

## Exécution et coût

Le scanner est une tâche autonome FastAPI, activée seulement lorsque l'univers
CONFLUENCE démo/crypto existe déjà. Il reprend la même cadence et la même rotation CFD,
et scanne les crypto à chaque cycle. Les appels bloquants MT5/émotion sont déportés hors
de la boucle asyncio. Aucun résultat n'est injecté dans CONFLUENCE, SCORING, l'exécuteur
ou les flags.

## Validation exigée

Tests unitaires : mapping, score plafonné par famille, conflit, données insuffisantes,
scan fail-safe, statut read-only et contrat de route. Puis tests ciblés avec
`.pyembed/python.exe -m pytest` et contrôle GitNexus `detect_changes` avant handoff.
