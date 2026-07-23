# Audit V12 — fiabilité, swing-only, risque et dashboard

Date : 10 juillet 2026
Périmètre : V12 local, données et rapports disponibles, intégration JARVIS dans C:\Program Files\JARVIS.
Nature : audit de conception et de code en lecture seule ; aucun ordre réel, aucune clé ni variable secrète consultée.

## Décision de synthèse

V12 ne doit pas être présenté comme rentable, ni promu vers le réel dans son état actuel.

Le projet a des éléments prometteurs : les revalidations natives MT5 sur USTECH et NAS100.fs sont nettement meilleures que les simulations Python, et le moteur swing travaille déjà en paper. Mais il subsiste quatre blocages majeurs :

1. trois moteurs indépendants cohabitent alors que la cible est le swing-only ;
2. le risque de portefeuille n'est pas centralisé et deux indices très corrélés ont déjà été ouverts pour environ 94 % du capital notionnel paper ;
3. les backtests qui alimentent le moteur crypto et l'optimiseur ne reproduisent pas la stratégie ni les coûts d'exécution du live ;
4. l'API expose des opérations d'administration et de push Git sans authentification alors que l'hôte par défaut écoute sur toutes les interfaces réseau.

La cible recommandée est un seul produit : un simulateur paper swing H4, piloté par données MT5, avec portefeuille unique, univers explicitement validé, critères de preuve versionnés, et dashboard orienté décision/risk rather than “signal theatre”.

## Éléments vérifiés

- Code V12 : API FastAPI, moteurs signal/scoring/forex/swing, exécution paper, garde-fous, tests, optimisateurs et dashboard.
- Données : états paper, historique de signaux, rapports d'optimisation, rapports MT5 et configurations d'actifs.
- JARVIS : connecteur Titanium, boucle de contexte, commandes vocales, frontend/bridge et scripts de revue.
- Vérification syntaxique : 182 fichiers Python V12 + JARVIS examinés ; une erreur de syntaxe réelle dans C:\Program Files\JARVIS\jarvis_agent.py, ligne 77.
- Tests : impossibles à exécuter dans l'état de l'environnement. Le venv pointe vers C:\Users\flore\AppData\Local\Programs\Python\Python312\python.exe, absent ; aucun interpréteur Python système n'est disponible ; le runtime de secours n'a pas pytest.

Les modifications déjà présentes dans le répertoire de travail ont été préservées.

## Lecture honnête des résultats

### Ce qui est étayé

Le rapport de revalidation MT5 natif sur 3,5 ans est la meilleure preuve actuellement disponible :

| Statut | Actif / horizon | Résultat rapporté | Décision de l'audit |
|---|---|---:|---|
| Tier A | USTECH, swing H4 | PF 1,66 ; Sharpe 2,30 ; DD 15,3 % | Forward paper admissible, mais pas réel |
| Tier A | NAS100.fs, swing H4 | PF 1,84 ; Sharpe 2,50 ; DD 7,2 % | Forward paper admissible, mais pas réel |
| Tier B | HSI.fs, swing H4 | PF 1,22 ; Sharpe 0,75 ; DD 7,0 % | Observation paper, pas de promotion automatique |
| Rejet | XAUUSD, swing H4 | PF Python 2,31 puis PF MT5 0,90 | Exclure du swing actif |
| Hors cible | EURUSD/GBPUSD, H1 | résultats MT5 positifs | Ne pas activer : la directive est swing-only |
| Rejet | BTCUSD CFD, H1 | PF 0,99 malgré 73,2 % de réussite | Exclure |

La divergence XAUUSD est précisément le signal d'alerte recherché : une apparente performance OOS Python s'est effondrée une fois confrontée au modèle de fills, spreads et swaps du tester MT5.

### Ce qui n'est pas démontré

- Le fichier data/swing_paper_state.json montre deux positions ouvertes, USTECH et NAS100.fs, mais aucun trade swing fermé. Aucune rentabilité forward ne peut donc être calculée.
- data/strategy_lab_report.json ne contient qu'un rapport SOL, alors que la version courante de tools/strategy_lab.py déclare un univers différent. Ce résultat n'est pas reproductible par le code actuel sans reconstruire le jeu de données et le commit exacts.
- Les PF/Sharpe affichés par les outils Python ne doivent pas être utilisés comme preuve de rentabilité. Le choix de modèles et d'actifs sur une même OOS augmente le risque de data-snooping. Voir [Bailey et al., The Probability of Backtest Overfitting](https://escholarship.org/uc/item/4w1110bb).
- Toute communication externe de performance hypothétique doit rester explicitement qualifiée ; la réglementation applicable dépend du pays et du statut de l'émetteur. La CFTC rappelle les limites inhérentes aux résultats simulés/hypothétiques dans [sa règle 4.41](https://www.cftc.gov/LawRegulation/FederalRegister/FinalRules/e7-3122.html).

