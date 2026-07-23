# Contrat de stratégie — live-paper et backtest

## Objet et convention temporelle

Une stratégie est une fonction **pure, déterministe et sans I/O** : même entrée canonique, même version de stratégie et même configuration donnent strictement la même intention. À la clôture de la barre `t`, elle ne peut lire que les données dont la disponibilité est prouvée à `t`; elle produit une intention exécutable au plus tôt sur `t+1`. Aucune valeur, indicateur, révision ou état connu après `t` n'est admis.

Une barre est exploitable seulement si `closed=true`, possède un `bar_id` immuable et un `source_ts <= decision_ts`. Une barre ouverte, absente, désordonnée ou stale mène à `NO_TRADE` avec un motif explicite.

## Signature proposée

```text
decide_strategy(
  market: MarketSnapshotAtClose,
  portfolio: PortfolioSnapshotAtT,
  config: FrozenStrategyConfig,
  cost_model: FrozenCostModel,
  context: DecisionContext
) -> DecisionIntent
```

| Entrée | Exigences minimales |
|---|---|
| `market` | OHLCV/ticks, spread observé ou règle de fallback, métadonnées instrument, `bar_id`, `closed`, `source_ts`, `decision_ts`; historique borné à `t`. |
| `portfolio` | cash, positions, ordres/intents en attente, prix de référence et PnL réalisés connus à `t`; aucun état mutable caché. |
| `config` | paramètres, règles de sizing et version/hash immuables durant un run. |
| `cost_model` | devise, spread, slippage, commissions/frais et swap/financement, avec règles et paramètres versionnés. |
| `context` | `strategy_id`, run id, calendrier/session, devise de compte et convention d'exécution; pas d'horloge système ni d'aléa non enregistré. |

## Sortie

`DecisionIntent` contient : `action` (`NO_TRADE`, `OPEN`, `CLOSE`, `REDUCE`, `REVERSE`), sens, instrument, quantité/risque maximal, type d'ordre, validité, prix/règle de déclenchement, stop/target éventuels, `execute_from_bar_id=t+1`, motifs et un instantané des hypothèses de coût. La sortie est une intention : le moteur d'exécution applique les mêmes règles de remplissage dans les deux modes et journalise tout remplissage/refus séparément.

Convention par défaut : une intention émise à la clôture de `t` est remplie au premier prix réellement disponible de `t+1`; jamais au close de `t`. Si ce prix n'existe pas, l'ordre reste non rempli ou expire selon la règle versionnée — il n'est pas « amélioré » par une donnée future.

## Coûts et résultat économique

Chaque exécution doit expliciter, dans la devise de compte :

- spread : bid/ask observé, sinon fallback déterministe déclaré;
- slippage : fonction signée de l'ordre, liquidité/volatilité disponibles à `t` et paramètres figés;
- frais/commissions/taxes : barème par instrument et volume;
- swap/financement : règle de rollover, jours et taux applicables à la position tenue.

Le backtest comptabilise ces postes au même instant et avec le même arrondi que le live-paper. L'absence d'une donnée nécessaire au coût produit `NO_TRADE` ou le fallback explicitement autorisé; jamais un coût implicite de zéro.

## Déterminisme et reproductibilité

Un run archive : version/hash du code et de `config`, données source et leur hash, normalisation, `cost_model`, calendrier, ordre des événements et décisions par `bar_id`. Toute source pseudo-aléatoire est interdite ou reçoit une graine fournie dans `context` et consignée. Un replay sur le même jeu canonique doit reproduire à l'identique les `DecisionIntent`, coûts et fills; toute divergence est un échec de parité live-paper/backtest.
