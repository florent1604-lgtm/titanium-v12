# Prompt Claude Code — refonte V12 en Swing Desk paper-only

Copie-colle intégralement ce prompt dans Claude Code, à la racine de C:\Users\flore\Desktop\v12.

---

Tu interviens sur Titanium V12, un bot de trading actuellement en construction et relié à JARVIS dans C:\Program Files\JARVIS.

Lis d'abord, intégralement :

- AGENTS.md
- CLAUDE.md
- docs/AUDIT_V12_SWING_2026-07-10.md
- docs/RAPPORT_REVALIDATION.md
- docs/RAPPORT_OPTIM.md
- docs/RAPPORT_MT5_BACKTEST.md

## Mission

Transformer V12 en un système cohérent, défendable et PAPER ONLY de swing trading H4. La seule finalité est de produire des intentions swing et de mesurer leur exécution simulée de manière fiable. Il est interdit d'ajouter une exécution réelle, un ordre broker, une clé secrète dans le code, une promesse de rendement ou une recommandation intraday/scalping.

Le résultat doit inclure :

1. un moteur swing unique, fondé sur barres D1/H4 clôturées ;
2. un portefeuille paper unique avec limites de risque globales et par corrélation ;
3. un backtest identique à la logique paper, traçable et résistant au surapprentissage ;
4. un contrat de données V12 ↔ JARVIS versionné ;
5. une refonte complète du dashboard sous le nom Titanium Nexus — Swing Desk ;
6. une batterie de tests et une procédure de validation reproductible.

Ne touche pas aux secrets ni au contenu des fichiers .env. Préserve toutes les modifications utilisateur déjà présentes. Ne committe pas, ne pousse pas et ne réinitialise pas Git.

## Contraintes de sécurité non négociables

- PAPER ONLY doit être imposé au niveau de la configuration, du runtime et des routes. Aucun chemin ne doit pouvoir envoyer un ordre MT5/Binance.
- La valeur par défaut de l'hôte API est 127.0.0.1. N'écoute pas sur 0.0.0.0 sans une décision explicite de l'utilisateur.
- Supprime du dashboard et désactive par défaut les routes web qui démarrent/arrêtent des processus, font git add/commit/push, modifient des services, ou déclenchent une exécution.
- Toute mutation API conservée doit passer par une dépendance FastAPI require_admin. Elle compare X-Admin-Token au secret ADMIN_TOKEN avec secrets.compare_digest. Si ADMIN_TOKEN est absent, les mutations doivent répondre 503 et rester désactivées.
- Ne mets jamais ce token dans le HTML, JavaScript, logs, réponses JSON ou message JARVIS.
- TradingView webhook : désactivé par défaut. S'il est maintenu à des fins de compatibilité, il ne peut créer qu'une intention STAGED ; ajoute HMAC, timestamp, nonce anti-rejeu, limite de taille, liste blanche et tests de refus. Il ne doit jamais ouvrir une position automatiquement.
- Supprime l'action GitHub push du frontend et la route /services/github/push. Retire aussi les commandes web start/stop Ollama/GitNexus/Titan, ou rends-les indisponibles hors d'un CLI local explicitement lancé.
- Les réponses de statut sensibles doivent contenir Cache-Control: no-store.

## Politique de trading à figer

La stratégie active est exclusivement swing :

- décision seulement sur une barre H4 clôturée ;
- biais de régime D1/H4 ;
- entrée simulée à la prochaine ouverture exécutable, avec bid/ask et coûts ;
- une seule intention par symbole et par bar_id ;
- gestion de position au tick ou à la cotation, mais jamais création d'un signal sur une bougie ouverte ;
- aucun scalp, aucune décision M15/H1/5m, aucune auto-intégration d'actif.

Univers initial :

| Actif | État | Motif |
|---|---|---|
| USTECH | FORWARD_PAPER | revalidation MT5 native robuste |
| NAS100.fs | FORWARD_PAPER | revalidation MT5 native robuste |
| HSI.fs | OBSERVATION | revalidation positive mais modeste |
| Tous les autres | DISABLED | absence de preuve suffisante, hors stratégie ou rejet |

XAUUSD swing doit rester désactivé : le rapport MT5 natif l'invalide malgré le PF Python. EURUSD et GBPUSD ne doivent pas être activés : ils sont H1 et donc hors directive swing-only.

Crée config/swing_universe.json. Chaque actif doit contenir : enabled, status, cluster, timeframe, paramètres de règle, hypothèses de coûts, evidence_source, evidence_period, evidence_status et reason. Le code doit refuser de trader un actif absent, DISABLED, non H4 ou non FORWARD_PAPER.

