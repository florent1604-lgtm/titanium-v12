# Rapport de calibration Titanium — 15 juillet 2026

> **Statut : EN COURS — AUCUN VERDICT DE PERFORMANCE À CE STADE.**
> Les runs v1 à v5 ci-dessous sont des simulations diagnostiques refusées
> fail-closed. Ils ne justifient aucune modification de `data/asset_configs.json`,
> d'un timeframe, d'un seuil d'entrée ou d'une limite de risque.

## Décision et périmètre

- Compte de mesure : **Axi-US50-Demo, login 50061786**.
- Compte réel 60261188 : **PAPER ONLY**, jamais utilisé pour une lecture ou une
  exécution de calibration native.
- Le paper reste le cerveau ; le pont démo ne peut intervenir qu'après une
  ouverture paper.
- Risque simulé : 7 % par trade, uniquement pour exprimer les rendements du
  compte démo. Ce paramètre ne transforme pas une stratégie non validée en
  stratégie admissible.
- `assert_demo_or_raise` et le mur démo/réel restent inchangés.
- Le fichier runtime `data/asset_configs.json` n'est pas modifié. La sortie sera
  un artefact **PROPOSITION ONLY**, soumis à Claude puis Florent.

## Question centrale

Une fréquence M15 ou H1 produit-elle, après spread, slippage et swap Axi, une
espérance OOS positive et suffisamment stable pour apprendre plus vite que H4 ?
La réponse sera donnée par actif avec : PF, Sharpe annualisé, espérance nette,
trades/jour, P&L net/jour, coût par trade, poids des coûts dans le profit brut,
spread de bascule, PBO, Deflated Sharpe et verdict M2.

Un scalp MT5 ne voit que le flux L1. L'absence de profondeur L2 rend donc son
coût simulé optimiste : le résultat MT5 constitue une borne inférieure des coûts
d'impact, pas une preuve complète de liquidité exécutable.

## Protocole préenregistré

1. Même fenêtre calendaire pour M15, H1 et H4 sur chaque actif.
2. Découpage temporel 50 % développement, 20 % sélection, 30 % final verrouillé
   (soit 70/30 IS/OOS).
3. 36 candidats fixes par style, 108 essais par actif ; aucun raffinement
   adaptatif après lecture de l'OOS.
4. Gates de stabilité avant sélection : développement ≥ 30 trades, sélection ≥
   15 trades, espérance > 0 et PF > 1 sur les deux segments.
5. Le segment final n'est exécuté qu'une fois pour le gagnant de chaque style.
6. Gate final : ≥ 30 trades, PF ≥ 1,20, espérance et borne bootstrap à 95 % > 0,
   drawdown ≤ 20 %, PBO ≤ 0,50 et Deflated Sharpe ≥ 0,50.
7. Le PBO conserve tous les essais préenregistrés, y compris les perdants ; le
   DSR tient compte de la famille complète de 108 essais.
8. Règle de proposition : style le plus rapide qui franchit tous les gates M2
   (`scalp` M15, puis `intraday` H1, puis `swing` H4).

