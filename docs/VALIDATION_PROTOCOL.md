# Protocole de validation statistique — paper only

## Pré-enregistrement obligatoire

Avant de consulter les résultats de sélection, figer et journaliser : univers, fréquence, plage temporelle, règles de stratégie/coûts, variantes testées, métriques, seuil minimal de trades `N_min`, seuils de robustesse, longueur/règle de blocs, nombre de réplications, critères de passage et hash de configuration. Toute modification crée une nouvelle expérience; elle ne peut pas réutiliser le test final précédent.

## Trois segments temporels strictement ordonnés

| Segment | Usage autorisé | Interdit |
|---|---|---|
| Dev | concevoir, déboguer et définir les candidats. | revendiquer une validation. |
| Sélection-validation | choisir parmi les candidats figés et évaluer leur robustesse. | retoucher les règles à partir du test final. |
| Test final verrouillé | une seule évaluation du candidat sélectionné, coûts compris. | optimisation, sélection ou seconde consultation après modification. |

Les frontières sont chronologiques, sans chevauchement ni fuite de données. Le test final est chiffré/à accès contrôlé ou, a minima, son hash et son résultat de première lecture sont consignés; après lecture, il est définitivement consommé.

## Incertitude pour séries dépendantes

Les rendements/trades conservent leur dépendance temporelle : utiliser un moving-block ou stationary block bootstrap, jamais un bootstrap i.i.d. La règle de longueur de bloc, le générateur, le nombre de réplications (minimum 10 000) et la graine sont figés au pré-enregistrement. Rapporter les intervalles de confiance bootstrap des métriques clés (rendement net, drawdown, Sharpe et taux de réussite), ainsi que la proportion de réplications respectant les seuils de robustesse.

Les seuils `N_min` et de robustesse sont des paramètres obligatoires de l'expérience, fixés avant résultat et appliqués par stratégie/instrument/période pertinents; ils ne sont jamais abaissés après coup pour qualifier un candidat.

## Multiplicité et décision

Calculer, en complément des seuils précédents :

- le **PBO** sur l'ensemble des configurations effectivement explorées, selon une procédure de partitions temporelles combinatoires documentée;
- le **Deflated Sharpe Ratio** en tenant compte du nombre de variantes tentées, de la non-normalité et de l'autocorrélation retenues par le protocole.

PBO et Deflated Sharpe ne remplacent ni les coûts réalistes, ni le volume de trades, ni les intervalles block-bootstrap. Tous les candidats testés, écartés ou non, doivent être comptés : exclure des essais après les avoir vus invalide la conclusion.

## Statuts de sortie

| Statut | Condition |
|---|---|
| `INSUFFICIENT_EVIDENCE` | données/trades insuffisants, coût non fiable, protocole incomplet ou incertitude non calculable. |
| `OBSERVATION` | prérequis minimaux satisfaits mais robustesse insuffisante, PBO/DSR préoccupants ou test final non encore consommé. Paper only, surveillance continue. |
| `VALIDATED_FOR_FORWARD_PAPER` | candidat figé, seuils préenregistrés atteints en sélection-validation et confirmés lors de l'unique test final, avec coûts et incertitude documentés. Autorise uniquement le forward paper. |

Le statut est joint à chaque rapport avec les seuils effectifs, hashes, dates des segments et limitations. Aucun statut n'autorise du trading réel.