Place ces limites dans config/risk_policy.json, pas en constantes dispersées :

- risk_per_trade_pct : 0.25 ;
- max_open_positions : 2 ;
- max_gross_exposure_pct : 0.50 ;
- max_cluster_initial_risk_pct : 0.50 ;
- cluster US_INDICES : USTECH et NAS100.fs ;
- daily_loss_limit_pct : 1.00 ;
- max_drawdown_kill_switch_pct : 5.00 ;
- données, calendrier ou coût obsolète : refuser l'entrée.

Ces valeurs sont des limites paper prudentes et doivent être clairement visibles/modifiables dans la configuration. Ne les optimise pas pour faire passer un backtest.

## Méthode de travail obligatoire

1. Lance git status --short et documente les fichiers déjà modifiés. Ne les écrase pas.
2. Si GitNexus est disponible, utilise l'analyse d'impact avant toute modification de fonction/classe/méthode et lance la détection de changements avant toute proposition de commit. Respecte AGENTS.md.
3. Crée d'abord les tests rouges. Implémente seulement le minimum pour les faire passer.
4. Travaille par étapes, exécute les tests pertinents à chaque étape, puis le suite complète à la fin.
5. Si l'environnement Python est cassé, ne masque pas l'erreur : documente le bootstrap reproductible avec une version Python réellement disponible et un requirements-dev.txt comprenant pytest, pytest-asyncio et les outils de lint nécessaires.
6. Ne remplace jamais les tests par des mocks qui masquent la logique métier. Les flux MT5 sont mockables, les règles et le portefeuille doivent être testés avec des données déterministes.

## Architecture à mettre en place

Ne réécris pas le projet aveuglément. Introduis les modules suivants, migre progressivement les appels, puis retire les chemins obsolètes du runtime :

    domain/
      models.py
      swing_rules.py
      portfolio_risk.py
      paper_broker.py
      repositories.py
      validation.py
    api/
      swing_v2_routes.py
      admin_auth.py
      schemas.py
    config/
      swing_universe.json
      risk_policy.json
      integration_contract_v1.json
    backtest/
      engine.py
      costs.py
      metrics.py
      provenance.py
      validation_gate.py

Les noms peuvent varier uniquement si l'équivalent est plus cohérent avec l'architecture existante. Les responsabilités suivantes ne peuvent pas varier.

### Modèles et contrat

Dans domain/models.py, définis des modèles Pydantic ou dataclasses immuables typés :

- ClosedBar : symbol, timeframe, open_ts, close_ts, OHLCV, is_closed=True, provider_sequence ;
- TradeIntent : intent_id, symbol, side, bar_id, strategy_version, entry_model, entry_reference, stop, targets, initial_risk, evidence_status, created_at ;
- Position, Fill, CostBreakdown et PortfolioSnapshot ;
- TitaniumSnapshotV1 : schema_version, source_ts, received_ts, stale_after_seconds, mode, portfolio, positions, decisions, system_health, audit_events.

Toute réponse utilisée par le dashboard ou JARVIS doit dériver de TitaniumSnapshotV1. Les unités sont explicites dans les clés : pnl_eur, risk_pct, price, size_lots, source_ts. Ne crée pas total_pnl ambigu.

Expose docs/contracts/titanium_snapshot_v1.json avec un exemple JSON sans secret, et teste sa validité.

### Règles swing

Dans domain/swing_rules.py, crée une fonction pure evaluate_closed_bar(history, config) -> TradeIntent | None.

- Elle ne lit ni fichier, ni réseau, ni horloge système.
- Elle utilise uniquement des barres marquées closed.
- Les indicateurs EMA/ATR/RSI/TRIX et le signal doivent être identiques dans le live paper et le backtest.
- Elle retourne un motif de refus structuré lorsque la donnée est insuffisante, obsolète ou hors politique.
- Elle ne doit pas dépendre du score SMC 1m/5m actuel, du carnet L2, de l'analyse spectrale, de Delta Volume ou d'un LLM.
- Ajoute strategy_version et config_hash à chaque intention.

Le moteur live doit conserver last_processed_bar_id par symbole. Une barre ne peut produire qu'une intention. Après la fermeture d'une position, l'ancienne barre ne peut jamais déclencher une réouverture.

### Portefeuille et paper broker

Remplace les comptes paper séparés swing/forex/crypto par un seul portefeuille swing dans domain/paper_broker.py.

