# Méthode d'entrée manuelle de Florent — l'edge humain à encoder (17/07/2026)

*Décrite par Florent après +1 an de trading manuel. C'est le detecteur d'entrée
le plus précieux du projet : une CONFLUENCE, pas un signal unique, + de la patience.*

## Les critères (dans l'ordre où il les lit)

1. **Tendance + gros niveaux S/R sur TF supérieures.** Contexte d'abord :
   direction de la tendance, supports/résistances majeurs des TF hautes.
   → bot : EMA200/biais, structure. ✅ existe.

2. **Volumes d'achat = zone de « juste prix ».** Selon leur valeur, les volumes
   confirment où les investisseurs estiment le juste prix ; **le prix revient
   généralement chercher ces zones avant de repartir en tendance.**
   → bot : `detect_volume_spike`, delta_volume (émotion). ⚠️ manque un **profil de
   volume / VPOC** (nœuds de volume = zones de juste prix). À AJOUTER.

3. **Grosses zones de liquidité** que le marché va récupérer. **Encore plus
   fiable s'il y a un FVG ou un gap.**
   → bot : `detect_liquidity_sweep`, `detect_fvg`. ✅ existe.

4. **Fibonacci — zone OTE (golden zone).** Point d'entrée optimal, MAIS doit être
   **confirmé** ; si la résistance casse = **invalide** (idem Order Blocks).
   → bot : ❌ **PAS de Fib/OTE — à AJOUTER.** OB : `has_ob_or_fvg_alignment` ✅.

5. **Sentiment de marché + volatilité = timing.** Influencent directement la
   décision. **Savoir ATTENDRE le meilleur point d'entrée, ne pas être impulsif.**
   (Florent : son erreur la plus fréquente = entrées impulsives — parfois à tort,
   pas toujours.)
   → bot : **segment ÉMOTION** (valence/arousal, pression, sweeps). ✅ existe —
   c'est ICI que l'émotion gagne enfin un rôle de DÉCISION (timing d'entrée).

## Règle de coût (discipline, pas fatalité)

- **Accepte le spread** — « ça fait partie du jeu ».
- **Refuse le financement du week-end** : ferme **le vendredi soir**, peut
  reprendre **samedi matin**. → encoder « pas de position tenue vendredi soir »
  (le swap week-end ne frappe que là ; côté CFD/MT5).
- Ordres **maker/limite** quand possible pour minimiser la commission.

## Module AGRESSIF (séparé, à traiter à part)

Avril 2026 : **+6000 €** avec prise de **multi-positions**, sizing basé sur
capital + marge. En tendance CONFIRMÉE, quand il sait que le marché reviendra sur
ses points d'entrée, il **empile des positions sur une correction** en surveillant
que la marge tienne (pas de liquidation), pour que la reprise compense les
entrées moyennes et reparte en gain. **Plus risqué, plus rentable.**
→ ⚠️ HONNÊTETÉ : c'est du **pyramidage/averaging en pullback** — légitime en
tendance confirmée AVEC discipline de marge, MAIS risque de queue réel (une seule
« tendance confirmée » qui ne revient pas = liquidation). À modéliser SÉPARÉMENT,
avec garde-fou de marge strict, jamais mélangé au détecteur d'entrée de base.

## Ce que ça donne comme plan

Le détecteur à construire = **CONFLUENCE** : tendance+S/R (1) ∧ zone de juste
prix volume (2) ∧ liquidité/FVG (3) ∧ Fib OTE confirmé / OB non cassé (4), avec
**timing émotion/volatilité** (5) pour attendre le bon moment. Testé rigoureusement
(M2, coûts acceptés, multiplicité contrôlée). À AJOUTER au bot : profil de volume
(VPOC) + Fibonacci OTE.

## Workflow futur (TODO) — labellisation live TradingView

Connecter Claude à **TradingView** avec les indicateurs du bot appliqués au
graphique (après scan des meilleurs actifs). **Florent juge en direct** quand
entrer / sortir → exemples étiquetés réels. « On n'avance plus à l'aveugle. »
= dataset d'entrées humaines pour entraîner/valider le détecteur de confluence.