## Anomalies et corrections prioritaires

### P0 — à traiter avant tout nouveau scan ou forward paper

| Constat | Preuve | Risque | Correction attendue |
|---|---|---|---|
| API d'administration exposée | UVICORN_HOST vaut 0.0.0.0 par défaut. POST /services/github/push lance git add ., commit et push ; les routes start/stop, reset, scan, approval et certains services n'ont pas d'authentification. | Une personne sur le réseau local peut réinitialiser des données, démarrer des services ou pousser des changements non désirés. Le bouton dashboard “Push” utilise en plus la branche par défaut. | Désactiver/supprimer les routes d'administration web ; lier l'API à 127.0.0.1 ; exiger un jeton administrateur sans valeur par défaut pour toute mutation conservée ; supprimer le push Git du dashboard. |
| Le moteur swing contourne le portefeuille commun | core/swing_engine.py possède son propre état, sizing, persistance et sorties ; il ne passe ni par execution.guards ni par PaperEngine. | L'état actuel porte USTECH et NAS100.fs à environ 47 % + 47 % du capital notionnel. Ces indices sont corrélés ; aucune limite globale, de cluster, de marge, de frais ou de perte quotidienne n'est appliquée. | Unifier les positions, la valorisation, les limites et le journal dans un PortfolioRiskService unique. Limiter le risque initial agrégé du cluster US indices avant l'ouverture de la seconde position. |
| V12 n'est pas swing-only | signal_engine scanne le crypto toutes les 5 s avec critères 1m/5m/15m ; forex_engine décide en H1 ; asset_configs contient BTCUSD et XAGUSD en intraday ; opportunity_scan peut auto-ajouter des actifs. | Les performances, risques et alertes de stratégies incompatibles sont mélangés. Une “suggestion” peut encore provenir d'un flux court terme. | Désactiver ces boucles par défaut, les sortir du chemin d'exécution, retirer l'auto-intégration et n'exposer que les décisions D1/H4 sur barres clôturées. |
| Les deux principaux backtests ne sont pas fidèles au live | engine/optimizer.py utilise EMA 5/20 et prix de clôture, tandis que le moteur réel utilise un score SMC 16 critères ; il ferme au premier TP sans sorties partielles/BE/time stop et ignore le champ trailing. | Les paramètres SL/TP optimisés ne sont pas validés pour la logique réellement exécutée. Les gains peuvent être artificiels. | Une fonction de stratégie pure, unique, doit servir au live paper et au backtest. L'entrée doit être la prochaine ouverture/bid-ask disponible après la clôture de la barre. |
| Coûts sous-estimés dans l'optimiseur crypto | optimizer.py prend 4 bps, alors que le paper engine applique frais, slippage et spread par côté. | L'OOS peut passer avec une marge qui disparaît au coût paper. | Modéliser frais, spread, slippage et funding historiques ; refuser toute validation si ces séries ne sont pas disponibles ou si l'hypothèse est plus optimiste que le forward paper. |

### P1 — nécessaire pour une mesure fiable

