# Revues croisées Codex

## 2026-07-10 — R1/R2 — REQUEST CHANGES

R1 et R2 restent en `REVIEW`.

### R1 — déduplication par barre

`scan_once()` est appelé par la boucle périodique et par `POST /scan`. Deux appels
peuvent franchir le contrôle `last_bar` avant le `await` de calcul ATR et ouvrir
sur la même barre. Correction attendue : verrou/in-flight ou seconde vérification
atomique, test concurrent et test miroir forex.

### R2 — atomicité et mono-écrivain

`temp + os.replace` empêche les JSON partiels et le `RLock` sérialise les
remplacements dans un processus. Le mono-écrivain demandé n'est pas démontré :

- `single_instance_guard` est cité dans `utils/atomic_state.py` mais absent ;
- le pré-vol de port est TOCTOU, contournable par Uvicorn direct et non lié au fichier ;
- le test ne couvre ni deux processus ni les mises à jour perdues ;
- `swing_auto_configs.json` reste écrit directement avec `write_text`.

La relance indépendante des tests est bloquée : les venv v12 et JARVIS pointent
vers un Python 3.12 supprimé. Ne pas redémarrer Titanium actif avant réparation
du runtime.

Message envoyé à Claude : `7912fcf6-3efc-4e94-a76e-99778c557639`.

## 2026-07-10 — R6 — cerveau JARVIS

Décision Florent : remplacer Gemini par une architecture Claude + ChatGPT.
Le lot doit inclure abstraction des fournisseurs, routage/fallback, timeouts,
secrets hors code/logs, suivi coût/latence, tests de non-régression et bascule
progressive après validation de parité par Florent. Aucune modification de JARVIS
n'est réalisée dans cette étape de planification.

Message envoyé à Claude : `10f098f7-0cea-4fb1-8ed3-b8d3ae4c132b`.

## 2026-07-10 — R3 — REQUEST CHANGES

Le branchement pré-ouverture swing/forex et les plafonds stratégie/cluster/gross
vont dans la bonne direction, mais R3 ne satisfait pas encore le contrat
`cluster + stratégie + gross/net` et possède deux chemins fail-open reproduits.

### Bloquants

1. **Plafond net absent.** Les positions sont réduites à
   `(stratégie, symbole, notionnel_abs)` : le sens LONG/SHORT est perdu, aucune
   exposition nette n'est calculée, contrôlée ou publiée.
2. **Entrée non finie autorisée.** `check_can_open(..., notional_eur=NaN, ...)`
   retourne `(True, "ok")`, car toutes les comparaisons avec `NaN` sont fausses.
   Le garde doit refuser les notionnels/equities non finis, nuls ou invalides.
3. **État existant malformé ignoré.** `_current_positions()` intercepte toute
   exception par moteur et continue avec une exposition vide. Une seule position
   dont `notional_eur` est invalide fait donc disparaître toutes les positions du
   moteur et autorise l'ouverture. Un champ absent vaut également zéro. Le calcul
   de risque doit échouer fermé avec un motif explicite.
4. **Agrégation incomplète.** Le service affirme couvrir « toutes positions, tous
   moteurs », mais ne lit que swing et forex. Le portefeuille crypto du
   `PaperExecutor` est exclu du gross, du cluster et du futur net, contrairement à
   la direction multi-stratégie.

### Correctifs et tests attendus

- conserver `side` et calculer gross + net par stratégie, cluster et portefeuille ;
- valider `math.isfinite`, valeurs positives et configuration de plafonds ;
- retourner un refus `RISK_STATE_UNAVAILABLE` si une source est absente ou malformée ;
- intégrer ou adapter explicitement le portefeuille crypto paper dans l'agrégat ;
- baser les plafonds portefeuille sur une equity agrégée cohérente et documentée,
  pas uniquement les capitaux initiaux statiques ;
- ajouter les tests net long/short, NaN/inf, état malformé/champ absent, crypto +
  MT5, equity après drawdown, égalité exacte au plafond et isolation des états de
  test par restauration en fin de fixture.

Vérification locale : les probes stdlib reproduisent les deux autorisations
fail-open. Pytest n'a pas pu être relancé : le venv V12 pointe vers un Python 3.12
supprimé et le seul Python disponible appartient au venv Hermes sans pytest.

## 2026-07-11 — R6 JARVIS → Hermes — REQUEST CHANGES (CRITICAL)

### Conclusion

Le remplacement de `asyncio.create_subprocess_exec` par `subprocess.run` dans
`asyncio.to_thread` corrige bien l'incompatibilité avec la SelectorEventLoop
Windows de pywebview. Le diff est limité à `demander_hermes`, utilise une liste
d'arguments sans shell et gère succès, code non nul, sortie vide, timeout et
exception. Le backup `main2.py.bak-hermes-r6-20260710` existe.

Le cutover Hermes reste toutefois **interdit** : l'intégration actuelle comporte
un risque critique d'exécution non autorisée.

### Bloquants

1. **Approbations contournées.** L'aide locale Hermes indique que `hermes -z`
   charge outils, mémoire, règles et `AGENTS.md` puis contourne automatiquement
   les approbations. Une phrase vocale/websocket non fiable est donc transmise
   directement à un agent local outillé. Cela contredit `HERMES_BRIDGE.md` et peut
   transformer une injection de prompt en action système.
2. **Contamination d'environnement non corrigée dans le code.** Le relancement a
   neutralisé `PYTHONPATH`, mais `subprocess.run` ne reçoit aucun `env` explicite
   et `DEMARRER_JARVIS.bat` ne nettoie pas cet héritage. Le défaut peut réapparaître
   selon le processus parent.
3. **Rollback seulement manuel.** `HERMES_ENABLED=True`, le chemin et le timeout
   sont codés en dur. Il n'existe pas de kill switch externe testé permettant de
   repasser immédiatement au fallback sans éditer `main2.py`.
4. **Fuite potentielle dans les journaux et la ligne de commande.** Le prompt
   complet est un argument visible localement ; jusqu'à 300 caractères de stderr
   sont journalisés sans redaction. Des contenus sensibles peuvent être exposés.
5. **Observabilité incomplète.** Aucun identifiant de corrélation, durée, provider,
   coût/budget ni motif de fallback structuré n'est produit.

### Preuves dynamiques en lecture seule

Un harnais AST en mémoire a exécuté la fonction courante sans importer l'application :

