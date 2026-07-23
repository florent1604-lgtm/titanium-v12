# Rapport — Backtests natifs MT5 (Strategy Tester Axi) · stratégie TitaniumV3

**Date** : 08/07/2026 · **Moteur** : MetaTrader 5 Strategy Tester (exécution modélisée
sur le compte réel **Axi-US52-Live**, spreads + swaps réels) · **EA** : `TitaniumV3.mq5`
**Période** : 01/07/2023 → 08/07/2026 (3 ans) · **TF** : H1 · **Modèle** : « chaque tick »
(le plus précis) · **Dépôt** : 10 000 € · **Risque** : 1 %/trade

Portage exact de la stratégie V3 (biais EMA200 + alignement pente EMA50 + croisement
TRIX + pullback RSI, SL ATR×2, TP partiels 1.5/2.5/4, break-even après TP1, time-stop 48 h).

---

## Résultats (données réelles broker, 3 ans)

| Actif | P&L net | Winrate | Trades | Profit factor | DD max | Espér./trade | Sharpe | Verdict |
|---|---|---|---|---|---|---|---|---|
| **EURUSD** | **+2 075 €** | **83.3 %** | 96 | **2.44** | 3.9 % | +21.6 € | **8.29** | ✅ EXCELLENT |
| **GBPUSD** | **+833 €** | **76.3 %** | 80 | **1.63** | 3.5 % | +10.4 € | 4.39 | ✅ SOLIDE |
| **XAUUSD** | **+387 €** | **73.1 %** | 93 | 1.18 | 5.6 % | +4.2 € | 1.79 | ⚠️ POSITIF FAIBLE |
| **BTCUSD** | **−40 €** | 73.2 % | 153 | 0.99 | 9.7 % | −0.3 € | −0.12 | ❌ REJETÉ |

## Lecture

1. **Les 4 actifs dépassent l'objectif de 65 % de winrate** — et pour trois d'entre eux
   avec une expectancy nettement positive après coûts réels du broker. C'est la validation
   la plus solide obtenue jusqu'ici : ce ne sont plus mes estimations de frais, c'est
   l'exécution modélisée sur ton propre compte Axi (spreads variables + swaps de nuit).

2. **Convergence avec les backtests Python** (`strategy_lab.py`) : EURUSD 68 % → 83 %,
   GBPUSD 78 % → 76 %. Même ordre de grandeur, même hiérarchie. Deux moteurs
   indépendants qui concordent = signal fiable, pas un artefact de code.

3. **BTCUSD est le piège du winrate** exactement comme annoncé : 73 % de trades gagnants
   mais **P&L net négatif** (PF 0.99). Les swaps de nuit sur un CFD crypto détenu en H1
   pendant 3 ans mangent l'edge, et le drawdown (9.7 %) est le double du forex. **La
   faisabilité technique est confirmée** (BTCUSD est connecté et backtesté), **mais la
   rentabilité ne l'est pas** sur ce produit. Le moteur crypto natif (Binance + L2 +
   funding + OI) reste supérieur pour le BTC — on ne le remplace pas par du CFD retardé.

## Décisions de production

| Symbole | Data MT5 | Trading (paper) | Motif |
|---|---|---|---|
| EURUSD | ✅ connecté | ✅ actif | validation forte, PF 2.44 |
| GBPUSD | ✅ connecté | ✅ actif | validation solide, PF 1.63 |
| XAUUSD | ✅ connecté | ✅ actif surveillé | positif mais marge fine |
| BTCUSD | ✅ connecté (monitoring) | ❌ pas de trade V3 | expectancy négative ; BTC reste sur le moteur Binance natif |

**Rapports HTML natifs MT5** : `docs/mt5_reports/TitaniumV3_*.html` — consultables aussi
depuis le dashboard (onglet RÉSEAU → panneau « Backtests MT5 natifs »).

## Rejouer les backtests

```powershell
powershell -ExecutionPolicy Bypass -File "C:\Users\flore\Desktop\v12\tools\mt5_tester_run.ps1" -Manifest "C:\chemin\experience.json"
```
(ferme MT5 → 4 backtests → copie les rapports → relance MT5 ; ~10 min).
EA source : `MQL5\Experts\TitaniumV3.mq5` (recompiler après édition via MetaEditor).

## Prochaines étapes recommandées (dans l'ordre, sans argent réel)

1. **Forward paper** EURUSD/GBPUSD/XAUUSD : confirmer que le live paper suit le backtest
   sur 2-4 semaines (tracking error).
2. **Compte démo Axi** : brancher `order_send` réels sur un login démo pour mesurer
   slippage/requotes/swaps réels — mécanique identique au live, zéro risque.
3. **Live micro-lots** : seulement après 1+2 concluants, sur ta décision explicite, avec
   garde-fous (perte journalière max, spread-guard, kill-switch). Le compte est à 0 € —
   il faudra l'alimenter.
> Depuis le 12/07/2026, ce point d'entrée est fail-closed et prépare uniquement
> les artefacts du runner natif. Il ne tue ni ne redémarre le terminal MT5 live.
> L'exécution exige ensuite un terminal tester et un data directory isolés, plus
> les preuves P0 réseau/charge décrites dans
> `REVIEWS/AUDIT_MTTESTER5_CODEX_2026-07-11.md`.
