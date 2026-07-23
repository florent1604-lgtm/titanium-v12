# Confluence multi-actifs — protocole M2 lead/lag (PAPER ONLY)

Statut : **CONCEPTION / AUCUN CÂBLAGE**. Ce document n'autorise ni ordre, ni flag,
ni consommation du signal par `confluence_demo_engine`. Toute expérience doit être
pré-enregistrée et hashée avant lecture de ses résultats.

## 1. Question falsifiable

À information strictement disponible à l'instant `t`, le rendement fermé d'un actif
leader améliore-t-il la prévision du rendement futur d'un actif cible, au-delà :

- de l'auto-prédiction de la cible ;
- d'un facteur de marché commun ;
- des coûts Axi et du délai réel d'observation/exécution ;
- de l'ensemble des variantes effectivement essayées ?

Une corrélation contemporaine n'est pas une anticipation. « Granger-cause » ou une
cross-corrélation décalée ne prouve pas une causalité économique ; seule compte ici
l'amélioration prédictive hors-échantillon, stable et nette de coûts.

## 2. Limites du primitive existant

`tools/latency_bench._best_lag_ms` reste un outil diagnostique, pas le sélecteur M2 :

- il choisit le maximum parmi 31 lags sans correction de multiplicité ;
- il maximise seulement la corrélation positive et manque les relations inverses
  (DXY→EURUSD/XAUUSD, par exemple) ;
- le forward-fill sur grille 200 ms peut créer de l'autocorrélation artificielle ;
- les timestamps locaux mélangent découverte de prix et latence de transport ;
- un point estimé sans intervalle, stabilité temporelle ni baseline inverse ne suffit pas.

Le code pourra être réutilisé comme contrôle de latence d'arrivée. Le modèle économique
travaillera séparément sur rendements de bougies closes et timestamps UTC corrigés.

## 3. Registre d'hypothèses fermé

Avant chargement des résultats, figer une petite liste motivée économiquement. Proposition
de première famille (toutes les directions et signes attendus sont pré-enregistrés) :

1. `BTCUSDT → {ETHUSD,XRPUSD,LTCUSD,BCHUSD,ADAUSD}` : signe positif ;
2. `DXY → {EURUSD,GBPUSD,XAUUSD}` : signe négatif ;
3. `NAS100.fs → US500` : signe positif.

Les symboles/sources indisponibles donnent `INSUFFICIENT_EVIDENCE`, jamais une substitution
après observation. Aucun scan exhaustif de toutes les paires. Ajouter un actif, inverser
une flèche, un signe, une fenêtre ou un horizon crée une nouvelle famille et augmente le
compteur global d'essais.

## 4. Données et causalité

- Bougies closes uniquement, grille UTC commune, intervalle commun sans remplissage des
  rendements manquants ; sources et calendrier de chaque venue consignés.
- Rendements logarithmiques ou innovations/résidus stationnaires, jamais niveaux de prix.
- Diagnostic ADF + KPSS sur Dev ; échec ou rupture structurelle non maîtrisée = insuffisant.
- Décalage opérationnel obligatoire : le prédicteur clos à `t` ne peut agir qu'au prochain
  scan ; aucune entrée sur la bougie cible qui a produit le signal.
- Baselines : AR de la cible, facteur commun, modèle nul, et direction inverse `B→A`.
- Les fenêtres et horizons sont verrouillés. Proposition primaire : LTF M15, horizon cible
  `t+1`; variantes secondaires limitées et comptées : horizons 2/4 barres et fenêtres
  roulantes 20/60 jours.
- Les rendements futurs chevauchants sont évalués avec erreurs HAC et stationary/block
  bootstrap, jamais bootstrap i.i.d.

## 5. Protocole M2 et multiplicité

Split chronologique commun et immuable : 50 % Dev / 20 % sélection-validation / 30 % final
verrouillé. Dev choisit au plus un lag et une fenêtre par flèche ; ces paramètres sont figés
avant la sélection. Le final n'est lu qu'une fois et son hash est journalisé.

Le registre des essais compte **tous** les couples × directions × signes × horizons ×
fenêtres × transformations × régimes, y compris échecs et essais abandonnés après lecture.

Gates proposés à figer avant résultats :

- contrôle FDR Benjamini–Hochberg à 5 % dans chaque famille pré-enregistrée et Holm sur les
  hypothèses primaires ;
- signe attendu stable dans au moins 70 % des fenêtres de sélection ; intervalle block-
  bootstrap de l'amélioration prédictive excluant zéro ;
- avantage hors-échantillon positif face aux baselines et après coûts/délai Axi ;
- PBO ≤ 0,20 sur toutes les configurations explorées ;
- Deflated Sharpe Ratio ≥ 0,50 selon la convention M2 Titanium, avec nombre total d'essais,
  asymétrie, kurtosis et autocorrélation ;
- effectif minimal pré-enregistré (proposition M15 : 200 événements non chevauchants par
  flèche/segment), sinon `INSUFFICIENT_EVIDENCE`.

Les seuils restent des propositions tant que le pré-enregistrement n'est pas signé. Ils ne
peuvent jamais être abaissés après lecture.

## 6. Mesure d'utilité et signal futur

Mesures primaires : gain de loss prédictive OOS versus baseline, information coefficient
laggé, puis PnL paper net de spread/slippage/commission/swap Axi. La Sharpe brute seule ne
qualifie rien.

Si et seulement si M2 passe, le module offline pourra produire un contrat expirant :

```text
leader, target, as_of_utc, horizon, expected_side, beta, effect_ci,
stability, q_value, dsr, pbo, expires_at_utc, status, reason_codes
```

Le statut maximal est `VALIDATED_FOR_FORWARD_PAPER`. Le signal reste un modérateur
expérimental séparé : absence, staleness, désaccord ou source manquante = aucune bonification
et aucune entrée. Il ne contourne jamais les cinq portes de confluence ni le mur démo/réel.

## 7. Étapes et critères d'arrêt

1. Pré-enregistrer registre, sources, coûts, timestamps, fenêtres, horizons, seuils et hash.
2. Construire un dataset offline reproductible et auditer les alignements sans calculer les
   performances finales.
3. Exécuter Dev puis sélection avec journal complet de multiplicité, PBO, DSR et bootstrap.
4. Geler un candidat maximum par famille ; lire le final une fois.
5. Si validé : forward PAPER silencieux, sans ordre MT5, avec monitoring de drift.
6. Toute instabilité, inversion de sens, avantage absorbé par les coûts ou final négatif :
   `OBSERVATION`/`INSUFFICIENT_EVIDENCE` et arrêt du câblage.

Ordre recommandé des chantiers : **A sécurité → D temps UTC → B M2 offline → E inventaire
read-only des marchés ouverts → C agressif en nouvelle famille M2**. E ne doit devenir une
watchlist démo qu'après contrôle de charge, déduplication et filtres de tradabilité ; C reste
dernier car il modifie le profil de sélection et de risque.