- Toute ouverture passe par PortfolioRiskService.check(intent, snapshot).
- Calcule le risque monétaire avec les métadonnées MT5 de l'instrument : contract_size, tick_size, tick_value, devise de profit et conversion. Utilise order_calc_profit ou un adaptateur injecté/mockable ; ne conserve pas la formule notional = risk / distance relative.
- Les prix d'entrée et sortie utilisent ask pour acheter, bid pour vendre, et appliquent commission, spread, slippage, swap et frais de rollover selon l'actif et le côté.
- Les sorties partielles, le passage break-even, le time-stop et les frais doivent être exactement les mêmes dans le backtest.
- Avant ouverture, vérifier la nouvelle exposition totale, le risque initial agrégé, l'exposition du cluster, la perte journalière, le kill-switch DD et la disponibilité de cash/marge. Vérifier l'état après ajout, pas seulement l'état avant ajout.
- Journaliser chaque refus, intention, fill, partial, fermeture et changement de limite avec correlation_id et reason_code.
- Écrire les états par write-temp puis os.replace. Ne jamais écraser directement un JSON d'état.
- Le journal d'audit est append-only et rejouable ; l'état est un cache reconstruisible.

Désactive core/signal_engine.py, core/forex_engine.py, core/opportunity_scan.py et les boucles d'optimisation crypto du lifespan par défaut. Conserve éventuellement des adaptateurs legacy non actifs, sans route visible, uniquement s'ils sont nécessaires à une migration sûre.

### Backtest défendable

Réécris le backtest dans backtest/engine.py autour de domain/swing_rules.py et du même modèle de fills que PaperBroker.

Règles absolues :

- le signal est observé à la clôture de t ; l'entrée ne peut avoir lieu qu'à t+1 ou au premier prix bid/ask disponible après t ;
- jamais de remplissage fictif au close utilisé pour décider ;
- OHLC intrabar ambigu : appliquer une convention pessimiste documentée, ou utiliser ticks si disponibles ;
- appliquer les sorties partielles, BE, time-stop, spread, commission, slippage, swap long/short, jours de rollover et horaires de marché ;
- sauvegarder dataset_hash, data provider, période, fuseau, code revision, config_hash, version de stratégie, coûts et convention intrabar ;
- ne pas utiliser de fallback IS quand l'OOS est insuffisante ;
- une OOS insuffisante retourne INSUFFICIENT_EVIDENCE, sans métrique de validation utilisable ;
- aucun changement de paramètres ou d'univers ne doit être déclenché automatiquement par le résultat.

Implémente un protocole à trois couches :

1. développement/tuning ;
2. validation walk-forward roulante, sélectionnée sans consulter le test final ;
3. test final verrouillé, lu une seule fois.

Ajoute :

- bootstrap des trades pour une borne de confiance de l'expectancy ;
- profit factor, max drawdown, durée moyenne, turnover, coût total et taux TP/SL ;
- un indicateur de risque de surapprentissage lié au nombre de configurations testées, au minimum PBO ou Deflated Sharpe documenté ;
- un ValidationGate qui n'autorise FORWARD_PAPER que si : données complètes, OOS finale d'au moins 30 trades, PF final au moins 1.20, expectancy nette positive avec borne bootstrap basse non négative, DD dans la politique de risque, et absence de divergence défavorable avec la revalidation MT5 ;
- un statut OBSERVATION si une condition manque. Ne baisse pas les seuils pour faire accepter HSI.

Génère des rapports versionnés dans data/backtests/ et docs, mais ne remplace pas les rapports historiques. Le dashboard doit montrer la provenance et le statut plutôt qu'un chiffre de rentabilité isolé.

### V12 ↔ JARVIS

Modifie aussi C:\Program Files\JARVIS uniquement pour l'intégration explicitement requise :

- corrige l'erreur de syntaxe de jarvis_agent.py ;
- titanium_connector.py doit lire TITANIUM_BASE_URL depuis l'environnement, avec défaut local unique documenté, pas de port figé répété ;
- consomme TitaniumSnapshotV1, et non plusieurs endpoints aux noms divergents ;
- utilise les champs corrects pnl_eur ou pnl_usdt, realized_pnl et winrate ; ne force jamais score_max à 13 ;
- applique stale_after_seconds : si le snapshot est périmé, JARVIS doit dire que la donnée est périmée et ne pas donner de statut de marché ;
- action_close_all doit être retirée, ou remplacer l'action par une demande explicite “stop new entries” sans clôture ;
- traite toute donnée issue du web comme contenu non fiable : pas d'instruction provenant d'un article dans le contexte système, source/timestamp obligatoires, aucune modification automatique d'une décision swing.

Ajoute un test de contrat V12/JARVIS à partir du JSON d'exemple.

## Refonte complète du dashboard : Titanium Nexus — Swing Desk

