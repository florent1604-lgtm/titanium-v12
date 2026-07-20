# Services MCP singleton et flux directs — conception

**Date :** 20 juillet 2026
**Décision :** validée par Florent — aucun doublon MCP, uniquement des chemins de flux directs
**Périmètre :** Titanium v12, JARVIS, Hermes, GitNexus, Claude Code et Codex
**Garde permanente :** compte réel Axi `60261188` interdit ; exécution limitée au compte DEMO `50061786` derrière le mur fail-closed existant.

## 1. Objectif

Remplacer les chaînes MCP `stdio` dupliquées, aujourd'hui recréées par chaque session cliente, par des services locaux persistants et singleton auxquels Claude, Codex et Hermes se connectent directement. Retirer complètement Base44 du runtime. Corriger avant le redémarrage les incohérences de données constatées pendant l'audit de vitalité, puis reconstruire une cartographie GitNexus fraîche et commune.

Le résultat attendu n'est pas « moins de processus au hasard » : chaque organe doit avoir un propriétaire de cycle de vie unique, une adresse canonique, un contrôle de santé et aucun processus orphelin.

## 2. Invariants

1. Un seul processus propriétaire par service logique.
2. Aucun serveur MCP métier lancé en enfant d'une session Claude, Codex ou Hermes.
3. Les trois clients utilisent les mêmes adresses canoniques et le même schéma d'outils.
4. Aucun proxy MCP en cascade et aucun pont `stdio -> stdio -> HTTP`.
5. Les transports sont exclusivement loopback ou named pipe Windows avec identité vérifiable.
6. GitNexus possède un seul daemon HTTP et un seul watcher.
7. Base44 ne possède plus de processus, route, configuration MCP, boucle de synchronisation ou composant d'interface actif.
8. Les rapports historiques peuvent citer Base44 ; ils ne doivent pas être réécrits.
9. Les journaux EventPlane, les journaux DEMO, les données de marché, les secrets et les mémoires Hermes ne sont jamais considérés comme des caches.
10. Une purge ne cible que des chemins explicitement régénérables et vérifiés sous leurs racines attendues.
11. Consensus, émotion et lead/lag peuvent circuler librement dans le plan afférent d'analyse, mais aucune capacité décisionnelle ne peut être implicite ou contredire son contrat M2.
12. Aucun redémarrage ne peut réarmer l'exécution si le compte MT5 n'est pas exactement `50061786`.

## 3. Topologie cible

```text
Claude ─┬──────────────────────> GitNexus :4747/api/mcp
Codex ──┤
Hermes ─┘

Claude ─┬──────────────────────> Titanium Control MCP :8091/mcp
Codex ──┤
Hermes ─┘

Florent/voix/dashboard ────────> JARVIS + Hermes :8765

Titanium moteurs ──> EventPlane ──> Cortex ──> Hermes/JARVIS/dashboard
                         │
                         └────────> observabilité et audit
```

### 3.1 GitNexus

- Un seul daemon sur `127.0.0.1:4747`.
- Un seul watcher, propriétaire des réindexations et protégé par mutex inter-processus.
- Les demandes de réindexation sont sérialisées ; une seconde demande rejoint l'opération en cours au lieu d'ouvrir LadybugDB simultanément.
- Claude, Codex et Hermes se connectent directement au transport HTTP MCP.
- Les écritures natives autorisées restent limitées à `rename` et `group_sync`, derrière la validation signée existante ; aucun client ne contourne ce garde.
- Le MCP structurel séparé est retiré après vérification que les fonctions nécessaires sont couvertes par GitNexus.

### 3.2 Titanium Control MCP

- Un processus singleton distinct du moteur de trading, sur `127.0.0.1:8091`.
- Il expose les outils d'observation et de contrôle autorisés sans créer un interpréteur Python par client.
- Il ne détient aucune autorité directe sur `order_send` ; toute mutation reste soumise aux gardes existants.
- Le processus principal Titanium conserve `127.0.0.1:8090` pour l'API et le dashboard.

### 3.3 JARVIS et Hermes

