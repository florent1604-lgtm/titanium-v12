# Rapport d'optimisation par actif — moteur inversé

*Généré le 2026-07-08 17:18 UTC · données Axi (MT5) · walk-forward 70/30 · verdict OOS après frais réels*

## Méthode
Pour chaque actif on cherche le **style** (scalp M15 / intraday H1 / swing H4) et les **variables** (SL×ATR, ladder TP, filtres align/RSI) qui maximisent la performance. Calibrage sur l'in-sample, **verdict sur l'out-of-sample jamais vue**. Un actif/style n'est *validé* que si l'OOS donne expectancy>0, profit factor>1 et assez de trades. Coûts : spread Axi réel + slippage ; swap appliqué par barre pour le swing.

## Passe 1 — classement de l'univers par potentiel (top 30)

| # | Actif | Cat. | Style | Pot. | OOS exp (bps) | PF | WR% | n |
|---|-------|------|-------|------|---------------|----|-----|---|
| 1 | BNB-USD | CRYPTO | swing | 473.18 | 77.79 | 1.58 | 64.9 | 37 |
| 2 | ETH-JPY | CRYPTO | swing | 451.49 | 125.22 | 1.77 | 69.2 | 13 |
| 3 | XAUGBP | METALS | swing | 373.36 | 79.6 | 2.23 | 72.7 | 22 |
| 4 | XAUAUD | METALS | swing | 368.51 | 72.27 | 2.3 | 65.4 | 26 |
| 5 | XAUEUR | METALS | swing | 357.54 | 70.12 | 2.0 | 69.2 | 26 |
| 6 | USTECH | CASH | swing | 348.3 | 57.26 | 1.89 | 67.6 | 37 |
| 7 | HK50 | CASH | swing | 336.21 | 57.66 | 1.94 | 67.6 | 34 |
| 8 | XAUUSD | METALS | swing | 276.37 | 51.32 | 1.71 | 72.4 | 29 |
| 9 | NAS100.fs | FUTURES | swing | 272.41 | 43.62 | 1.63 | 61.5 | 39 |
| 10 | BTCUSD | CRYPTO | intraday | 263.98 | 51.77 | 2.39 | 73.1 | 26 |
| 11 | ETHUSD | CRYPTO | swing | 198.64 | 49.66 | 1.26 | 62.5 | 16 |
| 12 | HSI.fs | FUTURES | swing | 183.94 | 27.73 | 1.38 | 63.6 | 44 |
| 13 | XAGUSD | METALS | intraday | 181.57 | 22.35 | 1.28 | 68.2 | 66 |
| 14 | USDCOP | FX | swing | 162.25 | 45.0 | 1.68 | 69.2 | 13 |
| 15 | SPA35 | CASH | swing | 150.19 | 27.42 | 1.45 | 63.3 | 30 |
| 16 | USDILS | FX | swing | 148.61 | 26.27 | 1.7 | 71.9 | 32 |
| 17 | UKOIL | CASH | swing | 123.48 | 22.93 | 1.16 | 55.2 | 29 |
| 18 | COFFEE.fs | FUTURES | swing | 107.26 | 15.99 | 1.1 | 62.2 | 45 |
| 19 | DJ30.fs | FUTURES | swing | 104.36 | 26.09 | 1.51 | 62.5 | 16 |
| 20 | USDBRL | FX | swing | 77.89 | 18.36 | 1.39 | 72.2 | 18 |
| 21 | WTI.fs | FUTURES | swing | 76.65 | 12.12 | 1.07 | 52.5 | 40 |
| 22 | US30 | CASH | swing | 73.84 | 11.26 | 1.21 | 53.5 | 43 |
| 23 | IT40 | CASH | swing | 69.64 | 12.31 | 1.22 | 62.5 | 32 |
| 24 | USDCAD | FX | swing | 66.62 | 12.59 | 1.96 | 71.4 | 28 |
| 25 | XLMUSD | CRYPTO | intraday | 62.25 | 6.49 | 1.06 | 57.6 | 92 |
| 26 | USOIL | CASH | swing | 57.97 | 8.84 | 1.07 | 58.1 | 43 |
| 27 | CHFJPY | FX | swing | 54.7 | 14.62 | 1.57 | 57.1 | 14 |
| 28 | NETH25 | CASH | swing | 49.61 | 8.91 | 1.24 | 74.2 | 31 |
| 29 | AUDNZD | FX | swing | 46.88 | 8.16 | 1.47 | 66.7 | 33 |
| 30 | EUSTX50.fs | FUTURES | intraday | 37.68 | 3.95 | 1.15 | 61.5 | 91 |