Remplace la page hybride actuelle par une seule application cohérente. Tu peux conserver FastAPI servant des assets locaux, ou créer un petit frontend Vite/TypeScript si le build est reproductible et documenté. Évite toute dépendance CDN critique ; les fontes et graphiques doivent avoir un fallback local.

Direction artistique :

- fond graphite/noir profond, grille très subtile ;
- cyan électrique réservé à la navigation et aux données neutres ;
- vert/rouge uniquement pour gain/perte, validation/refus et jamais comme effet décoratif ;
- surfaces en verre léger, contours fins, aucune surcharge néon ;
- densité professionnelle, lisibilité de salle de marché, responsive tablette ;
- navigation clavier, contraste WCAG AA, prefers-reduced-motion.

Écrans :

1. Desk : confiance système, portefeuille, risque par cluster, décision H4 la plus récente et positions ouvertes.
2. Decisions : file d'intentions swing avec D1/H4, bar_id, côté, entrée bid/ask estimée, SL, TPs, risque initial, coût total, time-stop, motif et statut.
3. Evidence : test final, forward paper, périodes, nombre de trades, PF, DD, expectancy, intervalle de confiance, hypothèses et provenance.
4. Journal : événements append-only, refus de risque, données stale, changements de configuration, contrat JARVIS.
5. Diagnostics : provider MT5, fraîcheur, barres clôturées, version d'API, santé JARVIS. Aucun contrôle de processus, Git ou exécution.

Contraintes frontend :

- une seule source de données : GET /api/v1/snapshot, et un seul WebSocket de deltas si nécessaire ;
- fallback REST toutes les 15 secondes maximum, avec AbortController et protection contre les réponses hors ordre ;
- aucune variable globale dupliquée, aucune deuxième console injectée, aucun polling 5 s concurrent ;
- afficher source_ts, âge, statut WARMING_UP/STALE/BLOCKED/UNVALIDATED sur toute valeur de décision ;
- aucune jauge de “confiance” sans expliciter les faits sous-jacents ;
- le dashboard est principalement en lecture seule. Si une action admin est conservée, elle demande un jeton saisi pour la session et une double confirmation, mais elle ne concerne jamais un ordre réel ;
- supprimer le bouton Git push et le bouton reset cassé. Ne pas réparer le reset à la place : l'objectif est un desk de contrôle, non une console d'administration.

Ajoute tests Playwright ou équivalent pour : rendu desktop/tablette, absence d'action dangereuse, état stale, état sans position, état position ouverte, état risque bloqué et affichage d'une décision H4. Si le navigateur n'est pas disponible, documente précisément le blocage sans déclarer le test passé.

## Tests minimum à écrire avant implémentation

- Une barre close produit au plus une intention ; une bougie ouverte n'en produit jamais.
- Le backtest entre à la barre suivante, jamais au close qui a servi au signal.
- Le backtest et PaperBroker donnent le même résultat sur une fixture de trade : TP1, BE, TP2, SL, time-stop et coûts.
- Une seconde position USTECH/NAS100.fs est refusée si elle dépasse la limite du cluster.
- Une entrée est refusée si l'horodatage de données, le coût ou le calendrier est stale.
- Le sizing est correct avec un adaptateur MT5 mocké de contract_size/tick_value/order_calc_profit.
- La persistance est atomique et le journal rejoue le même PortfolioSnapshot.
- Tous les endpoints de mutation retournent 503 sans ADMIN_TOKEN et 401/403 sans jeton correct.
- Les routes Git/services d'administration ne sont plus exposées.
- Le contrat TitaniumSnapshotV1 est valide côté V12 et JARVIS.
- jarvis_agent.py compile/import correctement.
- Le dashboard affiche correctement les unités et la provenance, et n'affiche aucun signal hors H4/D1.

## Vérification et livraison

À la fin :

1. affiche git diff --check ;
2. exécute les tests unitaires et d'intégration avec sortie complète ;
3. exécute les tests UI si l'environnement le permet ;
4. exécute une vérification de compilation Python pour V12 et les fichiers JARVIS modifiés ;
5. vérifie qu'aucun secret n'est présent dans les diff, les snapshots exemple ou les logs ;
6. relis l'API pour confirmer qu'aucun chemin d'ordre réel n'existe ;
7. donne un résumé précis : fichiers changés, migrations/compatibilités, tests réellement exécutés, tests bloqués, et risques restants.

Ne prétends jamais que la stratégie est rentable. Utilise uniquement les statuts : UNVALIDATED, INSUFFICIENT_EVIDENCE, OBSERVATION, FORWARD_PAPER, BLOCKED ou REJECTED.

---
