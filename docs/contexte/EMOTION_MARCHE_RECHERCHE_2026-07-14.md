# Recherche — émotion de marché et trading (PAPER ONLY)

**Date :** 14 juillet 2026  
**Périmètre :** recherche et simulation exclusivement. Ce document ne crée aucun signal exécutable ni aucun ordre.

## 1. Thèse retenue

L’émotion de marché ne peut pas être ramenée à un oscillateur de prix.

- **Valence** : aversion au risque / peur ↔ appétit pour le risque / euphorie.
- **Arousal** : calme ↔ énergie, urgence, attention, stress et désordre de marché.
- **RSI exclu** : le RSI transforme des prix passés ; il ne mesure ni positionnement, ni demande de protection, ni attention, ni émotion déclarée.

Les mesures disponibles sont des **proxies**. Elles peuvent aussi refléter de l’information fondamentale, une couverture rationnelle, la liquidité ou une prime de risque. Elles ne prouvent jamais une émotion individuelle.

## 2. Évidence académique utile

| Référence | Résultat utile | Limite à conserver |
|---|---|---|
| Baker & Wurgler (2006) — [DOI](https://doi.org/10.1111/j.1540-6261.2006.00885.x), [NBER](https://www.nber.org/papers/w10449) | Le sentiment affecte plus fortement les actifs difficiles à arbitrer ou à valoriser. | Association agrégée, non causalité individuelle. |
| Tetlock (2007) — [DOI](https://doi.org/10.1111/j.1540-6261.2007.01232.x) | Pessimisme médiatique inhabituel : pression baissière de court terme, volume accru, puis réversion possible. | Une source de presse et un lexique ne suffisent pas à prouver la causalité. |
| Da, Engelberg & Gao (2011) — [DOI](https://doi.org/10.1111/j.1540-6261.2011.01679.x) | L’attention précède parfois des achats retail et des mouvements temporaires. | Attention, information et sentiment sont partiellement confondus. |
| Whaley (2000) — [DOI](https://doi.org/10.3905/jpm.2000.319728) | La volatilité implicite synthétise le prix de l’assurance et du stress. | IV/VIX n’est pas synonyme de peur. |
| Bekaert, Hoerova & Lo Duca (2013) — [SSRN](https://doi.org/10.2139/ssrn.2160837) | Le VIX mélange incertitude anticipée et aversion au risque. | Décomposition dépendante du modèle. |
| Garcia (2013) — [DOI](https://doi.org/10.1111/jofi.12027) | L’effet du pessimisme médiatique est conditionnel au régime macro, plus visible en récession. | Les relations changent selon le régime. |

## 3. Taxonomie de mesures

| Famille | Mesure réellement observée | Axe dominant | Règle Titanium |
|---|---|---|---|
| Options : IV, IV-RV, VIX | Incertitude anticipée et prime de risque | Arousal | Ne jamais appeler IV « peur » seule. |
| Skew, risk reversal, put/call segmenté | Demande relative d’assurance baissière | Valence | Comparer à son rang historique par actif/maturité. |
| Funding, long/short, OI | Positionnement à levier sur une venue | Valence conditionnelle + fragilité | OI seul n’a pas de direction ; agréger des venues indépendantes. |
| Liquidations forcées | Désendettement et stress de microstructure | Arousal très fort | Réactif, incomplet selon la venue ; ne pas le présenter comme causal. |
| Order-flow, taker imbalance, spread, profondeur | Pression agressive et liquidité disponible | Valence court terme + arousal | Contrôler séquence, gaps, spoofing et taux d’annulation. |
| Volume, turnover, volatilité réalisée | Intensité de participation et amplitude passée | Arousal | Non directionnel ; peut refléter information ou rééquilibrage. |
| News | Polarité et attention médiatiques | Valence + arousal | Conserver source, texte, pertinence, nouveauté, publication et réception. |
| Réseaux sociaux | Humeur retail exprimée et attention | Valence + arousal | Signal le plus manipulable : dédupliquer, détecter bots/coordination, plafonner concentration. |
| COT | Positionnement réglementaire futures | Valence de régime lent | Rapport daté mardi/publié vendredi : jamais intraday. |

Sources de données/mécanique : [Cboe VIX](https://www.cboe.com/tradable-products/vix/vix-historical-data), [CFTC COT](https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm), [Binance funding](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History), [OI](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Open-Interest), [liquidations](https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams/Liquidation-Order-Streams).

## 4. Règles de décision émotionnelle

1. **Pas de décision sur une source unique.** Un état émotionnel requiert une concordance de familles indépendantes.
2. **La panique active ne se fade pas.** Peur élevée + énergie encore croissante = danger de poursuite.
3. **Les extrêmes épuisés seulement sont contrarians.** Capitulation (valence négative extrême + arousal en reflux) peut soutenir un biais long simulé ; euphorie épuisée peut soutenir un biais short simulé.
4. **Divergence = incertitude, pas signal directionnel.** Exemple : IV/volume hauts mais social neutre → régime actif, pas direction certaine.
5. **Stale = non utilisable.** Une panne sociale, un COT retardé ou une cote d’option périmée ne vaut jamais un score neutre.
6. **No-trade par défaut** si couverture, fraîcheur, intégrité ou confiance sont insuffisantes.

## 5. Contrat de données point-in-time

Chaque observation doit conserver :

```text
source, instrument, venue, event_time, publish_time, receive_time,
latence, timezone, formule, version fournisseur/modèle, confiance,
état fresh/stale, raison d’exclusion éventuelle.
```

Les snapshots doivent être append-only. Une révision fournisseur ou une modification d’API ne doit jamais réécrire un backtest historique.

## 6. Protocole de validation avant toute influence décisionnelle

1. Pré-enregistrer formule, univers, fréquence, TTL, hypothèse et mapping valence/arousal.
2. Normaliser uniquement avec le passé : fenêtres glissantes, par actif, venue, maturité et régime.
3. Évaluer **valence** sur un objectif directionnel et **arousal** sur volatilité future, jumps, spreads ou volume futur : ne pas confondre les deux.
4. Utiliser un walk-forward chronologique, purge/embargo pour horizons chevauchants et une période finale gelée.
5. Comparer au prix seul, aux retards de prix, à chaque famille seule, au signal permuté et à l’hypothèse nulle.
6. Rapporter rendement net simulé, volatilité, drawdown, Calmar, turnover, coûts, impact, stabilité par régime et intervalles de confiance.
7. Corriger les recherches de seuils multiples : Reality Check de White, SPA de Hansen, Deflated Sharpe Ratio / PBO si pertinent.
8. Segmenter calme/stress, tendance/range, heures de marché, bull/bear et jours d’événement.
9. Auditer manipulation : divergence de venues, concentration, volume sans prix, annulations anormales, comptes sociaux coordonnés.
10. Rester **PAPER ONLY**. L’émotion est d’abord un filtre de qualité/risque, jamais un ordre autonome.

## 7. Pièges structurels

- Réflexivité : prix, médias et positions s’influencent mutuellement.
- Herding : le consensus social peut répéter un récit sans information nouvelle.
- Look-ahead bias : publication, réception et disponibilité de donnée sont différentes.
- Changements de régime : une relation moyenne peut disparaître en crise ou en marché calme.
- Surapprentissage : multiplier sources, prompts, seuils et horizons produit des faux positifs.
- Survivorship et révisions : univers et séries actuels ne sont pas nécessairement ceux disponibles à la date historique.

Références de garde-fous : [De Long et al. (1990)](https://doi.org/10.1086/261703), [Bikhchandani et al. (1992)](https://doi.org/10.1086/261849), [Ang & Timmermann (2012)](https://doi.org/10.1146/annurev-financial-110311-101808), [White (2000)](https://doi.org/10.1111/1468-0262.00152), [Hansen (2005)](https://doi.org/10.1198/073500104000000631), [Loughran & McDonald (2011)](https://doi.org/10.1111/j.1540-6261.2010.01625.x).

## 8. Conclusion

Titanium doit apprendre l’émotion comme une **structure de données auditable**, à deux axes, sous incertitude : pas comme un score magique ni un RSI rebaptisé. La qualité, la fraîcheur, la concordance inter-sources et la validation prospective PAPER ONLY priment sur toute ambition de prédiction directionnelle.