## Passe 2 — optimisation profonde par actif et par stratégie

### ETHUSD  ·  CRYPTO  (spread 7.21 bps, swap 0.115 bps/j)

| Style | Config | Validé | OOS exp | PF | WR% | n | DD (bps) |
|-------|--------|--------|---------|----|-----|---|----------|
| scalp | SL×1.0 TP[0.92, 1.72, 2.88] a1 r0 | ❌ | -14.02 | 0.57 | 44.0 | 75 | 1102.0 |
| intraday | SL×1.5 TP[2.3, 3.45, 5.75] a1 r1 | ❌ | 78.9 | 2.68 | 69.2 | 13 | 423.0 |
| swing | SL×2.5 TP[3.45, 5.75, 9.2] a0 r1 | ✅ | 175.38 | 1.85 | 56.2 | 16 | 2356.0 |

### BNB-USD  ·  CRYPTO  (spread 17.67 bps, swap 3.535 bps/j)

| Style | Config | Validé | OOS exp | PF | WR% | n | DD (bps) |
|-------|--------|--------|---------|----|-----|---|----------|
| scalp | SL×0.5 TP[1.0, 1.5, 2.5] a1 r0 | ❌ | -23.58 | 0.24 | 22.6 | 62 | 1593.0 |
| intraday | SL×3.0 TP[2.3, 3.45, 5.75] a1 r1 | ❌ | 67.14 | 2.31 | 69.2 | 13 | 460.0 |
| swing | SL×2.5 TP[3.45, 5.75, 9.2] a0 r0 | ✅ | 94.6 | 1.55 | 54.3 | 35 | 2182.0 |

### USTECH  ·  CASH  (spread 0.93 bps, swap 0.023 bps/j)

| Style | Config | Validé | OOS exp | PF | WR% | n | DD (bps) |
|-------|--------|--------|---------|----|-----|---|----------|
| scalp | SL×1.5 TP[1.72, 2.88, 4.6] a0 r1 | ❌ | 0.15 | 1.01 | 39.1 | 23 | 191.0 |
| intraday | SL×1.0 TP[2.3, 3.45, 5.75] a1 r0 | ✅ | 14.81 | 1.69 | 44.9 | 69 | 279.0 |
| swing | SL×2.5 TP[3.45, 5.75, 9.2] a0 r0 | ✅ | 96.83 | 2.3 | 63.6 | 33 | 680.0 |

### XAUUSD  ·  METALS  (spread 0.76 bps, swap 1.436 bps/j)

| Style | Config | Validé | OOS exp | PF | WR% | n | DD (bps) |
|-------|--------|--------|---------|----|-----|---|----------|
| scalp | SL×2.0 TP[1.72, 2.88, 4.6] a1 r0 | ❌ | -0.66 | 0.97 | 52.9 | 68 | 444.0 |
| intraday | SL×3.0 TP[2.3, 3.45, 5.75] a1 r1 | ❌ | -22.01 | 0.69 | 41.7 | 12 | 418.0 |
| swing | SL×3.5 TP[2.55, 4.25, 6.8] a0 r0 | ✅ | 94.49 | 2.31 | 72.7 | 33 | 1308.0 |

### NAS100.fs  ·  FUTURES  (spread 0.85 bps, swap -0.0 bps/j)

| Style | Config | Validé | OOS exp | PF | WR% | n | DD (bps) |
|-------|--------|--------|---------|----|-----|---|----------|
| scalp | SL×1.5 TP[1.72, 2.88, 4.6] a0 r1 | ❌ | -1.73 | 0.91 | 38.5 | 26 | 225.0 |
| intraday | SL×2.5 TP[2.0, 3.0, 5.0] a1 r0 | ✅ | 5.98 | 1.16 | 60.3 | 68 | 527.0 |
| swing | SL×2.5 TP[3.45, 5.75, 9.2] a0 r0 | ✅ | 83.14 | 2.12 | 62.9 | 35 | 943.0 |

### HSI.fs  ·  FUTURES  (spread 4.17 bps, swap -0.0 bps/j)

| Style | Config | Validé | OOS exp | PF | WR% | n | DD (bps) |
|-------|--------|--------|---------|----|-----|---|----------|
| scalp | SL×0.5 TP[1.15, 1.72, 2.88] a1 r0 | ❌ | -4.65 | 0.58 | 32.7 | 52 | 262.0 |
| intraday | SL×2.5 TP[2.0, 3.0, 5.0] a1 r0 | ❌ | -1.86 | 0.96 | 58.2 | 67 | 1015.0 |
| swing | SL×3.0 TP[1.5, 3.0, 5.0] a1 r0 | ✅ | 65.38 | 2.34 | 80.0 | 35 | 615.0 |

