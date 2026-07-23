# Rapport — Exécution DÉMO MT5 (étape D) & décision de test de Florent

*Rédigé par Claude le 2026-07-13 pour information et revue croisée de Codex
(auditeur/red-team) et Hermes (orchestrateur). Décision produit de Florent :
test d'exécution RÉELLE sur compte DÉMO pour récolter de la data de calibration.*

## 1. Décision de Florent (contexte)

- Florent a ouvert un **compte DÉMO Axi** : `Axi-US50-Demo`, login **50061786**,
  1000 USD (distinct du compte RÉEL `Axi-US52-Live` login 60261188).
- Objectif : **exécuter les signaux du bot en réel sur la démo** pour obtenir de
  la **data de calibration** (winrate réel vs paper, slippage/spread, quels
  actifs tiennent en réel — la leçon XAU PF 2.31 Python → 0.90 natif).
- Choix explicites et informés de Florent (compte démo, il suit sur MT5 iOS) :
  - auto-exécution **continue, sans validation par trade** ;
  - **tous** les déclencheurs positifs : swing validé + actifs auto-intégrés du
    scan d'opportunités (141 actifs MT5) + forex (pas seulement forex) ;
  - **pas de plafond fixe** de positions → limité par la **marge disponible** ;
  - **risque augmenté / sécurité opérationnelle réduite** pour cette phase de test.

## 2. Ce qui a été construit

| Fichier | Rôle |
|---|---|
| `execution/demo_mt5_executor.py` | Garde-fou FAIL-CLOSED + sizing MT5 réel + `place_market_order` (order_send) |
| `execution/demo_bridge.py` | Pont : chaque ouverture paper swing/forex → ordre démo réel (sous `mt5_lock`, dédup, plafond) |
| `tools/demo_first_trade.py` | One-shot manuel (a placé le 1er trade) |
| `tests/test_demo_executor.py` (13) + `tests/test_demo_bridge.py` (2) | Couverture fail-closed |
| `LANCER_TITANIUM_DEMO_ARME.bat` | Lanceur exécuté par Florent (arme l'exécution) |

Câblage : `core/swing_engine.py` et `core/forex_engine.py` appellent
`place_demo_async(...)` après une ouverture paper réussie (non fatal).

## 3. MUR DÉMO ↔ RÉEL (non négociable, CONSERVÉ)

`assert_demo_or_raise(mt5)` refuse tout `order_send` sauf si :
- `account_info().trade_mode == ACCOUNT_TRADE_MODE_DEMO` (constante officielle) **ET**
- `login == 50061786` (démo attendu) **ET** `login != 60261188` (réel interdit).

→ Le compte RÉEL est **intouchable même armé**. Test : compte réel → aucun ordre
envoyé (`test_place_order_refused_on_real_account`). **Ce garde n'a PAS été
assoupli** — seuls les garde-fous de RISQUE l'ont été (voir §4).

## 4. Paramètres du test (assouplis à la demande de Florent)

`.env` (armé) :
```
DEMO_EXEC_ENABLED=1
DEMO_RISK_PCT=7.0              # risque augmenté
DEMO_MAX_POSITIONS=50         # plafond quasi levé → régulé par la MARGE
DEMO_DAILY_LOSS_LIMIT_PCT=50  # kill-switch = backstop catastrophe seulement
DEMO_MIN_FREE_MARGIN_PCT=20   # anti-cramage : stop nouvelles ouvertures si marge libre < 20%
DEMO_MAX_SPREAD_POINTS=80
```
Sizing basé equity → la taille grossit avec les gains (compounding). Le broker
gère SL/TP (posés à l'ouverture) — pas de gestion de sortie custom (v1).

## 5. État live (2026-07-13 ~07:33 UTC)

- Bot 8090 **armé**, connecté au compte démo (login 50061786 vérifié).
- Compte : balance 1000 → **equity 1005 USD**, marge libre 95 %.
- 1 position : EURUSD SHORT 0.24 lot, PnL +5.04.
- Note garde de sécurité auto-mode : le redémarrage armé par Claude a été bloqué ;
  **Florent a lancé lui-même** (bon modèle de propriété pour l'exécution réelle).

## 6. Demandes de revue

**Codex (red-team)** — angles à auditer :
1. `assert_demo_or_raise` est-il réellement inviolable (bascule de compte pendant
   une session, `account_info()` None, cache) ?
2. `compute_lot` : sizing correct sur tous types (indices .fs, XAU, forex) —
   `trade_tick_value`/`trade_tick_size` par symbole ; risque d'undersizing/oversizing ?
3. `demo_bridge` sous `mt5_lock` : contention avec le flux data ? dédup suffisante ?
   pas de double-ouverture entre le tick d'ouverture et `positions_get` ?
4. 7 % + compounding + pas de plafond de positions : risque de margin-call en
   cascade — le garde marge 20 % suffit-il ? (c'est de la démo, mais on veut de la
   data exploitable, pas un compte cramé en 3 trades).
5. Absence de gestion de sortie custom (dépendance au SL/TP broker) — acceptable v1 ?

**Hermes (orchestrateur)** — prise en compte :
- Le bot exécute désormais en réel sur DÉMO. Ceci reste **paper-only pour le compte
  RÉEL** (mur intact). Ta gouvernance : signaler à Florent tout comportement
  anormal ; le patron A (registre fermé) reste la frontière pour les commandes vocales.

## 7. Prochaines étapes

- Laisser tourner (Florent suit sur MT5 iOS), récolter un échantillon.
- Claude : analyse de calibration dès échantillon significatif (winrate réel vs
  paper, slippage, actifs qui tiennent), puis recalibrage — **avant** tout pas
  vers le compte réel (qui restera une décision explicite gated).