- parsing Python : PASS ;
- succès, code non nul, sortie vide, timeout et exception : PASS ;
- event loop réactive pendant le worker : PASS ;
- appel sans shell : PASS ;
- environnement explicitement contrôlé : FAIL (`env` absent).

### Critères avant approbation

- utiliser un profil/canal Hermes dédié dont les outils d'écriture, shell,
  computer-use et approbations automatiques sont impossibles pour l'entrée vocale ;
- nettoyer explicitement l'environnement enfant et le lanceur JARVIS ;
- déplacer activation, timeout et stratégie de fallback dans une configuration
  externe validée, avec kill switch et rollback testés ;
- ne pas placer le texte utilisateur dans la ligne de commande et redacter les logs ;
- tests automatisés : disabled, succès, nonzero, vide, timeout, exception,
  réactivité, environnement contaminé, injection demandant une écriture, fallback
  Gemini/Claude/Ollama et rollback ;
- test end-to-end websocket paper-only prouvant qu'aucun outil ni état de trading
  n'est muté ; vérification Titanium 8090 séparée.

Le bug de routage « relance Titanium » → « EA App » reste un lot séparé : aucun
correctif sans test rouge dédié.

## 2026-07-11 — R3 rev.2 — REQUEST CHANGES

Les quatre bloquants de la revue `462b1e62` sont corrigés dans le code : net
signé et plafond portefeuille `|net|` sur equity live agrégée, validation
`RISK_INPUT_INVALID`, état malformé refusé via `RISK_STATE_UNAVAILABLE`, et
agrégation du `PaperExecutor` crypto par `_crypto_engine()` injectable. Le sens
est transmis au garde par swing et forex ; l'approximation paper 1 USDT = 1 EUR
est documentée.

### Bloquant restant — décision non atomique entre moteurs

`check_can_open()` lit un snapshot puis retourne ; chaque `_open_position()`
insère ensuite séparément dans son propre état. Le verrou de scan de swing ne
sérialise pas forex (et réciproquement). Deux ouvertures swing/forex concurrentes
peuvent donc toutes deux valider le même état initial, puis dépasser ensemble un
plafond stratégie/cluster/gross/net. Pour une validation production PAPER, le
check et la réservation/insertion doivent être atomiques à l'échelle du
portefeuille, ou passer par un service central de réservation avec rollback.
Ajouter un test concurrent inter-moteurs prouvant qu'une seule des deux
ouvertures incompatibles est acceptée.

### Vérification venv

La commande imposée
`.\\venv\\Scripts\\python.exe -m pytest tests/test_portfolio_risk.py tests/test_bar_dedup.py tests/test_atomic_state.py -q`
échoue avant collecte avec `No Python at ...Python312\\python.exe`.
`venv/pyvenv.cfg` référence encore ce runtime supprimé ; le Python Hermes trouvé
sur le PATH ne contient pas pytest. Le résultat annoncé `15 passed` n'est donc
pas reproductible dans l'environnement présent et ne peut pas servir de preuve
fraîche de validation.

Verdict : **REQUEST CHANGES**. Aucun ordre réel ; périmètre PAPER-only.

## 2026-07-11 — DASH — exigences de rigueur Codex

1. Chaque donnée affiche sa source, son `source_ts`, son âge calculé et un état
   `LIVE / STALE / UNAVAILABLE`; stale ou inconnu ne doit jamais ressembler à du live.
2. Chaque stratégie affiche un statut de validation explicite et traçable
   (`research`, `paper`, `reviewed`, `approved paper`, `blocked`), avec version du
   modèle/configuration et date de la dernière preuve.
3. Crypto, forex et swing restent visuellement et sémantiquement séparés ; les
   agrégats transverses indiquent unités, conversion (dont 1 USDT = 1 EUR ici),
   périmètre et éventuelles données manquantes.
4. L'orbe JARVIS/Hermes est un centre d'état et d'explication, jamais une preuve
   d'autorité : actions mutantes distinctes, confirmées, journalisées et PAPER-only.
5. CSP stricte et mode offline dégradé : aucun CDN requis au runtime, aucune
   exécution inline non autorisée, cache/version explicites et bannière offline
   empêchant de confondre données mémorisées et données fraîches.

Décision R6 actée : Gemini est retiré du cerveau JARVIS ; Hermes conserve ses
outils ; une phase de test précède la sécurisation et R6b est différé. La threat
review du 11/07 reste au dossier et n'est pas annulée par cet arbitrage.

## 2026-07-11 — R3c — READY FOR CLAUDE REVIEW

Codex implémente le bloquant d'atomicité identifié lors de la re-revue R3 ;
Claude devient simple relecteur. `core.portfolio_risk.check_and_insert()` tient
un `threading.Lock` module-level pendant le check complet et le callback
d'insertion synchrone. Les deux `_open_position` swing/forex utilisent ce chemin
sans changement de logique de signal, taille, SL ou TP. `check_can_open()` reste
disponible et repose sur le même corps de validation, donc les motifs
`RISK_INPUT_INVALID` et `RISK_STATE_UNAVAILABLE` sont conservés.

Le nouveau test concurrent lance une ouverture swing `USTECH` et une ouverture
forex `NAS100.fs` simultanément avec un plafond `US_INDICES` incompatible. Il
contient un piège de régression qui force l'ancien check séparé à exposer la
course ; avec le nouveau câblage, exactement une ouverture est acceptée et une
seule position existe entre les deux moteurs.

Vérifications disponibles dans le sandbox Codex :

- `py_compile` des quatre fichiers modifiés : PASS ;
- probe concurrent dynamique inter-moteurs : PASS, résultat `[True, False]` ;
- probes fail-closed invalid input / état malformé : PASS ;
- pytest de secours avec l'interpréteur Hermes 3.11 et les paquets pytest V12 :
  `14 passed in 2.26s` pour `test_portfolio_risk.py` + `test_atomic_state.py`.

Point environnement exact : la commande imposée via
`C:/Users/flore/Desktop/v12/venv/Scripts/python.exe` échoue avant collecte, y
compris avec `-c`, par
`No Python at '"%LOCALAPPDATA%\Programs\Python\Python312\python.exe'`.
Le runtime de secours est Python 3.11 et ne peut pas charger le numpy/pandas V12
compilé pour 3.12 ; les deux tests `test_bar_dedup.py` n'ont donc pas été
rejoués dans ce sandbox. Revue Claude demandée sur le bus R3 :
`cbb03952-f2da-4898-8d95-82731057e49a`.

