# Audit du stack de détection d'entrée (Claude, 17/07/2026)

*Audit parallèle à celui de Codex. Objectif : face à la méthode de Florent
(collab/FLORENT_ENTRY_METHOD.md), quelles briques sont solides, faibles, ou absentes.*

## ✅ Présent et SOLIDE (mieux que ce qu'on craignait)

| Brique | Où | État |
|---|---|---|
| SMC : FVG, Order Blocks (+statut), sweep, **sweep+displacement**, BOS | `core/smc_engine.py` | solide |
| Patterns de retournement : inducement→sweep→CHoCH, div. RSI sur OB, score confiance | `fixes/new_reversal_patterns.py` | solide |
| **Order-flow L2** : imbalance, imbalance pondéré, **murs**, **absorption** | `indicators/orderbook.py` | **riche** (crypto/Binance) |
| Momentum/régime : **ADX (régime)**, **RSI + divergence**, TRIX | `indicators/{adx,rsi,trix}.py` | solide |
| **Bougies : 12 familles + signification + biais contextuel** | `core/candlestick_engine.py` | **AJOUTÉ 17/07** (était : 1 seul) |

## ❌ MANQUANT ou trop pauvre (à construire — priorité méthode Florent)

| Brique manquante | Critère Florent | Priorité |
|---|---|---|
| **Profil de volume / VPOC / value area** | n°2 (zones de « juste prix » où le prix revient) | **HAUTE** |
| **Fibonacci OTE** (0.618/0.705/0.786 golden zone, invalidation) | n°4 (point d'entrée optimal confirmé) | **HAUTE** |
| **Niveaux S/R multi-TF explicites** (objets support/résistance, pas juste EMA200) | n°1 (gros niveaux TF hautes) | MOYENNE |

## Constat

Les **fondations sont bonnes** (SMC, order-flow, momentum, et maintenant les
bougies). Ce qui manquait vraiment à la méthode de Florent : **VPOC** et **Fib
OTE** — les deux zones qui définissent *où* il entre. Une fois ces deux briques
posées + des niveaux S/R explicites, **toute la confluence est encodée et testable**.

## Suite

1. Claude : construire **VPOC** (profil de volume → nœuds de juste prix + value area).
2. Claude : construire **Fib OTE** (retracement auto sur swing, golden zone, invalidation).
3. Claude : niveaux S/R explicites (swing highs/lows clusterisés + VPOC).
4. Codex : review candle lib + gap report croisé + optimisation.
5. Puis : **labo de confluence** = croiser tout ça (tendance ∧ VPOC ∧ liquidité/FVG
   ∧ Fib OTE, confirmé bougie, timing émotion) et tester contre coûts, multiplicité
   contrôlée. PAPER ONLY, rien en prod sans M2.
