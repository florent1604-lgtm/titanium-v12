# Mémoire de Cloe — 2026-07-29T11:45:07.281737+00:00

# MÉMOIRE DE CLOE (brief)

## Identité
- role: Analyste quant du bot Titanium. Je PROPOSE, Florent valide, le moteur deterministe decide (jamais je ne declenche un ordre). Local uniquement (Ollama), aucune API commerciale.
- contraintes: Compte DEMO uniquement. Rien de perso ne sort. Le noyau de decision reste 100% deterministe (test du fil debranche).

## Architecture
- pyramide: N1 ingestion/market -> N2 poles/{smc,spectral(geometrix),fundamentals,emotion,vision} -> N3 fusion -> N4 risk/riskgate (porte unique) -> N5 execution. N6 feedback. Socle N0 core/{state,journal,config,flux,cloe}.
- organes_cles: SystemState=etat partage; journal non censure=signal/decision/fill/ghost; core/flux=fondamentaux/cout/exposition continus; /health=sante live.

## Ce que j'ai appris (findings)
- crypto_saigne: Le crypto fait ~70% de la perte (winrate 10%, spreads demo enormes). A couper/reduire.
- sizing_piliers_inverse: Plus de piliers = PIRE (S/2p -0.5R, M/3p -0.9R, L/4p -3.3R). Le sizing plus-de-piliers=plus-gros-lot est A INVERSER.
- vetos_protecteurs: Les vetos (COUNTER_TREND_BLOCKED, BRAIN_SIDE_CONFLICT) protegent (rendement des refus ~0/negatif). Le probleme est ce qu on ACCEPTE, pas ce qu on refuse.
- cout_est_le_tueur: Backtest cout-conscient : baseline lot-plein = -88 (PF 0.20, colle au live). Le COUT (spread) tue l edge, pas le sens. Adapter le lot au cout (modele Florent) divise la perte par ~7 (-13, PF 0.48). Ne JAMAIS rejeter sur cout ; adapter le lot.
- encore_negatif: Meme avec lot adapte au cout, la strategie reste negative (PF 0.48). Prochain levier : SELECTIVITE (moins de trades, meilleure qualite) + CIBLES plus larges (laisser courir) pour battre le cout. Le signal brut a un edge mince mais les couts l effacent.

## Directives de Florent
- riskgate_cable: RiskGate cable en veto additif (RISKGATE_ENABLED=1), enrichi par core/flux (fondamentaux/cout/exposition). Filtre cout coupe le crypto a spread enorme.
- laisser_tourner: Florent laisse tourner le demo comme source de donnees; readaptation strategie (sizing inverse + coupe crypto) en attente de son GO.
- modele_cout_tendance_valide: Florent avait raison : cout=propre au broker, on l accepte et on adapte le lot (jamais rejeter). Tendance=orientation + prediction de retournement (geometrix), pas un bloc. Implemente + valide par backtest cout-conscient.

## Dernières analyses
- (2026-07-29T11:45) DEBRIEF LONG sur NZDCAD : 3 piliers [trend_sr, fair_value, liquidity] -> SL PnL=-1.11 | SL touché
- (2026-07-29T11:45) DEBRIEF LONG sur USDCAD : 2 piliers [trend_sr, liquidity] -> SL PnL=-1.35 | SL touché
- (2026-07-29T11:45) DEBRIEF LONG sur EURGBP : 2 piliers [trend_sr, liquidity] -> 1 PnL=0.08 | continuation avec la tendance -> gain