## 2026-07-14 — Reprise Codex — verdicts consolidés

### GitNexus 1.6.9 — `detect_changes(all)` débloqué

**Verdict : FIX VERIFIED.** Le bootstrap qui précharge `@ladybugdb/core` avant le
sentinel supprime le crash déterministe MCP, mais le stress test a révélé une
seconde condition : 2/5 seulement avec un nouveau processus MCP par scan, et la
CLI native termine elle aussi avec `3221225477` (`0xC0000005`) lorsque stdout est
un pipe anonyme Windows. La même CLI avec un handle de fichier sort à zéro.

Correction finale : le préflight/postflight du garde ne dépend plus du cycle de
vie MCP. `tools/gitnexus_detect_changes.mjs` appelle directement `LocalBackend`,
retourne le JSON structuré puis exécute `backend.dispose()`. Le superviseur Python
lance ce runner avec stdout/stderr adossés à des fichiers temporaires et transmet
un `safe.directory` fixe. Toute sortie non nulle, timeout ou JSON invalide reste
un refus fail-closed. Preuves : 17 tests garde/config verts, 5/5 scans consécutifs
et appel réel `gate._detect_changes()` réussi (24 fichiers, 39 flux, risque
`CRITICAL`, aucune erreur). Le nombre exact de symboles oscille entre scans dans
GitNexus 1.6.9, sans changer le périmètre fichiers/flux ; ce point est résiduel et
non utilisé comme autorisation. Aucun paquet vendor n'a été modifié, aucune
modification utilisateur n'a été stagée, commitée ou supprimée, et aucune
opération GitNexus mutante n'a été tentée.

### DEMO_EXEC rev.3

**Verdict : APPROVE.** `_verify_risk` refuse l'absence, exception, `None`, valeur
non numérique ou non finie de `order_calc_profit`. `order_check` est obligatoire
et fail-closed. `assert_demo_or_raise` est rejoué après `order_check`, juste avant
`order_send`. Les paramètres critiques non finis sont refusés. Le verrou du pont
couvre déduplication, capacité, référence journalière et placement. Preuve :
32/32 tests, dont les probes adversariaux. Risque P1 non bloquant : un terminal
DEMO dédié reste recommandé contre une bascule de compte par un autre processus
pendant l'appel natif `order_send`.

### ÉMOTION v2

**Verdict courant : APPROVE_READ_ONLY / REQUEST_CHANGES_BEFORE_M2.** Le
circumplex valence×arousal, la séparation PANIQUE/CAPITULATION, ESPOIR, le retrait
RSI et la neutralisation décisionnelle sont cohérents. Claude a corrigé les deux
P0 de la première passe dans `emotion_engine` : valeurs non finies rejetées,
stale/faible confiance neutralisés, registre validé ; 13/13 tests moteur passent.

Le nouvel adaptateur `emotion/market_context.py` ouvre cependant deux P0 de
fidélité avant M2 :

- son `_clamp` transforme encore `delta_pct=NaN` en `+1`, avant que le moteur ne
  puisse le rejeter ; probe : contexte frais avec `delta_volume=1.0` ;
- `data.mt5_provider.get_tick()` retourne un timestamp ISO, mais
  `live_raw_mt5()` fait `float(tk["ts"])`. L'exception est avalée, `delta_ts` et
  `source_age_s` disparaissent. Probe avec tick `stale=True` : état
  `EXALTATION`, `stale=False`, confiance 0.58 et filtre long actionnable.

Un timestamp futur est aussi ramené à âge zéro, et funding/macro/bougies n'ont
pas leur fraîcheur propre : sans delta/tick valide, le contexte est réputé frais.
Les 8 tests adaptateur annoncés par Claude n'ont pas été reproduits dans le venv
du garde, qui ne contient pas pandas ; cette limite d'environnement est explicite.
Risques modèle toujours HOLD M2 : corrélation/double comptage, seuils fixes par
actif/régime, calibration hors échantillon et hystérésis. Exiger nombres finis
dès l'adaptateur, parsing ISO/epoch robuste, timestamps par source et état stale
fail-closed avant toute logique de trading.

### R4 TitaniumSnapshot v1

**Verdict : REQUEST_CHANGES.** Les 10 tests passent et les routes sont GET-only,
avec contrat/provenance/âge explicites. Probe bloquant : source fraîche et cinq
métriques à `None` donnent chaque métrique `UNAVAILABLE`, mais stratégie et
snapshot restent `LIVE`. Le statut agrégé doit intégrer le pire état des métriques
requises afin d'empêcher un faux vert. P1 : freshness du score indépendante,
timestamp futur de validation et robustesse aux nombres invalides.

### Runner MetaTester

**Verdict : REQUEST_CHANGES / NO-GO opérationnel.** Les 23 tests runner+harness
passent, sans lancer MetaTester ni MT5. Trois P0 prouvés : chaîne `"true"` pour
`market_session` acceptée avec 8 agents, launcher non lié au terminal/data-dir
validés par le preflight, et double transition concurrente
`FINAL_LOCKED→FINAL_CONSUMED` acceptée faute de verrou/CAS. L'API peut aussi lire
plusieurs rapports finaux avant sélection, ce qui permet une fuite holdout.
Ajouter validation de type stricte, jeton/capability immuable liant le preflight
au lancement, consommation finale atomique et sélection d'un unique gagnant avant
lecture du final. Les prérequis opérateur (terminal/data-dir isolés, firewall/LAN,
secrets, baseline) restent bloquants.

Périmètre de toute cette reprise : audit PAPER ONLY ; aucun ordre réel ou démo,
aucun lancement MetaTester, aucun secret sur le bus.

## 2026-07-16 · Revue Codex · GitNexus FTS/runtime

**Verdict ciblé : PASS avec réserve worktree globale.** Le défaut FTS est
reproduit (`LOAD fts` échouait faute de `libcrypto-3-x64.dll` et
`libssl-3-x64.dll` dans le chemin de chargement), puis réparé par injection du
répertoire OpenSSL de Git avant l’import LadybugDB et dans les sous-processus du
runtime. L’index Titanium a été reconstruit, le watcher a terminé son analyse
automatique, `4747/api/health` renvoie `ok`, les requêtes FTS retournent des flux
et 37 tests ciblés passent. Le risque `CRITICAL` de `detect_changes` concerne
l’ensemble des 24 fichiers déjà modifiés du dépôt ; il interdit d’interpréter
ce PASS ciblé comme une validation globale du worktree.