- Un seul processus JARVIS/Hermes propriétaire du port `8765`.
- Hermes est un client direct de GitNexus et Titanium Control MCP.
- Les anciennes chaînes `hermes.exe -> python.exe -> gitnexus gate` par session disparaissent.
- La correction Windows utilise un exécutable/runtime conforme à Code Integrity. La politique Windows n'est pas désactivée globalement.
- Si Hermes ne peut pas démarrer avec une identité vérifiable, son état est `DEGRADED` et il ne doit pas être simulé par un processus fantôme.

## 4. Retrait complet de Base44

Le retrait couvre :

- la déclaration `base44` de `.mcp.json` et des configurations Codex/Claude concernées ;
- le serveur `mcp_base44.py` ;
- les routes et le client runtime `api/base44_routes.py`, `core/base44_client.py` et `core/base44_push.py` ;
- l'enregistrement de route et la boucle de synchronisation dans `api/api_server.py` ;
- les paramètres Base44 dans `utils/config.py` et les modèles d'environnement documentés ;
- les widgets ou appels Base44 encore actifs dans les dashboards maintenus ;
- les tests runtime devenus sans objet, remplacés par une preuve d'absence de route et de processus.

Les mentions dans `collab/`, `docs/` et les sauvegardes HTML restent des archives. Aucun secret historique n'est déplacé ou affiché.

## 5. Corrections préalables au redémarrage

Chaque correction suit un cycle test rouge, modification minimale, test vert et analyse d'impact GitNexus.

### 5.1 Projection Cortex/Consensus

Le Cortex doit consommer le contrat réel de consensus : `heartbeat` et `symbols`. La fraîcheur provient de `heartbeat.last_cycle_at` et le nombre d'actifs de `symbols`. Une donnée absente ou invalide produit `unknown/cold`, jamais un faux état vert.

### 5.2 Univers Axi du scanner d'opportunités

La catégorisation reconnaît explicitement les familles réellement exposées par Axi : `ROW_STANDARD_FX`, `ROW_CRYPTO`, `ROW_FUTURES`, `ROW_CASH` et `ROW_STANDARD_METALS`. Un univers vide devient une erreur visible et ne peut plus être enregistré comme un scan réussi.

### 5.3 Contrats décisionnels

Tant qu'un moteur publie `decision_capability=false`, ses données restent accessibles à Cortex, Hermes et au dashboard, mais ne peuvent ni autoriser/refuser une entrée ni modifier la taille d'une position. Toute promotion de consensus ou émotion vers le chemin décisionnel exige un contrat M2 explicite et versionné.

Cette correction rétablit le contrat fail-closed ; elle ne ferme pas les flux d'analyse.

### 5.4 Schéma JSON canonique

`/consensus/status` ne doit plus contenir de clés distinctes uniquement par la casse. Les clés de critères ont une forme canonique unique ; les valeurs contextuelles comme les prix d'EMA vivent sous un objet différent des critères booléens. Le test d'acceptation parcourt récursivement la réponse et exige zéro collision insensible à la casse.

### 5.5 Santé et fraîcheur

- L'intégrité EventPlane est calculée explicitement par Cortex ; une preuve absente vaut `unknown`, pas `ok`.
- Les `consumer_failures` sont exposés en compteurs `total`, `recent` et `delta`, afin de ne pas confondre historique et panne active.
- Un snapshot crypto trop ancien est marqué `stale` avec son âge et sa source.
- Le webhook reste désactivé si son secret n'est pas configuré.

### 5.6 CommandGateway et contournements

CommandGateway reste C1 shadow, sans handler et sans activation. Le nettoyage MCP ne sert pas à promouvoir ce noyau. Les contournements JARVIS déjà identifiés en Section 7 doivent être fermés et revus avant toute future autorité efférente centralisée.

## 6. Assainissement des processus

L'arrêt suit l'ordre dépendant suivant :

1. maintenir le mur réel et geler toute nouvelle exécution DEMO ;
2. vérifier qu'aucune position inconnue n'est ouverte ;
3. arrêter proprement JARVIS/Hermes, Titanium, les serveurs MCP et GitNexus ;
4. attendre la disparition des listeners ;
5. terminer uniquement les arbres encore vivants dont la ligne de commande et la racine exécutable correspondent aux services Titanium/JARVIS/Hermes/GitNexus inventoriés ;
6. ne jamais utiliser un `Stop-Process -Name python/node` global ;
7. relancer les services singleton dans l'ordre GitNexus, Titanium Control MCP, Titanium, JARVIS/Hermes.

