# Calibration Binance M2 — conception

## Objectif

Tester la thèse scalping sur Binance Spot avec exactement le harnais statistique
M2/DSR de Titanium, sans ordre, sans clé privée et sans modification de la
configuration de production. La comparaison primaire porte sur le mode
d'exécution, car les commissions Binance dominent le spread sur les cryptos
liquides.

## Périmètre figé

- Source : bougies publiques Binance Spot via `tools/binance_history.py`.
- Actifs : `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `XRPUSDT`, `DOGEUSDT`, `ADAUSDT`,
  `BNBUSDT`, `AVAXUSDT`, `LINKUSDT`, `LTCUSDT`.
- Timeframes et styles : M15/scalp, H1/intraday, H4/swing, mêmes signaux,
  mêmes 108 candidats et mêmes gates M2 que `tools/asset_optimizer_m2.py`.
- Fenêtre : intersection commune M15/H1/H4, minimum 730 jours, split verrouillé
  50 % développement / 20 % sélection / 30 % final.
- Scénarios de coûts : TAKER et MAKER calculés sur les mêmes bougies.
- Sortie isolée : `data/calibration_binance_2026-07-16`, jamais
  `data/asset_configs.json`.

## Modèle de coûts

`binance_cost_model()` expose une commission **par côté**, tandis que
`CostModel.commission_bps` représente le coût total soustrait une seule fois
par trade. Le driver convertit donc explicitement :

- TAKER : 10 bps/côté → 20 bps aller-retour ;
- MAKER : 7,5 bps/côté → 15 bps aller-retour ;
- spread observé : 1 bps, stressé par défaut à ×1,25 ;
- slippage : 1 bps ;
- Spot : swap et funding égaux à zéro, avec l'hypothèse inscrite dans chaque
  snapshot.

Le coût d'exécution attendu par trade est donc 22,25 bps en TAKER et 17,25 bps
en MAKER avec le stress par défaut.

## Architecture

Créer `tools/binance_optimizer_m2.py`, un driver data-only frère de
`asset_optimizer_m2.py`. Il charge et met en cache les trois timeframes une
seule fois par symbole, retire toute bougie encore ouverte, construit un
`CostModel` spot par scénario, puis appelle `_calibrate_style` sans modifier le
harnais statistique existant. Les résultats sont écrits atomiquement par
couple symbole/scénario et résumés sans identifiant de compte MT5.

Le probe `tools/binance_scalp_probe.py` reste diagnostic et ne doit fournir
aucun verdict tant que son coût aller-retour n'est pas corrigé. Le run M2 est
la seule source de décision.

## V2 régime adaptatif

V2 est approuvé comme deuxième famille : suivi de tendance lorsque ADX ≥ 25,
réversion Bollinger lorsque ADX < 20. Il sera pré-enregistré séparément après
le câblage Binance de base. Ses résultats historiques resteront exploratoires
tant que sa multiplicité n'est pas combinée avec celle de la famille de base ;
aucun résultat V2 ne pourra être promu directement en production.

## Sécurité et critères de fin

- Aucun appel `order_send`, `order_check` ou terminal MT5.
- Réseau public en lecture seule ; aucune clé Binance.
- Deux scénarios obligatoires sur les mêmes timestamps.
- Tests sans réseau avec injecteur de données.
- Toute promotion reste `PROPOSAL_ONLY` et exige Claude + Florent.
- Un résultat positif n'est pas une garantie de rentabilité : seuls les gates
  M2 complets peuvent autoriser une phase de forward PAPER.