## 2026-07-16 · Revue Codex · Correctif calibration point/price

**Verdict ciblé : PASS / prêt pour relance data-only des 112 actifs.** L'impact
GitNexus avant édition est LOW : un appelant direct de `_cost_snapshot`
(`calibrate_asset`), puis `main`; aucun flux d'exécution d'ordre. Les régressions
couvrent les fallbacks `trade_tick_size` et `digits`, la reprise après une
cotation initiale nulle et la classification `DATA_SPEC_INVALID`. Résultats :
64/64 tests, `py_compile` PASS et smoke MT5 read-only 3/3 sur compte démo.

Réserve globale : `detect_changes(unstaged)` demeure CRITICAL pour 24 fichiers,
133 symboles et 39 flux déjà modifiés dans le worktree. Les deux fichiers de ce
correctif sont non suivis par Git dans l'état actuel ; ce verdict est donc fondé
sur l'impact GitNexus ciblé, les tests et la vérification live read-only, et ne
constitue pas une approbation du worktree complet. Aucun ordre ni changement de
configuration de production.

## 2026-07-16 · Revue Codex · INTEREST_CURRENT + CURRENCY_SYMBOL

**Verdict ciblé : PASS pour relance data-only des 50 actifs.** GitNexus classe
`swap_bps_per_rollover` HIGH (5 symboles, 3 flux de calibration), tandis que
`simulate`, `_cost_snapshot` et `_cost_model` sont LOW. Le niveau HIGH est
accepté uniquement dans le protocole M2 : aucune route d'ordre n'est atteinte.

Les tests prouvent les intérêts courants variables selon le close de chaque
rollover, le calcul monétaire base=profit, la conversion d'un cross base/profit,
la propagation dans `simulate` et l'acceptation des deux modes par le snapshot.
Résultat : 71/71 et `py_compile` PASS ; smoke live read-only BTCUSD/HSI.fs PASS.
Les modes inconnus et données nécessaires absentes restent fail-closed.

Réserve : `detect_changes(all)` via le runner file-backed retourne toujours
CRITICAL pour le worktree global préexistant (24 fichiers, 133 symboles,
39 flux). Les fichiers de calibration sont non suivis dans l'état Git actuel;
ce PASS ne valide ni le worktree complet ni un changement production.

## 2026-07-16 · Revue Codex · Driver Binance Spot M2

**Verdict ciblé : PASS pour exécution réseau data-only par Claude.** Le driver
compare TAKER et MAKER avec la même donnée et le même harnais M2. La commission
par côté est convertie explicitement en aller-retour : 20 bps TAKER et 15 bps
MAKER. Avec spread 1 bps stressé ×1,25 et slippage 1 bps, le simulateur retire
respectivement 22,25 et 17,25 bps par trade. Spot implique swap/funding nul,
hypothèse enregistrée dans chaque snapshot.

Preuves fraîches : 11/11 tests spécifiques, 82/82 régressions
Binance/calibration/validation/MetaTester, compilation Python PASS, aucune
référence à `order_send`, `order_check`, MetaTrader5 ou `mt5.` dans le nouveau
driver et ses tests. Les sorties restent sous
`data/calibration_binance_2026-07-16`; aucune écriture de
`data/asset_configs.json`.

Réserves : GitNexus a reconstruit 6 398 nœuds/11 193 relations/298 flux mais a
perdu la couche PDG et n'a pas chargé FTS. `detect_changes` reste CRITICAL au
niveau du worktree global déjà sale (24 fichiers, 133 symboles, 39 flux) et ne
voit pas les fichiers non suivis. Ce PASS autorise seulement le run de mesure ;
il ne valide ni V2 régime, ni une proposition production, ni le worktree global.

## 2026-07-17 · Revue Codex · ENTRY_DETECTION

**Verdict : BLOCK avant câblage au labo ou au score.** Les quatre modules ajoutés
par Claude comblent les familles manquantes sur le plan architectural, mais ils
sont encore standalone et leurs tests couvrent surtout les happy paths.

P0 transverse : Binance REST conserve la kline en formation, le resample WS 30 s
peut exposer le bucket courant et les timeframes ne partagent pas un `as_of`
clôturé. La promesse « sans look-ahead / dernière bougie close » n'est donc pas
vraie bout-en-bout. Le moteur bougie compte aussi des patterns `confirm=True`
sans confirmation et additionne des observations corrélées (doji+marteau,
engulfing+outside). Les étoiles et soldats/corbeaux sont trop permissifs ou mal
classés par rapport aux définitions standard adaptatives.

