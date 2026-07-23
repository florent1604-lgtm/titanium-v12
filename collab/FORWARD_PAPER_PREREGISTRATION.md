# Pré-enregistrement — forward-paper gelé XRP/LINK intraday

**Figé le 2026-07-16 par Claude, en binôme avec Codex (red-team), arbitre Florent.**

> Ce document est une **hypothèse immuable**. On le fige AVANT tout trade forward
> pour que le test soit honnête : personne ne pourra dire que la config a été
> choisie après avoir vu les résultats. Toute modification = un NOUVEAU
> pré-enregistrement daté, pas une réécriture.

## Statut honnête (ce qu'on teste et ce qu'on ne prétend PAS)

- XRP/LINK sont des **candidats DIAGNOSTIQUES, PAS validés** (Codex, 16/07).
- L'analyse historique est **entachée de biais** : les 3 actifs ont été choisis
  après avoir vu le run complet ; la régression alpha était conditionnelle et
  mal spécifiée ; le test 70/30 n'est pas un vrai OOS.
- Le label « vrai alpha » est **retiré**. Les shorts gagnants ne prouvent pas un
  alpha (peut être du beta baissier).
- **Seul le forward-paper produit de la donnée intacte.** C'est lui qui juge.

## Config GELÉE (identique pour les 2 actifs, non ré-optimisable)

| Paramètre | Valeur |
|---|---|
| Actifs | `XRPUSDT`, `LINKUSDT` (Binance spot) |
| Venue | **Binance** (là où l'edge a été mesuré ; PAS Axi démo — coûts différents) |
| Timeframe | H1 (bougie clôturée) |
| Signal | `entries(align_ema50=True, rsi_gate=True)` (EMA200 + TRIX, variant v0/v1) |
| SL | `1.5 × ATR` |
| TP ladder | `(1.5, 2.5, 4.0) × ATR` |
| Time-stop | `48` barres H1 |
| Coûts | maker RT **15 bps** (7.5/côté) + spread 1 + slippage 1 = **17 bps** ; scénario taker (22) suivi en parallèle |
| Risque/trade | 7 % (démo) — sizing exact, non en cause |
| Exposition | décalée d'une barre H1 fermée (aucun look-ahead) |

## Métriques de référence (backtest, à battre en forward)

*Backtest config-fixe, historique complet — à titre indicatif, PAS une promesse :*
- XRP : porté par les shorts (longs perdants) ; décorrélé du marché en apparence.
- LINK : deux côtés positifs, shorts plus forts.
- **Aucun ne passe le DSR** (trop peu de trades : ~25/an) → c'est précisément
  pourquoi on forward-teste au lieu de conclure.

## Critère de décision (fixé d'avance)

- **Fenêtre** : ≥ 3 mois de forward OU ≥ 40 trades par actif (le premier atteint).
- **Promotion vers micro-lots réels** : UNIQUEMENT si, à la fois,
  (a) le forward-paper reste positif net de coûts sur la fenêtre, ET
  (b) l'analyse historique corrigée (calendrier complet, facteur BTC, t-stats
  Newey-West, DSR sur ≥ 10 actifs × 108 configs pour la multiplicité) confirme un
  alpha dont l'IC95 exclut 0. **Sinon : abandon, sans regret.**
- Décision finale : **Florent**, sur avis conjoint Claude + Codex.

## Traçabilité

- Outils : `tools/binance_history.py`, `tools/asset_optimizer_m2.py` (moteur),
  `tools/intraday_basket.py`, `tools/intraday_oos.py`, `tools/beta_isolation.py`
  (ce dernier À CORRIGER selon P0 Codex avant toute interprétation d'alpha).
- Chaque trade forward journalisé (venue, prix, coût, émotion observée).
- Bus : tâche `INTRADAY_BASKET` / `FORWARD_PAPER`.
