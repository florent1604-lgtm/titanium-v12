# Rapport — Campagne de calibrage scalping multi-TF (30/15/5 min)

**Date** : 08/07/2026 · **Outil** : `tools/scalp_lab.py` · **Données** : 180 jours,
Binance 5 m (BTC/ETH/PAXG) + MT5-Axi M5 (EURUSD/GBPUSD/XAUUSD)
**Objectif fixé** : winrate ≥ 65 % minimum, calibrage indépendant par actif.
**Garde-fous** : split 70 % in-sample / 30 % out-of-sample ; validation = winrate OOS ≥ 65 %
**ET** expectancy après frais > 0 **ET** ≥ 15 trades OOS. Frais aller-retour inclus :
11 bps crypto, 1.5 bps forex, 4 bps or.

---

## 1. Ce qui a été testé (la boucle de recalibrage)

- **Méthode** : contexte 30 m (biais EMA200, pente EMA50) → déclencheur 5 m puis 15 m
  (E1 pullback RSI, E2 croisement TRIX, E3 réversion Bollinger) → SL ATR×p,
  TP partiels 33/33/34, break-even après TP1, time-stop 8 h, anti-rafale 30 min.
- **Boucle** : étage 1 (grille standard) → étage 2 (profils haute-winrate : TP1 court,
  SL large) → étage 3 (déclencheur remonté à 15 m + filtre session Londres/NY 07-17 UTC
  pour le forex). ≈ **600 backtests** au total, calibrage séparé pour chacun des 6 actifs.

## 2. Résultat : aucun actif ne valide le scalping

| Actif | Meilleur OOS (déclencheur 5 m) | Meilleur OOS (déclencheur 15 m) | Verdict |
|---|---|---|---|
| BTC | 35.7 % WR, −11.5 bps/trade | 46.8 % WR, −11.9 bps | ❌ |
| ETH | 39.1 % WR, −14.3 bps | 68.5 % WR, **+0.4 bps** ⚠️ faux positif¹ | ❌ |
| PAXG | 14.7 % WR, −11.4 bps | 21.4 % WR, −26.0 bps | ❌ |
| EURUSD | 29.3 % WR, −2.1 bps | 70 % WR, +1.2 bps ⚠️ 10 trades² | ❌ (échantillon) |
| GBPUSD | 43.5 % WR, −1.9 bps | 25.0 % WR, −3.5 bps | ❌ |
| XAUUSD | 48.7 % WR, −7.1 bps | 54.5 % WR, −1.2 bps | ❌ |

¹ ETH 15 m a techniquement passé le seuil (68.5 % WR, expectancy +0.4 bps) mais la même
config **perdait −11.7 bps in-sample** : un edge réel ne s'inverse pas entre IS et OOS.
C'est du bruit statistique — rejeté volontairement plutôt que déployé.
² EURUSD 15 m en session Londres/NY : 70 % WR, PF 2.02 — mais **10 trades seulement**
en OOS. Piste intéressante, échantillon insuffisant pour conclure.

## 3. Pourquoi le scalping ne peut pas marcher ici (cause structurelle)

Part du TP1 (1×ATR) consommée par les frais aller-retour :

| Actif | ATR 5 m | ATR 15 m | Frais RT | Frais/TP1 en 5 m | en 15 m |
|---|---|---|---|---|---|
| BTC | 15.3 bps | 29.6 bps | 11 bps | **72 %** | 37 % |
| ETH | 20.3 bps | 39.0 bps | 11 bps | **54 %** | 28 % |
| PAXG | 8.1 bps | 16.4 bps | 11 bps | **136 %** 🔴 | 67 % |
| EURUSD | 2.7 bps | 4.8 bps | 1.5 bps | 56 % | 31 % |
| GBPUSD | 3.2 bps | 5.7 bps | 1.5 bps | 47 % | 26 % |
| XAUUSD | 12.1 bps | 21.6 bps | 4 bps | 33 % | 18 % |

Quand les frais absorbent un tiers à la totalité du premier objectif, il faudrait un
winrate irréaliste pour compenser. Ce n'est pas un problème de calibrage : c'est de
l'arithmétique. **Continuer la boucle produirait uniquement de l'overfitting** (on peut
toujours fabriquer 65 % de winrate in-sample ; il s'écroule systématiquement en OOS —
c'est exactement ce que la campagne a montré).

## 4. L'objectif 65 % est déjà atteint — mais en H1

Rappel du backtest 365 j du 08/07 (`tools/strategy_lab.py`), stratégie **V3** (alignement
EMA200 + pente EMA50, SL ATR×2, TP 1.5/2.5/4) :

| Actif | Winrate | Profit factor | Expectancy |
|---|---|---|---|
| **GBPUSD (H1)** | **78.3 %** ✅ | 2.02 | +5.7 bps |
| **EURUSD (H1)** | **68.4 %** ✅ | 1.80 | +6.7 bps |
| ETH (H1, V3) | 69.6 % ✅ | 1.02 | +1.5 bps (faible) |
| BTC (H1, V3) | 59.1 % | 1.59 | +31.1 bps |

Le cahier des charges (≥ 65 % winrate) est satisfait par la stratégie **déjà déployée**
dans le moteur forex MT5-Axi (paper) — sur l'horizon H1, pas en scalping.

## 5. Décisions et recommandations

1. **Ne pas déployer de scalping 5 m/15 m** — aucun calibrage validé, cause structurelle.
2. **Conserver V3 H1** sur EURUSD/GBPUSD/XAUUSD (moteur forex paper en cours de forward-test).
3. Si le scalping reste un objectif, les deux seuls leviers réels sont :
   - **réduire les frais crypto** : ordres maker (limit) ≈ −7 bps, payer les frais en BNB
     (−25 %), — à ~4 bps RT, BTC 15 m redevient jouable ;
   - **approfondir la piste EURUSD 15 m session Londres/NY** avec 2-3 ans d'historique M15
     MT5 pour porter l'échantillon OOS à 50+ trades. Je peux lancer cette étude sur demande.
4. Le lab est rejouable et extensible : `venv\Scripts\python.exe tools\scalp_lab.py [--tf15]`.

**Artefacts** : `data/scalp_calibration.json` (détail des ~600 runs),
`data/strategy_lab_report.json` (campagne H1), ce rapport.
