# Premier bilan — exécution démo MT5 (compte Axi-US50-Demo)

*2026-07-13. Compte démo 50061786. Échantillon PRÉLIMINAIRE (1 trade clôturé).*

## 1. État du compte

| | |
|---|---|
| Balance de départ | 1000,00 USD |
| **Balance actuelle** | **950,08 USD** (−4,99 %) |
| Positions ouvertes | **0** (la position EURUSD a été clôturée) |
| PnL flottant | 0,00 |

## 2. La position que tu suivais — CLÔTURÉE au stop

Le EURUSD SHORT (0,24 lot) que tu regardais **a touché son stop-loss** :

| Étape | Prix | Résultat |
|---|---|---|
| Ouverture (short) | 1,14037 | — |
| Stop-loss posé | 1,14245 | — |
| **Clôture (SL touché)** | **1,14245** | **−49,92 USD** |

Le prix est d'abord descendu (position à +5 un moment), puis est remonté et a
touché le SL. EURUSD est monté contre le short.

## 3. Ce que ça VALIDE (le point positif majeur)

**La mécanique d'exécution est prouvée et fidèle :**
- Risque **visé** : 50,00 USD (5 % de 1000). Perte **réelle** : **49,92 USD**.
  → écart 0,08 USD (0,16 %) : le sizing MT5 est **exact**.
- Le SL a été exécuté **précisément** au niveau posé (1,14245), **zéro slippage**
  sur la sortie.
- Toute la chaîne a fonctionné : ordre, SL/TP, clôture broker, comptabilité.

L'infrastructure démo (ordre réel, sizing, gardes) est **techniquement validée**.

## 4. Ce que ça NE nous dit PAS encore (l'honnêteté du bilan)

**Nous n'avons quasiment aucune donnée de STRATÉGIE.** Détail crucial :
- Ce trade EURUSD n'était **pas** un signal des stratégies validées — c'était le
  **one-shot manuel** de test (heuristique de tendance EMA), placé pour prouver le
  pipeline. Il a perdu, mais c'est **un tirage isolé**, pas un verdict de stratégie.
- Les moteurs **validés n'ont produit AUCUN signal** sur la période :
  - swing : **0 trade** sur 6998 scans ;
  - forex : **0 trade** sur 4713 scans.
  → donc **0 ordre démo auto** issu d'une stratégie validée. On ne sait pas encore
  si le panier validé se traduit en fills gagnants en réel — c'est pourtant LE but.

*(Le paper crypto, séparé du démo MT5, tourne à part : 28 trades, winrate 21 %,
−10,9 USDT — Binance, pas sur ce compte démo.)*

## 5. Lecture & recommandations

1. **Bonne nouvelle** : l'exécution réelle est fiable (sizing exact, SL au prix).
   Le passage paper→démo ne dégrade pas l'exécution. C'est acquis.
2. **Le vrai test n'a pas commencé** : il faut que les stratégies **validées**
   déclenchent. Actuellement elles sont muettes (conditions de marché / seuils).
3. **⚠️ Le 5 % de risque dessert le but « data »** : une seule perte = −5 %. À ce
   rythme, le compte s'érode **avant** d'avoir un échantillon statistiquement
   exploitable. Pour COLLECTER de la data, il faut **plus de trades**, donc un
   risque **plus faible** (ex. 1–2 %) qui laisse le compte survivre plus longtemps.
   Contre-intuitif mais c'est la bonne logique : petit risque = gros échantillon.

## 6. Décisions ouvertes pour Florent

- (a) **Baisser le risque à 1–2 %** pour maximiser le nombre de trades exploitables
  (recommandé pour la calibration), ou garder 5 % (test agressif, data plus rare) ?
- (b) Faut-il **élargir/assouplir** ce qui déclenche un trade démo pour ne pas
  rester à 0 signal ? (⚠️ tout changement de logique de trading = protocole M2,
  pas un simple réglage — à cadrer ensemble.)
- Prochain bilan chiffré dès qu'on atteint ~15–20 trades (winrate réel, slippage
  moyen, actifs qui tiennent).