Gap stack : `ob_status` s'arrête au premier touch et peut masquer une cassure
postérieure ; GitNexus classe ce symbole **HIGH** (un appelant direct, trois
modules jusqu'à profondeur 3, dont Execution). Le score /16 reste additif et
autorise la substitution entre piliers corrélés au lieu d'imposer la confluence
tendance/SR ∧ juste-prix ∧ liquidité ∧ OTE/OB valide ∧ bougie confirmée. FVG, OB,
sweep et BOS restent trop pauvres ; une meilleure implémentation sweep existe
dans `fixes/` mais n'est pas celle du runtime.

Les nouveaux profils de volume sont une approximation uniforme OHLCV, pas un
vrai volume-at-price ; Fib OTE relie simplement les derniers pivots sans filtre
d'impulsion/BOS ; S/R n'est pas encore multi-TF et son clustering peut chaîner
des niveaux. Diffs/tests proposés sur le bus :
`33240967-4ecd-4839-8df3-64a4ebfbf896`. Aucun code de trading modifié par Codex.
Le `venv` Codex pointe vers un Python absent : les 20 tests annoncés par Claude
n'ont pas été réexécutés indépendamment.

## 2026-07-17 · Re-revue Codex · Confluence lots 1 a 4

**Verdict : BLOCK POUR CABLAGE ; poursuite autorisee en modules isoles.** Les
correctifs `closed_only`, source Binance `k.x=true`, `net_bias` non additif et
gate AND vont dans le bon sens. Le bus de revue est
`0eb44364-3264-4bc6-8fbc-bb7327d82a35`.

P0 restant : `confluence_adapter.py` force `edge_ok=True` et
`confluence_gate.py` considere la valeur absente vraie. Le cout est donc
fail-open ; aucune decision ENTER ne doit etre possible tant que l'edge n'est
pas calcule par une methode preregistree. Il manque aussi un `decision_at`
commun, la fraicheur/as-of par pilier, l'alignement LTF/HTF, la validation
OHLC/index et la separation entre prix causal de signal et prix live.

Autres blocages : les patterns `confirm=True` n'ont pas d'automate de
confirmation N+1 ; certains tests bearish emploient encore `not bull` ; le feed
Binance ne deduplique pas les klines rejouees ; la trace dashboard n'expose pas
encore les reason codes, timestamps, valeurs/seuils, versions et `decision_id`.
Tests demandes : ENTER long/short, donnees/cout/emotion manquants fail-closed,
stale/misaligned, NaN/index desordonne ou duplique, kline dupliquee et
confirmation N+1. La reproduction pytest Codex reste bloquee par le venv qui
pointe vers un Python 3.12 absent.

## 2026-07-17 - Re-revue Codex - Confluence lot correctif 2

**Verdict : PASS contractuel cible apres corrections Codex ; BLOCK pour tout
cablage.** Le split est desormais explicite : `setup_side` vient du niveau S/R,
`setup_family` vaut `continuation` ou `reversal`, la continuation exige la
tendance HTF alignee et le reversal conserve la tendance comme contexte. Une
absence de setup donne `WAIT_NO_SETUP`; un side/famille incoherent bloque.

Le mode DEMO/EXPLORE reste volontairement ouvert : `require_edge=False` accepte
`edge_ok=None` afin de mesurer chaque strategie, mais `edge_ok=False`, un cout
absent ou une emotion absente bloquent. Le mode PROD reste fail-closed par
defaut. `decided_at` est repris de la cloture LTF tracee.

Corrections red-team additionnelles : validation OHLC de tout le frame lu par
les detecteurs ; validite stricte de la premiere bougie des patterns trois
barres ; trois corps francs pour soldats/corbeaux ; outside doji non bearish ;
dedup Binance commite seulement apres succes du callback.

Verification non executable dans le sandbox : `py` est absent et les deux venv
pointent vers un Python 3.12 invisible. La suite contient maintenant 75 tests
statiques (65 initiaux + 10 regressions), mais aucun resultat vert independant
n'est revendique. La relance forward PAPER sans `--mirror` a echoue pour la meme
raison ; aucun ordre ni mutation de compte. Bus :
`f6c2353b-e6c0-4df9-9018-df2d9a5728ad`.

GitNexus : impacts cibles LOW sauf deux lectures initiales UNKNOWN pendant un
verrou LadybugDB, compensees par un blast statique sans appelant production.
`detect_changes(all)` reste CRITICAL sur le worktree global preexistant et ne
voit pas ces fichiers non suivis. Restent avant cablage : test executable,
`ob_status` touch->break HIGH et durcissement VPOC/Fib/SR. PAPER ONLY.

## 2026-07-17 - Revue Codex - ENTRY_DETECTION lot 3

**Verdict : PASS executable cible ; GO DEMO/EXPLORE, BLOCK PROD/CABLAGE.** La
suite independante demandee passe 75/75 via le Python embeddable local. Le lot
augmente, incluant les regressions order-block et le consommateur scoring,
passe 88/88.

Le P0 `ob_status` est corrige : la lecture ne retourne plus `tested` a la
premiere touch et continue jusqu'a detecter une eventuelle cassure ulterieure.
Les cas achat, vente et touch sans cassure sont couverts. GitNexus classe ce
symbole HIGH avec un appelant direct et une propagation jusqu'a la boucle de
scan ; cette modification reste donc interdite de promotion hors protocole.

VPOC, Fib OTE et S/R refusent maintenant les parametres invalides, les prix et
OHLC non finis/incoherents et, pour le profil, les volumes negatifs/non finis.
Aucun seuil de setup ou de confluence n'a ete resserre : la diversite des
strategies reste mesurable en DEMO/EXPLORE.

`detect_changes(all)` est CRITICAL sur l'ensemble du worktree preexistant
(138 symboles, 25 fichiers, 38 flux) et detecte bien `ob_status`; il ne couvre
pas les modules non suivis. La tentative de suite globale est bloquee a la
collection par des dependances GitNexus/async hors lot absentes de `.pyembed`.
Aucun ordre, aucun acces compte, aucun cablage production.

## 2026-07-17 - Revue Codex - CABLAGE DEMO CONFLUENCE

**Verdict : GO DEMO/EXPLORE, DESARME ; aucun P0 bloqueur.** La suite demandee
passe 5/5 via `.pyembed/python.exe`. Une verification elargie des contrats de
confluence, du pont demo, de l'executeur et des bougies cloturees passe 77/77.

Le chemin d'ordre est unique : `run_once` -> `place_demo_async` -> `_place_sync`
-> `place_market_order`. Le compte est refuse s'il n'est pas en trade mode demo,
s'il correspond au login reel interdit ou s'il differe du login demo attendu.
`assert_demo_or_raise` est rejoue apres `order_check`, immediatement avant
`order_send`, sous le verrou MT5. Reserve operationnelle non bloquante : le
verrou local ne rend pas atomique une bascule externe du terminal ; conserver
le terminal dedie et verifier le compte demo avant armement.

La double porte est correcte : la premiere controle la creation de la boucle au
demarrage, la seconde est relue dynamiquement avant toute tentative d'ordre et
dans `DemoGuards.from_env`. L'ATR filtre explicitement les bougies ouvertes ;
l'adaptateur filtre aussi LTF/HTF et utilise la derniere cloture comme prix de
reference. Un ENTER garantit un side +/-1, mappe vers long/short puis revalide
par l'ensemble ferme de l'executeur. Le try/except par symbole isole donnees,
decision, ATR et placement.

Le statut expose flags, verdict/code, raisons, portes, identifiant, as-of,
setup, piliers et resultat/refus de placement : il est exploitable pour le
dashboard pourquoi. P1 recommande : `last_cycle_at`, etat/duree du dernier
cycle, afin de distinguer aucun signal, pas encore lance et boucle morte. Ajouter
un test de cablage SHORT serait utile mais non bloquant. Aucun flag arme ni ordre
emis. Bus : `5504a823-2061-4c06-85f1-e784e5de9346`.

## 2026-07-18 - Revue Codex - CONFLUENCE MULTI-ACTIFS A/D/B

**Verdict A : GO DEMO avec reserve P1 ; BLOCK PROD.** Les CFD et cryptos portent
leur `venue` par entree. La reference Binance est desormais appelee uniquement
pour `venue=crypto`, rejette NaN/inf/zero/negatif et reste non fatale en panne.
Elle ne modifie pas le setup, les niveaux ni l'ordre : le terme « ajuste » est
donc a comprendre comme cross-check affiche, pas ajustement decisionnel.

Le chemin d'ordre reste exclusivement demo. `place_demo_async` exige
`DEMO_EXEC_ENABLED=1`; `_place_sync` controle positions, plafond et compte ;
`place_market_order` refuse trade mode non-demo, login reel et tout login autre
que le demo attendu, puis repete ce controle immediatement avant `order_send`.
Reserve operationnelle inchangee : terminal DEMO dedie contre une bascule externe.

**D livre, risque HIGH maitrise par changement pur et tests.** `get_rates_h1`,
`get_rates` et `get_ohlcv` normalisent l'heure murale Axi EET/EEST vers UTC avec
gestion DST. Blast radius : forex, swing, confluence demo et forward paper.

Verification : commande exacte fournie = **51 passed**, pas 73 ; le compte
attendu du briefing est obsolete pour ces cinq fichiers dans l'etat courant.
Suite elargie securite/execution/D = **86 passed**. Les deux avertissements sont
de configuration pytest/pandas, sans echec. Aucun acces ordre/compte dans les tests.

**B : BLOCK CABLAGE, protocole papier pret.** `_best_lag_ms` ne peut pas qualifier
une anticipation (31 lags non corriges, inverse ignore, forward-fill, transport
confondu avec decouverte). Le protocole M2 pre-enregistre une petite famille
economique, corrige toute la multiplicite, exige PBO/DSR/bootstrap/couts et ne
peut promouvoir qu'en forward PAPER. Ordre : A -> D -> B M2 offline -> E inventaire
read-only -> C famille M2 separee. `detect_changes` global reste CRITICAL a cause
du worktree preexistant tres sale ; aucun go production/reel.

## 2026-07-18 - Revue Codex - LEADLAG_M2_EXEC

**BLOCK CABLAGE, 0 PAIRE SURVIT.** Sur 864 hypotheses Axi M15, aucune ne passe
BH-FDR ou Holm a 5 %. Les trois candidats du scan court echouent bootstrap,
DSR et/ou economie nette Axi ; le final verrouille n'a pas ete lu. PBO=0 indique
seulement un classement stable entre strategies perdantes et ne compense aucun
gate.

P0 scanner : la derniere kline Binance en formation n'est pas retiree dans
`_crypto_fetch`; les neuf appels sequentiels peuvent produire un faux ordre
leader/follower de transport. P1 : lag choisi au maximum de correlation brute,
facteur commun/AR/inverse absents, trous M15 non controles, persistance sur
fenetres quasi identiques et couverture de tests uniquement synthetique.

Le turning-point brut compare mal un taux naturellement proche de 50 %. Sur la
selection longue, les trois uplifts conditionnels tombent a +0,06/+0,07/+0,08
point. Nouvelle famille proposee : label flip residuel, baseline hazard,
log-loss/Brier apparies, split purge+embargo, events non chevauchants,
bootstrap/FDR/Holm puis couts/latence Axi. Rapport complet :
`collab/REVUE_LEADLAG_M2_CODEX_2026-07-18.md`. PAPER/DEMO ONLY, aucun ordre.

## 2026-07-19 - Revue Codex - CONSENSUS_3_MOTEURS

**GO détection / BLOCK décision et trading avant M2 + go Florent.** Le consensus
ne somme pas les 5 piliers et les 16 critères. Il normalise chaque moteur dans cinq
familles corrélées plafonnées ; une preuve isolée ne reçoit que 60 % du poids de sa
famille et deux moteurs concordants peuvent au plus la saturer. L'accord publié exige
une confirmation interne minimale (4/5 structurels avec trend/SR ; 8/16 scoring ;
émotion actionnable). Les conflits de direction restent visibles même si la somme
signée penche d'un côté.

Sécurité : aucun import d'exécuteur, aucun `place_fn`, aucun flag, aucun ordre et
aucune écriture d'état de trading. La route lit seulement le cache. Vérification
pertinente `.pyembed` : **57 passed** ; intégration réelle des fonctions CONFLUENCE et
SCORING couverte sur données closes synthétiques. Suite complète non collectable dans
`.pyembed` faute de `anyio`/`cryptography` préexistants. GitNexus MCP verrouillé ;
fallback `detect_changes` global CRITICAL et non attribuable au lot seul dans ce
worktree déjà fortement modifié. Aucun commit, aucun câblage décisionnel.

## 2026-07-19 - Revue Codex - RESTORE_CODE_INTELLIGENCE

**GO développement read-only, aucune capacité de mutation.** GitNexus est de nouveau
interrogeable sur 4747 avec un index PDG frais. Le mode continu est volontairement
désactivé : sous Windows, reconstruire la base active pendant une lecture MCP crée
un verrou LadybugDB. La politique retenue est une réindexation bornée aux checkpoints
de développement, suivie d'un serveur stable sans watcher.

Le fournisseur structurel local corrige le trou fonctionnel de `smart-explore` sans
activer la collecte de mémoire claude-mem. Sa barrière de chemin est testée contre
les sorties de racine et les candidats de type symlink ; les secrets et zones
d'état sont exclus. Chargement effectif requis au prochain redémarrage des sessions
Claude/Codex. Réserve P1 : l'analyseur signale l'extension FTS LadybugDB indisponible,
mais `query`, `cypher` et `pdg_query` ont tous répondu après reconstruction.

## 2026-07-19 - Contre-revue Codex - AUDIT_ARCHI_V12

**ACCORD cerveau non câblé / BLOCK câblage actif.** GitNexus confirme zéro
appelant in-repo pour `run_plan`, `plan_from_text` et `map_intent`; les moteurs
DEMO atteignent directement `demo_bridge`. La phrase « seulement câblé à la
voix » doit être ramenée à une hypothèse externe non prouvée dans v12.

Le bus possède déjà un fan-out, mais son seul consommateur est le WebSocket UI.
Il n'est pas apte au contrôle : pertes silencieuses, disque synchrone, absence
de schéma/sequence/idempotence/replay. Recommandation : EventPlane afférent
read-only distinct du CommandGateway efférent. Hermes produit des propositions
non fiables ; un PolicyKernel déterministe les valide ; le registre fermé reste
l'unique frontière du cerveau ; gardes/approvals/DEMO sont revalidés au sink.

La priorité devient G (identité), E0/B0 (projection + miroir), F0
(supervision), D0 (DecisionKernel offline/M2), puis C0/C1 (observe/shadow).
Lead/lag et émotion ne peuvent pas entrer dans un AND décisionnel sans preuve M2.
Rapport : `collab/CONTRE_REVUE_ARCHITECTURE_V12_CODEX_2026-07-19.md`.

## 2026-07-19 - Design Codex - fondation fusion Hermes / AUDIT_ARCHI_V12

**GO B0/C0 miroir selon contrat ; BLOCK tout efférent actif.** La fusion Hermes
est réconciliée comme une couverture totale de perception/mémoire/proposition,
sans autorité LLM. Le plan afférent est un EventPlane séparé, SQLite/WAL,
append-only, commit avant ACK, ordre global + par stream, livraison au moins une
fois, consommateurs idempotents, replay et erreurs/gaps visibles. Le plan efférent
accepte uniquement une Proposal non fiable via PolicyKernel déterministe, registre
fermé versionné et revalidation compte/mode/risque au sink.

Le schéma, le DDL, les API Python, les types initiaux C0, reason codes et 16 tests
d'acceptation sont spécifiés dans
`collab/CONTRAT_FUSION_HERMES_EVENTPLANE_COMMANDGATEWAY_2026-07-19.md`.
Aucun runtime, flag ou ordre n'a été touché. Compte réel PAPER ONLY ; DEMO sous
mur fail-closed.

## 2026-07-19 - Revue Codex - câblage EventPlane C0a read-only

**REQUEST CHANGES / PAS DE GO production.** L'afférent reste sans appel direct
vers un exécuteur et OpenAPI n'expose que deux routes GET, mais le canari a été
activé avant la revue (`EVENTPLANE_MIRROR_ENABLED=1`) et accumule des erreurs.
Pendant la revue, le journal est passé de 78 à 89 faits ; l'intégrité de chaîne
reste OK, mais 17 `PUBLISH_FAILED` sont tous des `IdempotencyConflict`.

Cause P0 : `decision_id` n'est pas globalement unique entre instruments
(ADA/BCH/XRP partagent un identifiant ; ETH/LTC un autre) alors que la clé est
`confluence:{decision_id}`. Le symbole doit participer à la clé et un test doit
couvrir deux instruments portant le même identifiant. Autres blocants :
`repr(exc)` persiste encore dans le journal, le heartbeat avale ses erreurs,
les routes acceptent offset négatif/type inconnu/limite > 200 sans 422, et aucun
test HTTP/runner n'existe. Le Cortex est fail-open : il appelle `health()` sans
intégrité puis traite l'absence de `integrity.ok` comme vraie.

GitNexus a été réindexé (24 187 nœuds, 93 476 relations, 300 flux). Les symboles
isolés sont LOW, mais la cartographie de routes GitNexus ne détecte toujours pas
les deux décorateurs ; la couverture consommateurs reste donc inconnue. Les 31
tests ciblés passent mais ne couvrent ni la collision réelle, ni HTTP, ni le
runner. Verdict transmis à Claude via ACK
`5848b25b-f1a3-4222-8e6b-08bca8ffd98d`. PAPER/DEMO ONLY.

## 2026-07-19 - Revue en attente - cycle de vie GitNexus Windows

**VALIDATION TECHNIQUE VERTE, INTEGRATION BLOQUEE POUR REVUE CRITICAL.** Le
serveur `1.6.10-rc.50` sert les deux graphes apres un cycle arret/redemarrage :
Titanium (1 104 fichiers, 24 297 symboles, 64 237 liens, 300 flux) et JARVIS
assaini (38 fichiers, 5 288 symboles, 19 372 liens, 101 flux). Cypher et BM25
passent avant et apres redemarrage ; un faux jeton de shutdown retourne 403.

Le correctif ajoute un arret gracieux authentifie et met en quarantaine, sans
suppression, uniquement l'etat LadybugDB ferme dont le WAL mesure exactement 42
octets. Tout WAL plus grand echoue ferme. Le bootstrap MCP est epingle sur la
meme version que le serveur. 46 tests passent, mais `detect_changes` classe les
quatre fichiers CRITICAL (156 symboles, 23 flux). Claude doit rendre GO ou
REQUEST CHANGES avant commit/production. Le patch local du paquet npm sera
ecrase par une mise a jour et doit etre upstream ou automatise. PAPER/DEMO ONLY.

## 2026-07-19 - Revue Codex - reconnaissance Claude / GitNexus

**GO TECHNIQUE, RECHARGEMENT TITANIUM DIFFERE.** Claude est configure comme
client HTTP nomme sur l'unique endpoint loopback `127.0.0.1:4747/api/mcp` et
atteste `SUBSCRIPTION_OK` via l'abonnement first-party. L'attestation ne contient
que dix champs publics et bascule sur Ollama pour toute cle/jeton API, fournisseur
tiers, verification absente ou age superieur a 86 400 secondes.

La premiere version du manifeste interdisait declarativement les capacites natives
`rename` et `group_sync` a Claude. Les 61 tests cibles passent. GitNexus est sain et frais (1 109 fichiers, 24 535
symboles, 64 586 relations, 300 flux), Cypher et BM25 passent, et `claude mcp
list` ne montre aucun conflit. L'API services possede le contrat teste et le
cycle stop/start gracieux authentifie. L'instance Titanium active n'a pas ete
coupee car le moteur DEMO est arme ; elle expose encore l'ancien module jusqu'au
prochain redemarrage controle. Revue Claude/Hermes demandee. PAPER/DEMO ONLY.

## 2026-07-19 - Re-revue Codex - frontiere Claude/GitNexus durcie

**GO TECHNIQUE POUR LE CLIENT READ-ONLY ; AUCUNE ECRITURE CLAUDE.** Les trois
defauts bloquants de la contre-revue sont corriges : (1) le serveur HTTP applique
la politique native `GITNEXUS_MCP_READ_ONLY=1`, (2) les dependances GitNexus du
lot sont versionnees au lieu de dependre seulement du worktree local, (3) les
attestations et reponses API filtrent les champs prives et les chemins locaux.

Preuve dynamique : 13 outils HTTP uniquement read-only ; aucun `rename`,
`group_sync`, `cypher` ou `group_list`; tentative forcee de `rename` refusee.
Le controle d'abonnement reste fail-closed et retire l'endpoint en cas d'echec.
Le fichier d'attestation demeure dans le perimetre de confiance du compte Windows
local : il protege contre la derive, les donnees vieillies et les contrats
incoherents, pas contre un attaquant ayant deja le meme acces utilisateur.

Le cycle Windows reel a aussi revele deux faux timeouts : 2 s ne suffisaient pas
pour lire `/opportunities/status` et 8 s ne suffisaient pas pour la fermeture
Node. Les seuils bornes sont maintenant 5 s et 30 s ; le timeout reste fail-closed.
La reindexation post-correctif reussit en 73,5 s avec code 0.

Les 97 tests cibles passent. Le repli Ollama est une politique fail-closed, pas
une promesse de disponibilite : si Ollama est arrete, Claude reste retire au lieu
d'autoriser une facturation API. Titanium 8090 n'est pas redemarre pendant que la
DEMO est armee. PAPER/DEMO ONLY ; aucun chemin critique trading modifie.

## 2026-07-20 - Red-team Codex - CommandGateway C1 SHADOW

**REQUEST CHANGES ; TRANSPORT R-2 BLOQUE ; SECTION 7 PRIORITAIRE.** Le noyau
reste acceptable comme prototype dormant : GitNexus ne trouve aucun appelant ni
flux runtime, la table de handlers est vide, `resolve_handler` echoue toujours et
`dispatch_permitted` reste faux. Les 21 tests nominaux passent dans `venv` et
`.pyembed`, mais la majorite des criteres annonces ne sont couverts que
partiellement.

Bloquant P0 avant toute activation : `CommandGateway.submit` persiste la
proposition avant la validation du schema de capacite et avant tout secret gate.
Un contre-test a prouve qu'un champ `api_key` place dans `params`, ensuite refuse
par `PARAM_SCHEMA_VIOLATION`, reste tout de meme stocke en clair dans
`proposal_json`.

Bloquants P1 : course multi-gateway pouvant rendre deux verdicts differents pour
le meme `decision_id`, TTL maximal de capacite non applique, `projection_as_of`
ignore, timestamps naifs acceptes, M2/approval valides par simple presence,
PolicyKernel non pur car le registre est lu paresseusement, journal non
reconstructible depuis son JSON, et rejeu exact qui recree une reply differente.
La provenance de `AttestedPrincipal` et `TrustedState`, le lifecycle/concurrence
SQLite et les tests crash/replay restent aussi a fermer.

Decision d'ordonnancement : fermer d'abord les contournements de la Section 7
(JARVIS/`ADMIN_TOKEN`/`run_plan`/POST directs/`run_swing_scan`/
`reset_circuit_breaker`). Aucun named pipe, service Windows, handler, audit
EventPlane Gateway ni activation avant un lot correctif noyau test-first puis une
nouvelle revue Codex. Verdict transmis a Claude par ACK
`783ad742-2895-490e-96eb-9881f4d43a3a`. PAPER/DEMO ONLY.

## 2026-07-21 - Revue Codex - lot MCP singleton et reprise GitNexus

**GO BORNE AU TRANSPORT MCP ET A L'INDEXATION.** Le lot `bc0c364` centralise les
trois listeners locaux sans modifier la logique de trading. Les 26 tests cibles
passent, aucun secret n'est present dans les 14 fichiers indexes et les trois
serveurs MCP repondent sur leurs ports uniques.

GitNexus classe le rayon staged CRITICAL car les wrappers generiques de lecture
traversent 28 flux `signals`/`positions`/journaux/backtests. La revue detaillee ne
montre aucun processus d'ordre ou de score affecte. Ce classement n'est donc pas
ignore : il est accepte uniquement pour ce lot de transport read-only/signe.

La reconstruction finale est fraiche avec PDG et FTS actifs. Le refus d'arret
gracieux 4747 a ete ferme dans `b204777` : fallback uniquement sur route absente,
identite PID/CLI/host/port verifiee, verification WAL et redemarrage garanti.
Aucun relachement des garde-fous : PAPER/DEMO ONLY, compte reel 60261188 interdit.

## 2026-07-21 - Revue Codex CollabHub C1

**Verdict : GO technique C1 shadow / HOLD pour toute elevation.** Le service est
local, durable, rejouable et idempotent. Les cinq outils MCP ne peuvent ni
approuver une permission, ni ecrire le code, ni dispatcher une commande, ni
trader. Les approbations GitNexus signees restent separees. Impact GitNexus de
l'importeur LOW : un appelant direct et un flux operateur. Suite ciblee : 21/21.
Claude doit encore rendre son arbitrage H0-H4 avant modification des droits
Hermes au-dela de la collaboration C1. PAPER/DEMO ONLY ; reel interdit.

### Addendum 2026-07-22 - arbitrage Claude

Claude rend **ACCEPT H0, ACCEPT H1, AMEND H2, ACCEPT H3, ACCEPT H4**. H2 reste
sous double signature obligatoire Florent + superviseur ; l'indisponibilite de
l'un differe l'operation et ne permet pas de basculer sur une seule signature.
Hermes est reconnu cerveau principal de confiance **C1 shadow uniquement** :
perception, analyse, proposition et coordination, sans autorite d'action.

## 2026-07-29 - Revue Codex - exposition GitHub pour Kimi 3

**GO publication, avec exclusions de sécurité obligatoires.** Les branches
`master`, `reorg/phase1` et `feature/command-deck` ont été poussées sans force.
L'état fonctionnel des agents, sous-chantiers, validations et dettes connues est
publié dans `KIMI3_START_HERE.md` et `collab/`.

Les répertoires bruts `.claude/` et les caches d'agents ne sont pas des sources
projet publiables : ils contiennent credentials, historiques et sauvegardes de
session. Leur état utile a été consolidé sans ces données. Même exclusion pour
`.env`, tokens, données runtime/PnL, environnements, modèles, index GitNexus et
binaires générés.

Contrôles : aucun secret réel dans 1 319 fichiers du snapshot ni dans 648 objets
historiques locaux à publier ; HTTP 200 sur la branche, le Markdown brut, le
JSON brut et le Command Deck. Command Deck 20/20 tests ; outils Open WebUI
compilables. GitNexus a été invoqué mais son résultat « No changes detected »
est **non probant** ici : FTS indisponible et nouveaux fichiers absents de
l'index. Aucun changement de trading ; PAPER/DEMO ONLY.