Le DSR suit Bailey et López de Prado, *The Deflated Sharpe Ratio* :
[document des auteurs](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf).
Les unités de swap et la limite d'historique suivent la
[référence officielle MQL5 des propriétés symbole](https://www.mql5.com/en/docs/constants/environment_state/marketinfoconstants)
et la
[référence officielle `copy_rates_range`](https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesrange_py).

## Journal des simulations diagnostiques

| Run | Résultat | Cause du refus | Enseignement conservé |
|---|---|---|---|
| v1 | 0/3 actif mesuré | EURUSD/XAUUSD sans M15 ; USTECH swap `INTEREST_OPEN` non supporté | Un refus de coût inconnu vaut mieux qu'un PF faux. |
| v2b/v2c | 0/3 | L'API Python n'expose pas les sept multiplicateurs journaliers | Dériver et tracer le calendrier depuis `swap_rollover3days`; jamais facturer arbitrairement le week-end. |
| v3 | non retenu | Revue avant exécution : triple swap décalé d'un jour | Le multiplicateur appartient au rollover du jour de départ (mercredi vers jeudi). |
| v4 | 0/3 | Requête unitaire M15 de 100 000 barres refusée `(-2, Invalid params)` | Une erreur de limite n'est pas transitoire ; les retries ne la corrigent pas. |
| v5 | abandonné avant verdict | Cap unitaire 60 000 fonctionnel mais horizon réduit | Ne pas sacrifier 40 % de l'historique quand le chargement chunké est disponible. |
| v6 smoke | 3/3 calculés, 0 proposition | Chargement par tranches de 240 jours, déduplication et cap terminal 100 000 | Transport validé ; M15 perdant sur EURUSD, USTECH et XAUUSD, H1 USTECH positif mais non déflaté. |

## Coûts observés lors des diagnostics

Ces captures sont indicatives et seront reprises à l'instant de chaque run final.
Le slippage stressé ajoute 25 % du spread observé ; la commission séparée est
fixée à 0 bps pour ce compte démo spread-only, à confirmer par le testeur natif.

| Actif | Spread observé | Mode swap | Swap long brut | Swap short brut |
|---|---:|---|---:|---:|
| EURUSD | 0,611 bps (7 points) | POINTS | -6,71 | +3,69 |
| USTECH | 0,238 bps (70 points) | INTEREST_OPEN | -6,75 %/an | +0,75 %/an |
| XAUUSD | 0,395 bps (16 points) | POINTS | -58,3 | +38,7 |

## Résultats OOS par actif

Le smoke v6 ci-dessous est un contrôle ciblé, pas encore le tableau des 141
actifs. Les valeurs en devise utilisent la balance démo capturée (950,08 USD) et
un risque simulé de 7 % par trade.

| Actif | Style / TF retenu | PF OOS | Sharpe OOS | Espérance nette | Trades/jour | P&L net/jour | PBO | DSR | Verdict M2 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| EURUSD | aucun ; M15 testé | 0,695 | -1,309 | -1,461 bps/trade | 0,241 | -2,97 USD | 0,00 | 0,000000005 | OBSERVATION |
| USTECH | aucun ; H1 à observer | 1,239 | 1,017 | +5,624 bps/trade | 0,399 | +3,36 USD | 0,30 | 0,025 | OBSERVATION |
| XAUUSD | aucun ; M15 testé | 0,775 | -1,364 | -3,597 bps/trade | 0,635 | -3,58 USD | 0,60 | 0,000373 | OBSERVATION |

Sur USTECH, H4 obtient PF 2,358 et +44,16 bps/trade, mais seulement 28
trades finaux : le verdict est `INSUFFICIENT_EVIDENCE`. Sur XAUUSD, H4 obtient
PF 2,146 et +29,94 bps/trade sur 25 trades ; il reste insuffisant et contredit
par l'ancien test natif PF 0,90. Aucun de ces deux chiffres H4 n'est promu.

## Validation native MetaTester

Le code du runner a reçu les corrections de revue : booléen `market_session`
strict, chemins liés au preflight portable, hash EX5 vérifié, INI UTF-16LE et
clés sensibles contrôlés, verrou inter-processus du state store, parsing HTML
fail-closed et lecture du rapport final uniquement pour le candidat sélectionné.

Aucun run natif n'est compté tant qu'un terminal portable réellement isolé, un
EX5 préenregistré et un manifest conforme ne sont pas fournis. Le terminal MT5
actif n'est ni arrêté ni réutilisé comme environnement de test.

## Décision provisoire

**Aucune.** Les anciennes affirmations « H4 domine » et « scalp mort après frais »
provenaient d'un pipeline où l'OOS servait à la sélection et où M15 n'avait été
testé que sur 15 actifs choisis pour H1/H4. Elles sont retirées comme preuves.
La décision de fréquence attend le run OOS propre et la confirmation native des
candidats retenus.
