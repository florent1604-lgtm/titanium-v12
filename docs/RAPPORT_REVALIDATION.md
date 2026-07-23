# Re-validation tester natif MT5 — top 5 configs par actif

*Généré le 2026-07-08 · EA TitaniumV3 (align/RSI paramétrables) · Strategy Tester
natif · fills réels Axi (spreads + swaps) · période 2023.01 → 2026.07 (3,5 ans, H4)*

## Pourquoi

Le moteur inversé (`tools/asset_optimizer.py`) a classé ~140 actifs par potentiel
sur un backtest Python (walk-forward OOS). Avant tout capital, on re-valide le
**top 5** sur le **tester natif MT5**, qui modélise l'exécution réelle du compte
Axi (spreads variables, swaps, slippage, timing des ordres). C'est le juge de paix.

## Résultat

| Actif | Config (swing H4) | Profit net | PF natif | Sharpe | WR% | DD% | PF Python (OOS) | Verdict |
|-------|-------------------|-----------:|---------:|-------:|----:|----:|----------------:|---------|
| **USTECH** | SL×2.5 · TP 3.45/5.75/9.2 · align off | **+9 350 €** | 1.66 | 2.30 | 53.6 | 15.3 | 2.30 | ✅ **validé, robuste** |
| **NAS100.fs** | SL×2.5 · TP 3.45/5.75/9.2 · align off | **+3 249 €** | 1.84 | 2.50 | 65.9 | 7.2 | 2.12 | ✅ **validé, robuste** |
| **HSI.fs** | SL×3.0 · TP 1.5/3.0/5.0 · align on | +383 € | 1.22 | 0.75 | 82.0 | 7.0 | 2.34 | ✅ validé (modeste) |
| **XAUEUR** | SL×2.5 · TP 2.0/3.5/6.0 · align on | +265 € | 1.10 | 0.44 | 66.7 | 7.9 | 2.00 | ⚠️ marginal (PF≈1.1) |
| **XAUUSD** | SL×3.5 · TP 2.55/4.25/6.8 · align off | **−349 €** | 0.90 | −0.44 | 63.6 | 10.0 | 2.31 | ❌ **rejeté sur fills réels** |

Rapports HTML complets : `docs/mt5_opt_reports/TitaniumOpt_*.html`.

## Lecture

- **Les indices actions US (USTECH, NAS100) sont le vrai gisement.** +9 350 € et
  +3 249 € sur 3,5 ans, PF 1.66–1.84, **Sharpe 2.3–2.5**, drawdown maîtrisé. Ils
  tiennent sous exécution réelle — c'est le résultat le plus solide de tout le projet.
- **HSI (Hang Seng) valide** aussi, plus modestement (PF 1.22, WR 82 %).
- **L'or optimisé ne survit PAS.** XAUUSD swing SL×3.5 affichait PF 2.31 sur la
  fenêtre OOS Python mais fait **−349 € (PF 0.90)** sur 3,5 ans de fills réels :
  la fenêtre OOS récente (bull run or 2024-25) flattait la config ; sur le cycle
  complet, spreads + swaps XAU (~1.4 bps/nuit) mangent l'edge. XAUEUR est à la
  limite (PF 1.10). *À noter :* l'or reste rentable sur la config V3 H1 d'origine
  (XAUUSD +387 € PF 1.18 dans `RAPPORT_MT5_BACKTEST.md`) — c'est la variante swing
  SL large qui est overfittée, pas l'or en soi.

## Conclusion

**Validés pour un forward paper : USTECH, NAS100, HSI** (indices swing H4).
À surveiller : XAUEUR (marginal). **Écarté : XAUUSD swing** (garder l'or sur V3 H1).

La divergence backtest Python ↔ fills réels (or : PF 2.31 → 0.90) est LA
démonstration qu'il ne faut jamais trader une config sur le seul backtest
optimisé. Prochaine étape possible : forward paper H4 sur USTECH/NAS100/HSI,
puis démo, puis micro-lots — sur décision explicite.
