# Lead/lag inter-actifs — validation M2 Codex (2026-07-18)

Statut : **PAPER/DEMO ONLY — BLOCK CÂBLAGE — 0 PAIRE SURVIT**.

## Verdict

Les trois candidats exploratoires sont rejetés avant lecture du segment final :

| Candidat (lag scanner) | BH q / Holm p | Bootstrap 95 % du gain de loss | PnL net sélection | DSR diag. | Verdict |
|---|---:|---:|---:|---:|---|
| SOL → BCH (2) | 0,685 / 1,000 | [-3,21e-9 ; -0,67e-9] | -5,46 bps/barre | 0,000 | rejet |
| ETH → XRP (2) | 0,829 / 1,000 | [-3,69e-9 ; 10,64e-9] | -14,33 bps/barre | 0,000 | rejet |
| LTC → BCH (2) | 0,707 / 1,000 | [-15,16e-9 ; 2,61e-9] | -20,58 bps/barre | 0,000 | rejet |

Sur la famille complète `9 actifs × 8 followers × 12 lags = 864 tests` :

- BH-FDR 5 % : **0/864** ;
- Holm FWER 5 % : **0/864** ;
- PBO CSCV sur les 864 configurations : **0,00**, mais non disculpant : les
  configurations sont des perdantes stables. Le PBO mesure l'instabilité du
  classement, pas l'existence d'une espérance positive ;
- DSR sélection diagnostique des trois candidats : **0,000**, sous 0,50 ;
- final 30 % (`2025-09-07 10:15Z` → `2026-07-16 07:15Z`) : **non lu**.

Le résultat est un rejet sûr, pas une certification M2 positive. Les candidats
avaient déjà été vus avant cette passe : l'expérience ne peut plus être dite
pré-enregistrée ex ante. De plus, aucune trace de latence de transport/exécution
Axi synchronisée au dataset n'est archivée. Ces deux réserves empêcheraient une
promotion même si les statistiques étaient positives.

## Exécution du protocole

- Dataset : 99 578 rendements M15 communs Axi, du 2023-09-07 18:00Z au
  2026-07-16 07:15Z, neuf actifs. Rendement accepté seulement si les deux closes
  sont séparés d'exactement 15 minutes ; jointure interne, aucun forward-fill.
- Split immuable : Dev 49 789 (50 %), sélection 19 915 (20 %), final 29 874
  (30 %, verrouillé/non lu).
- Baseline apprise sur Dev : AR(1) cible + facteur crypto équipondéré hors paire.
  Modèle augmenté : baseline + rendement du leader à `t`, cible à `t+k` ; aucune
  entrée sur la barre ayant produit le signal.
- Test primaire : amélioration appariée de loss carrée en sélection, paramètres
  gelés depuis Dev, erreur HAC puis BH global et Holm global.
- Incertitude candidats : moving-block bootstrap, blocs d'un jour M15 (96 barres),
  2 000 réplications, seed 20260718.
- Économie PAPER : position séquentielle au signe de la prévision ; coût Axi à
  l'entrée/changement de côté, snapshots spread stressé + slippage + commission.
  Round-trip utilisé : BCH 44,78 bps ; XRP 36,23 bps.
- Hash du protocole lu :
  `B7F0A782B3C8EC3E850681338B27ABD308CCDD30F05F337437A589E666499593`.
  Les neuf caches sources ont été hashés SHA-256 pendant l'audit.

La réplication exacte sur historiques Binance n'a pas été possible : BCHUSDT
n'était pas dans le cache Binance quatre ans et le fetch réseau a renvoyé `None`.
Le contrôle Axi est néanmoins celui qui répond à la transportabilité et aux
coûts de la passerelle d'exécution demandée.

## Red-team du scanner Claude

### P0 — bougie Binance en formation et ordre de transport

`core/lead_lag_engine._crypto_fetch` appelle directement `get_ohlcv(..., 500)` et
retourne la dernière close. Or `data/binance_ohlcv` documente explicitement que
la dernière ligne est la bougie en formation et qu'elle doit être retirée « en
amont » ; ce retrait n'existe pas dans la boucle lead/lag. Le scanner peut donc
repeindre. Les neuf requêtes REST sont en plus séquentielles : leurs closes de la
même bougie ouverte sont observées à des instants différents. Cet ordre de fetch
peut fabriquer un lead/lag de transport, particulièrement sur la dernière barre.

