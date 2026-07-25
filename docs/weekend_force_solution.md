# Solution week-end forcee — fraicheur globale MTF + realite Axi

Date: 2026-07-25
Auteur: Copilot (relais Claude)

## Objectif

Repondre a la demande Florent:
- verifier la fraicheur de toutes les timeframes de decision, pas seulement M15/H4;
- forcer le week-end pour tester la plomberie demo;
- garder un moteur qui identifie des positions naturellement, et pas un simple moteur de calcul aveugle.

## Ce qui a ete verifie

### 1. Realite Axi demo week-end

Probe MT5 execute en lecture/validation, sans `order_send` reel:
- compte: `50061786 @ Axi-US50-Demo`
- symboles testes: `BTCUSD`, `ETHUSD`, `XAUUSD`, `EURUSD`
- `symbol_info_tick`: present sur les 4 symboles
- `order_check`: `retcode=0`, `comment=Done` sur les 4 symboles

Conclusion pratique:
- Axi demo ACCEPTE la validation pre-trade week-end sur crypto et CFD testes.
- Donc la marche forcee week-end n'est pas absurde: le broker ne refuse pas en amont.
- Limite de preuve: je n'ai PAS envoye un vrai `order_send`, pour eviter d'ouvrir des positions demo parasites juste pour tester. Le meilleur proxy non destructif disponible est `order_check`, et il est vert.

### 2. Boucles de test sur exemples historiques reels

Boucle executee sur 4 symboles (`BTCUSD`, `ETHUSD`, `XAUUSD`, `EURUSD`) et 4 fenetres historiques recentes par symbole.

Resultat resume:
- Fraicheur MTF: `M15=OK`, `H1=OK`, `H4=OK` sur tous les echantillons testes.
- Le moteur ne force pas artificiellement des entrees:
  - il produit surtout `WAIT_NO_SETUP` ou `BLOCK_PILLAR_MISSING`;
  - il garde donc un comportement structurel/naturel, pas une emission mecanique.

Interpretation:
- quand la donnee est fraiche, le blocage principal n'est plus G0 mais la qualite du setup (piliers/confluence);
- la marche forcee week-end sert bien la plomberie, sans transformer le moteur en simple machine a entrer partout.

## Correctif implemente

### 1. Politique globale de fraicheur coherente par TF

Le pipeline valide maintenant explicitement une chaine canonique de timeframes entre la TF d'entree et la TF haute.

Exemple actuel `M15 -> H4`:
- `M15`
- `H1`
- `H4`

Comportement:
- chaque TF a le meme contrat de fraicheur: `3 barres max` en mode normal;
- si une TF echoue, la raison renvoyee detaille toute la chaine, par exemple:
  - `TF_FRESHNESS:M15:STALE|H1:OK|H4:OK`

Effet:
- la lecture est maintenant coherente et auditable;
- on ne se contente plus d'un simple couple LTF/HTF opaque.

### 2. Gestion marche ferme / marche thin

Le `market_status` expose maintenant:
- `open`
- `thin`
- `closed`
- `unavailable`

Regle:
- `closed`: toutes les TF de la chaine sont stale, ou aucune bougie exploitable;
- `thin`: melange de TF fraiches et stale;
- `unavailable`: erreur structurelle/non temporelle;
- `open`: donnees valides et marche exploitable.

### 3. Marche forcee week-end auto-restauree lundi

Le flag existant `DEMO_STALE_RELAX=1` agit maintenant sur toute la chaine MTF, pas seulement sur la M15.

Effet:
- week-end: la plomberie demo peut tourner meme si les bougies sont clairsemees;
- lundi: retour automatique au mode strict, sans intervention manuelle.

## Fichiers touches

- `core/confluence_adapter.py`
- `core/confluence_demo_engine.py`
- `tests/test_confluence_adapter.py`
- `tests/test_stale_relax_weekend.py`
- `tests/test_confluence_demo_engine.py`

## Validation

Valide par tests cibles:
- `pytest tests/test_confluence_adapter.py tests/test_stale_relax_weekend.py tests/test_confluence_demo_engine.py -q`
- resultat: `34 passed`

Validation syntaxe:
- `py_compile core/confluence_adapter.py core/confluence_demo_engine.py`

## Decision recommande

### Pour ce week-end

Garder:
- `DEMO_STALE_RELAX=1`
- `DEMO_EXEC_ENABLED=1`
- `DEMO_MIN_LOT_TEST=1`
- `BRAIN_GATE_PERMISSIVE=1`

But:
- tester la chaine execution/risk/bridge/order_check/order_send demo;
- observer le comportement en situation forcee sans toucher au compte reel.

### A partir de lundi

Ne rien coder de plus pour revenir au mode strict:
- le relax week-end est deja auto-scope dans la fenetre week-end;
- lundi, la fraicheur redevient normale automatiquement.

## Point de fond

Le moteur reste coherent avec la demande Florent:
- il peut etre force pour la plomberie ce week-end;
- mais sur donnees fraiches reelles, il continue a distinguer `WAIT` / `BLOCK` / `ENTER` selon la structure du marche;
- il ne se transforme pas en simple calculateur qui ouvre parce qu'on a relache un seul garde.