Les shells `.bat` historiques sans enfant vivant et les sidecars sans listener sont classés orphelins et retirés pendant cette fenêtre contrôlée.

## 7. Purge des caches

### 7.1 Autorisés

- `__pycache__` et fichiers `.pyc` sous les racines projet validées ;
- `.pytest_cache` et caches de couverture ;
- caches Vite régénérables ;
- fichiers temporaires de test identifiés ;
- index GitNexus local après arrêt confirmé de tous ses lecteurs/écrivains, puisqu'une réindexation complète est demandée.

### 7.2 Interdits

- `data/` hors fichier explicitement documenté comme cache ;
- EventPlane SQLite/WAL, journaux DEMO, résultats de calibration et historiques MT5/Binance ;
- `.env`, clés, attestations, approbations signées et mémoires Hermes ;
- environnements Python, `node_modules` et installations applicatives ;
- worktree Git et modifications non liées appartenant à Florent ou Claude.

Chaque chemin est résolu en absolu et contrôlé avant toute suppression récursive.

## 8. Réindexation et identité des clients

GitNexus indexe du code, pas les modèles Claude ou Codex. « Réindexer Claude, Codex et Hermes » signifie donc :

1. reconstruire les index Titanium et JARVIS ;
2. créer ou rafraîchir un snapshot Hermes sans secrets si son code n'est pas déjà un dépôt indexable ;
3. créer un groupe GitNexus `titanium-neural` réunissant ces dépôts et leurs contrats HTTP/MCP ;
4. recharger les configurations clientes pour que Claude, Codex et Hermes pointent vers les endpoints singleton ;
5. effectuer pour chaque identité un handshake, `list_tools`, une requête GitNexus read-only et une lecture Titanium ;
6. prouver que ces connexions n'engendrent aucun nouveau serveur métier local.

## 9. Séquence de redémarrage

1. GitNexus daemon et watcher singleton.
2. Vérification index, groupe et requête de graphe.
3. Titanium Control MCP.
4. Titanium API/moteurs avec exécution maintenue fermée pendant les contrôles initiaux.
5. JARVIS/Hermes.
6. Handshakes Claude, Codex, Hermes.
7. Vérification EventPlane -> Cortex -> Hermes/dashboard.
8. Réarmement DEMO uniquement si le compte est `50061786`, les gardes sont verts et aucune position inconnue n'existe.

## 10. Critères d'acceptation

- Exactement un listener sur chacun des ports canoniques `4747`, `8090`, `8091` et `8765`.
- Exactement un watcher GitNexus.
- Aucun processus `mcp_base44.py`.
- Aucun processus serveur MCP métier enfant d'une session Claude/Codex/Hermes.
- Aucun processus orphelin des anciens lanceurs Titanium/JARVIS.
- Aucune route Base44 dans OpenAPI et aucune configuration MCP Base44 active.
- GitNexus ne produit aucun verrou concurrent pendant deux réindexations demandées simultanément.
- Les dépôts Titanium, JARVIS et le snapshot Hermes sont frais dans le groupe `titanium-neural`.
- Claude, Codex et Hermes réussissent les mêmes sondes read-only via leurs connexions directes.
- Cortex affiche consensus vivant avec le nombre réel de symboles.
- Le scanner d'opportunités découvre un univers Axi non vide ou expose une erreur explicite.
- `/consensus/status` possède zéro collision de clés insensible à la casse.
- EventPlane progresse, son intégrité est vraie et le delta d'échecs récents reste nul pendant la fenêtre d'observation.
- Le compte réel `60261188` n'a reçu aucune requête d'ordre ; seul le compte DEMO `50061786` peut être réarmé.

## 11. Retour arrière

Avant toute mutation, les configurations MCP et les fichiers runtime concernés sont sauvegardés dans un répertoire horodaté hors cache. Si un service singleton ne passe pas ses contrôles :

1. l'exécution reste fermée ;
2. les configurations sont restaurées ;
3. les services essentiels sont relancés dans leur mode antérieur, à l'exception de Base44 qui reste supprimé conformément à la décision ;
4. l'échec et les preuves sont publiés dans le bus commun sans secret.

Le retour arrière ne doit jamais restaurer un processus dupliqué ou contourner Windows Code Integrity.