### P1 — sélection, alignement et persistance

- Le meilleur des 12 lags est choisi sur `abs(corr)` sans correction locale ; les
  72 paires ordonnées donnent 864 essais. Corrélation brute, hit-rate et flip-rate
  réutilisent ensuite ce lag sélectionné.
- Aucun retrait de l'AR cible ni du facteur crypto commun ; le sens inverse n'est
  pas comparé. Une réaction commune/autocorrélée peut paraître directionnelle.
- Il n'y a pas de forward-fill dans `align_returns` (bon point), mais aucune garde
  index monotone/unique ni contrôle d'espacement M15. `log_returns` peut donc
  transformer un trou de 30/45 minutes en « rendement M15 ».
- La jointure complète sur les neuf actifs élimine une date dès qu'un seul actif
  manque ; cela change l'échantillon de toutes les paires et peut introduire un
  biais de disponibilité. Une jointure paire par paire avec calendrier audité est
  préférable.
- La persistance réemploie presque les mêmes 500 barres à chaque cycle. Les scans
  fortement chevauchants ne sont pas des réplications indépendantes. Au premier
  passage, `seen=1, rate=1.0` est visuellement trompeur même si le gate exige cinq
  observations.
- Les exceptions de fetch sont avalées par symbole sans reason-code ; un univers
  variable peut modifier silencieusement classement et multiplicité.
- Les six tests synthétiques prouvent la détection d'un lag massif, pas l'absence
  de repaint/look-ahead, la robustesse aux trous/duplicates, le contrôle sous le
  null, la relation inverse, les coûts ou le transport.

## Turning-point : test propre pré-enregistrable

Le `flip_rate` courant estime seulement `P(flip cible | flip leader)`. Il ne le
compare pas à `P(flip cible)` et un flip de signe sur des rendements bruités vaut
naturellement environ 50 %. Sur la sélection Axi, les uplifts bruts sont :

- SOL→BCH : 51,33 % conditionnel contre 51,27 % de base, **+0,06 point** ;
- ETH→XRP : 51,56 % contre 51,49 %, **+0,07 point** ;
- LTC→BCH : 51,35 % contre 51,27 %, **+0,08 point**.

Les 58–60 % du scan court ne persistent donc pas sur l'échantillon de sélection.

Protocole proposé, nouvelle famille séparée :

1. Résidualiser leader et cible sur AR cible + facteur commun, uniquement avec
   paramètres Dev.
2. Pour chaque horizon fermé `h` pré-enregistré, définir
   `Y(t,h)=1[sign(eF(t+h)) != sign(eF(t+h-1))]`. Les features disponibles à `t`
   sont le flip résiduel du leader, son choc normalisé (seuil figé sur Dev), l'état
   courant de la cible et le facteur ; jamais une donnée postérieure à `t`.
3. Comparer une logistique augmentée à un hazard baseline (taux de base + état de
   la cible). Mesure primaire : gain OOS de log-loss/Brier apparié ; AUC-PR,
   calibration et MCC seulement secondaires. Un simple flip prédit un événement,
   pas un côté : la direction doit être une cible séparée, ou être explicitement
   définie comme `-sign(eF(t))` et testée.
4. Split 50/20/30 purgé avec embargo `h`, événements non chevauchants, au moins
   200 flips par segment. Block bootstrap/stationary bootstrap sur la différence
   de loss ; BH+Holm sur toutes les paires × horizons × seuils, essais abandonnés
   inclus ; stabilité du signe ≥70 % des fenêtres.
5. Après passage statistique seulement : simulation PAPER à la première barre
   exécutable après le scan, coût/latence Axi et abstention si probabilité sous le
   seuil Dev. Gates inchangés : PBO≤0,20, DSR≥0,50, CI du gain >0, net coûts >0.
   Final lu une fois ; statut maximal `VALIDATED_FOR_FORWARD_PAPER`.

## Décision

**Aucune paire ne survit.** Le scanner reste un moniteur exploratoire uniquement.
Avant tout nouveau résultat interprétable : exclure explicitement la bougie
ouverte, capturer un snapshot commun/as-of, auditer les trous, enregistrer le
transport Axi et lancer la nouvelle famille turning-point sous registre neuf.
Rien n'est câblé, aucun flag n'est modifié, aucun ordre n'est envoyé.