| Constat | Effet | Correction attendue |
|---|---|---|
| Fallback IS déguisé en OOS | Quand l'OOS est insuffisante, optimizer.py reporte le résultat IS pénalisé, tout en exposant des métriques de validation. | Retourner UNVALIDATED, sans Sharpe/PF promotionnels ni paramètres utilisables. |
| Sélection répétée sur l'OOS | asset_optimizer choisit d'abord des actifs avec l'OOS, puis réutilise cette même période pour une optimisation profonde et la sélection finale. | Créer trois segments temporels : développement, sélection/validation, test final verrouillé. Ajouter walk-forward roulant, bootstrap des résultats et mesure de PBO/Deflated Sharpe. |
| Échantillons trop faibles | Plusieurs configs validées reposent sur 12 à 16 trades OOS ; l'ETHUSD swing a 16 trades et 2 356 bps de DD. | Définir un seuil de trades et une borne de confiance minimale ; à défaut, afficher “observation”, pas “validé”. |
| Garde-fous désactivés | GUARD_CORRELATED_EXPOSURE_ENABLED et GUARD_BLACKOUT_ENABLED sont à 0 par défaut. | Activer les garde-fous utiles au swing, les alimenter par calendrier versionné et bloquer en cas de donnée absente/obsolète. |
| Décisions sur bougies potentiellement ouvertes | Les fetches multi-timeframe et le score SMC utilisent la dernière ligne sans contrat explicite “bar close”. | Fournir bar_end, is_closed et sequence_id ; n'évaluer les signaux qu'une fois par barre clôturée. |
| Warm-up synthétique trompeur | _seed_candle_store découpe une bougie 1m en deux pseudo-bougies 30 s avec le même high/low. | Ne jamais autoriser ces données à déclencher un signal ; afficher l'état WARMING_UP jusqu'à réception de vraies données. |
| Limitation REST insuffisante | scan_symbol récupère 8 horizons pour chaque symbole toutes les 5 s sans budget/retour 429 centralisé. | Mettre en cache par clôture de timeframe, appliquer un budget et un backoff. Binance impose des poids par requête et répond 429/418 en cas de dépassement : [documentation officielle](https://developers.binance.com/en/docs/products/spot/rest-api). |
| Apprentissage adaptatif peu interprétable | Les poids changent de 0,05 puis le score est arrondi à un entier et plafonné à 16. Les évolutions peuvent ne pas avoir d'effet mesurable. | Désactiver l'apprentissage online durant le forward paper ou le traiter comme une expérience versionnée, avec score continu normalisé et test hors échantillon. |
| Persistance JSON non atomique | swing/forex/paper écrivent directement les états. | Écrire dans un fichier temporaire puis remplacer atomiquement ; versionner le schéma et conserver un journal append-only cohérent. |
| Aucun dédoublonnage par barre pour swing/forex | Après une fermeture, le signal de la même barre clôturée peut rouvrir une position au scan suivant. | Stocker le bar_id traité et un cooldown par stratégie/actif ; une intention de trade par barre clôturée. |
| Sizing forex/swing simplifié | notional = risque / distance relative ; aucun contract_size, tick_value, devise de profit, marge ni conversion EUR. | Calculer le volume via les métadonnées MT5 et order_calc_profit ou un équivalent mockable. |

### P1 — intégration JARVIS

| Constat | Effet | Correction attendue |
|---|---|---|
| jarvis_agent.py ne compile pas | La chaîne JARVIS concernée ne peut pas se lancer. | Corriger la chaîne mal formée à la ligne 77 puis ajouter un test de compilation/import. |
| Contrat de données incohérent | titanium_connector demande total_pnl et winrate_pct, alors que PaperEngine expose realized_pnl et winrate. Il force aussi score_max à 13 alors que V12 est à 16. | Définir TitaniumSnapshot v1 avec version, timestamp, freshness, PnL, unités et provenances ; valider côté V12 et JARVIS. |
| Adresse et port figés | Le connecteur et le dashboard JARVIS visent localhost:8090, alors que le défaut V12 est 8080. | Une seule variable d'intégration non secrète, vérifiée au démarrage ; aucune URL ni port en dur dans le frontend. |
| Commande close-all inexistante | JARVIS appelle /paper/close/all, endpoint absent. | Retirer la commande ou l'implémenter seulement derrière confirmation explicite + token + test. Pour la cible paper swing, privilégier une action “stop new entries” plutôt qu'une fermeture groupée. |
| Fraîcheur non appliquée | _CONTEXT_MAX_AGE est déclaré mais pas utilisé ; JARVIS peut décrire un cache comme temps réel. | Insérer source_ts, received_ts et stale_after dans toutes les réponses vocales et visuelles. |
| Données web externes envoyées au LLM | Le résumé d'actualité traite du contenu de recherche comme une source de contexte. | Marquer ces contenus non fiables, retirer toute instruction, exiger source/timestamp, et ne jamais les laisser modifier une décision de trading. |

### P2 — qualité du dashboard et exploitabilité

- Le fichier titanium_v12_dashboard.html contient plusieurs consoles superposées, plusieurs boucles de polling et des variables globales répétées. La maintenance devient fragile.
- Le bouton “Reset compte” envoie POST /paper/reset sans le header X-Reset-Confirm requis ; l'interface annonce donc une action qui échoue.
- Le dashboard mélange signaux crypto courts, paper crypto, forex, swing, JARVIS, Base44, Git, GitNexus et services locaux. Le trader ne sait pas quelle stratégie ni quelle source produit un chiffre.
- Les widgets rendent un score SMC comme une jauge de conviction mais n'affichent pas systématiquement la date de clôture de la barre, l'âge du flux, le coût estimé, le risque de portefeuille, ni le statut de validation.
- Les appels périodiques concurrents à /api/state, /paper/* et aux endpoints JARVIS créent des états d'écran incohérents et une charge inutile.
- Les fontes et Chart.js viennent de CDN : prévoir un mode local/offline et une CSP lorsque l'interface devient un poste de décision.

## Architecture cible recommandée

    Données MT5 H4/D1 clôturées
             |
    SwingRules (fonction pure, versionnée)
             |
    TradeIntent unique par actif/barre
             |
    PortfolioRiskService (capital, cluster, DD, calendrier, frais)
             |
    PaperBroker (bid/ask, swap, commissions, partials, journal)
             |
    Snapshot API v1 en lecture
          /        |        \
    Dashboard   JARVIS   Backtest identique

Le seul univers actif par défaut doit être :

- USTECH et NAS100.fs : forward paper contrôlé, mais un seul cluster “US_INDICES”.
- HSI.fs : observation paper, ou activation manuelle explicite seulement.
- Tout autre actif : DISABLED, avec motif de rejet ou absence de preuve.

Le bot ne doit produire qu'une intention swing : biais D1/H4, signal H4 sur barre clôturée, durée attendue de plusieurs barres et étiquette de validité. Il ne doit ni scalper, ni suggérer de position intraday, ni passer d'ordre réel.

## Protocole de validation avant toute promotion

1. Geler l'univers, les règles et les coûts dans un fichier de configuration versionné.
2. Reproduire les trois stratégies H4 avec la même fonction que le paper engine.
3. Conserver un test final jamais consulté pendant le choix des actifs/paramètres.
4. Pour chaque actif, afficher : période, source, hash de données, commit, hypothèses de coût, nombre de trades, PF, expectancy, DD, intervalles bootstrap et statut.
5. Qualifier “VALIDATED_FOR_FORWARD_PAPER” seulement si tous les seuils de robustesse sont respectés. Une OOS insuffisante devient “INSUFFICIENT_EVIDENCE”, jamais un fallback IS.
6. Exiger au minimum 12 semaines et 30 sorties forward paper, puis comparer slippage, durée, taux TP/SL et PnL aux intervalles du modèle. Le seuil temporel ou statistique le plus long s'applique.
7. Rester en paper après tout écart significatif, tout problème de données, toute violation de limite, ou toute modification de règles.

## Refonte dashboard : “Titanium Nexus — Swing Desk”

Le design doit être futuriste mais sobre : noir graphite, bleu électrique contrôlé, vert/rouge réservés aux états de risque et non aux effets décoratifs. Une seule application, une seule source de vérité, aucune action Git/service/exécution réelle dans l'interface.

Écran principal :

1. Barre de confiance : mode PAPER ONLY, fraîcheur MT5, dernière clôture H4, connectivité JARVIS, version du snapshot, kill-switch.
2. Radar portefeuille : equity, cash, risque initial agrégé, exposition brute, exposition par cluster, DD courant/max, budget journalier restant.
3. File de décisions : maximum trois cartes, chacune avec actif, D1/H4, bar_id, côté, entrée bid/ask estimée, SL, TPs, risque, ratio net, coût, preuve et statut “validé / observation / bloqué”.
4. Cycle de vie des positions : étapes entrée, TP1, BE, TP2, sortie ; PnL net et coûts séparés.
5. Preuve de stratégie : résultats validés, période, nombre de trades, PF, DD, incertitude, statut de revalidation MT5. Aucune courbe ne doit masquer un échantillon faible.
6. Journal d'audit : événements de risque, refus, données obsolètes, changement de configuration et décisions JARVIS.
7. Mode diagnostic : état de chaque provider et contrat V12 ↔ JARVIS. Ce mode remplace les multiples panneaux réseau actuels.

Règles UX :

- WebSocket de snapshots/deltas unique ; fallback REST unique, lent et annulable.
- Afficher l'âge et la provenance de chaque valeur sensible.
- États vides, WARMING_UP, STALE, BLOCKED et UNVALIDATED explicites.
- Navigation clavier, contrastes AA, prefers-reduced-motion, responsive tablette.
- Zéro promesse de profit, zéro recommandation de position hors swing.

## Ordre recommandé d'exécution

1. Isoler et sécuriser l'API, supprimer les actions dangereuses du dashboard.
2. Désactiver les moteurs hors swing et l'auto-ajout.
3. Construire le portefeuille, le modèle de coût et le contrat de données swing.
4. Réécrire le backtest autour des règles réellement exécutées et geler la validation.
5. Corriger et contractualiser JARVIS.
6. Remplacer le dashboard par Titanium Nexus.
7. Réparer l'environnement de test, puis ajouter les tests de non-régression et les parcours UI.

La spécification exécutable correspondante est dans docs/PROMPT_CLAUDE_CODE_REFONTE_V12_SWING.md.