### BTCUSD  ·  CRYPTO  (spread 4.36 bps, swap 0.032 bps/j)

| Style | Config | Validé | OOS exp | PF | WR% | n | DD (bps) |
|-------|--------|--------|---------|----|-----|---|----------|
| scalp | SL×2.5 TP[1.72, 2.88, 4.6] a0 r1 | ❌ | -0.96 | 0.96 | 62.1 | 29 | 583.0 |
| intraday | SL×2.0 TP[2.0, 3.0, 5.0] a0 r1 | ✅ | 71.03 | 2.73 | 69.2 | 26 | 406.0 |
| swing | SL×2.5 TP[3.45, 5.75, 9.2] a1 r1 | ❌ | -9.88 | 0.95 | 37.5 | 8 | 890.0 |

### XAUEUR  ·  METALS  (spread 1.41 bps, swap 1.036 bps/j)

| Style | Config | Validé | OOS exp | PF | WR% | n | DD (bps) |
|-------|--------|--------|---------|----|-----|---|----------|
| scalp | SL×1.5 TP[1.27, 2.12, 3.4] a1 r0 | ❌ | -4.3 | 0.76 | 44.8 | 67 | 499.0 |
| intraday | SL×3.0 TP[2.0, 3.0, 5.0] a1 r1 | ❌ | -85.66 | 0.15 | 20.0 | 10 | 919.0 |
| swing | SL×2.5 TP[2.0, 3.5, 6.0] a1 r0 | ✅ | 70.12 | 2.0 | 69.2 | 26 | 944.0 |

### XAUAUD  ·  METALS  (spread 0.99 bps, swap 1.949 bps/j)

| Style | Config | Validé | OOS exp | PF | WR% | n | DD (bps) |
|-------|--------|--------|---------|----|-----|---|----------|
| scalp | SL×2.5 TP[1.0, 1.5, 2.5] a1 r0 | ✅ | 2.23 | 1.18 | 71.6 | 67 | 195.0 |
| intraday | SL×3.0 TP[2.3, 3.45, 5.75] a1 r0 | ✅ | 13.87 | 1.3 | 60.7 | 56 | 420.0 |
| swing | SL×2.5 TP[1.72, 3.45, 5.75] a1 r0 | ✅ | 43.81 | 1.84 | 71.4 | 28 | 391.0 |

### XAUGBP  ·  METALS  (spread 1.29 bps, swap 1.521 bps/j)

| Style | Config | Validé | OOS exp | PF | WR% | n | DD (bps) |
|-------|--------|--------|---------|----|-----|---|----------|
| scalp | SL×2.0 TP[1.0, 1.5, 2.5] a1 r1 | ❌ | -9.48 | 0.48 | 46.2 | 13 | 202.0 |
| intraday | SL×2.0 TP[2.3, 3.45, 5.75] a1 r0 | ✅ | 5.91 | 1.13 | 45.9 | 74 | 640.0 |
| swing | SL×2.0 TP[1.27, 2.55, 4.25] a1 r0 | ✅ | 43.91 | 2.05 | 78.3 | 23 | 488.0 |

### HK50  ·  CASH  (spread 2.5 bps, swap 0.031 bps/j)

| Style | Config | Validé | OOS exp | PF | WR% | n | DD (bps) |
|-------|--------|--------|---------|----|-----|---|----------|
| scalp | SL×0.5 TP[1.72, 2.88, 4.6] a1 r0 | ❌ | -0.01 | 1.0 | 30.8 | 52 | 177.0 |
| intraday | SL×2.0 TP[2.3, 3.45, 5.75] a1 r1 | ❌ | 28.9 | 2.41 | 66.7 | 9 | 185.0 |
| swing | SL×1.5 TP[3.0, 5.0, 8.0] a0 r0 | ✅ | 30.76 | 1.43 | 40.9 | 44 | 790.0 |

### XAGUSD  ·  METALS  (spread 7.77 bps, swap 2.278 bps/j)

| Style | Config | Validé | OOS exp | PF | WR% | n | DD (bps) |
|-------|--------|--------|---------|----|-----|---|----------|
| scalp | SL×1.5 TP[1.72, 2.88, 4.6] a1 r0 | ❌ | -32.44 | 0.45 | 33.3 | 69 | 2482.0 |
| intraday | SL×2.0 TP[1.5, 2.5, 4.0] a1 r0 | ✅ | 22.35 | 1.28 | 68.2 | 66 | 1141.0 |
| swing | SL×2.5 TP[1.5, 3.0, 5.0] a0 r0 | ❌ | -21.7 | 0.88 | 69.2 | 39 | 3953.0 |

### USDCOP  ·  FX  (spread 15.41 bps, swap 0.026 bps/j)

| Style | Config | Validé | OOS exp | PF | WR% | n | DD (bps) |
|-------|--------|--------|---------|----|-----|---|----------|
| scalp | SL×2.0 TP[1.72, 2.88, 4.6] a0 r1 | ❌ | -0.69 | 0.97 | 66.7 | 21 | 226.0 |
| intraday | SL×1.5 TP[2.3, 3.45, 5.75] a0 r0 | ❌ | -24.85 | 0.61 | 38.5 | 78 | 2702.0 |
| swing | SL×2.5 TP[1.5, 3.0, 5.0] a0 r1 | ✅ | 38.04 | 1.79 | 78.6 | 14 | 337.0 |

### SPA35  ·  CASH  (spread 6.26 bps, swap 0.027 bps/j)

| Style | Config | Validé | OOS exp | PF | WR% | n | DD (bps) |
|-------|--------|--------|---------|----|-----|---|----------|
| scalp | SL×1.5 TP[1.72, 2.88, 4.6] a0 r1 | ❌ | -16.72 | 0.31 | 38.5 | 26 | 340.0 |
| intraday | SL×1.0 TP[1.5, 2.5, 4.0] a1 r1 | ❌ | -18.92 | 0.22 | 57.1 | 7 | 94.0 |
| swing | SL×3.5 TP[2.3, 4.02, 6.9] a1 r0 | ✅ | 22.77 | 1.28 | 63.0 | 27 | 637.0 |

### ETH-JPY  ·  CRYPTO  (spread 14.73 bps, swap 0.532 bps/j)

| Style | Config | Validé | OOS exp | PF | WR% | n | DD (bps) |
|-------|--------|--------|---------|----|-----|---|----------|
| scalp | SL×2.5 TP[1.72, 2.88, 4.6] a0 r1 | ❌ | -29.63 | 0.42 | 37.5 | 24 | 835.0 |
| intraday | SL×2.0 TP[1.0, 2.0, 3.5] a0 r1 | ❌ | -75.51 | 0.22 | 39.4 | 33 | 2752.0 |
| swing | SL×3.0 TP[3.0, 5.0, 8.0] a1 r0 | ❌ | -181.69 | 0.53 | 32.0 | 25 | 5663.0 |

## Configuration live retenue (data/asset_configs.json)

| Actif | Style | TF | SL×ATR | TP ladder | Pot. |
|-------|-------|----|--------|-----------|------|
| ETHUSD | swing | H4 | 2.5 | [3.45, 5.75, 9.2] | 701.52 |
| BNB-USD | swing | H4 | 2.5 | [3.45, 5.75, 9.2] | 559.66 |
| USTECH | swing | H4 | 2.5 | [3.45, 5.75, 9.2] | 556.25 |
| XAUUSD | swing | H4 | 3.5 | [2.55, 4.25, 6.8] | 542.8 |
| NAS100.fs | swing | H4 | 2.5 | [3.45, 5.75, 9.2] | 491.86 |
| HSI.fs | swing | H4 | 3.0 | [1.5, 3.0, 5.0] | 386.79 |
| BTCUSD | intraday | H1 | 2.0 | [2.0, 3.0, 5.0] | 362.18 |
| XAUEUR | swing | H4 | 2.5 | [2.0, 3.5, 6.0] | 357.54 |
| XAUAUD | swing | H4 | 2.5 | [1.72, 3.45, 5.75] | 231.82 |
| XAUGBP | swing | H4 | 2.0 | [1.27, 2.55, 4.25] | 210.58 |
| HK50 | swing | H4 | 1.5 | [3.0, 5.0, 8.0] | 204.04 |
| XAGUSD | intraday | H1 | 2.0 | [1.5, 2.5, 4.0] | 181.57 |
| USDCOP | swing | H4 | 2.5 | [1.5, 3.0, 5.0] | 142.33 |
| SPA35 | swing | H4 | 3.5 | [2.3, 4.02, 6.9] | 118.32 |

---
*MT5 = données seulement, compte Axi live intouché. Ces résultats sont paper/backtest ; passage à l'écriture réelle = séquence forward → démo → micro-lots, sur décision explicite.*