# Titanium v12 — point d'entrée Kimi 3

Instantané de référence : **2026-07-29 13:20 CEST**.

Ce dépôt public contient le code source, les tests, les contrats, les plans,
les audits et l'historique de collaboration utiles à l'analyse de Titanium v12.
Les secrets, clés API, caches, environnements virtuels, index GitNexus générés
et données de compte/runtime volatiles sont volontairement exclus.

## Ordre de lecture recommandé

1. [`AGENTS.md`](AGENTS.md) — règles GitNexus, sécurité et collaboration.
2. [`collab/ETAT_ACTUEL.md`](collab/ETAT_ACTUEL.md) — briefing historique compact.
3. [`collab/AGENT_STATE_SNAPSHOT_2026-07-29.md`](collab/AGENT_STATE_SNAPSHOT_2026-07-29.md)
   — état consolidé des agents, branches, validations et travaux ouverts.
4. [`collab/TASKS.md`](collab/TASKS.md) — registre historique des tâches.
5. [`collab/messages/stream.ndjson`](collab/messages/stream.ndjson) — bus commun
   append-only Claude/Codex/Hermes/Copilot.
6. [`docs/STRATEGY_CONTRACT.md`](docs/STRATEGY_CONTRACT.md) et
   [`docs/VALIDATION_PROTOCOL.md`](docs/VALIDATION_PROTOCOL.md) — contrat
   stratégique et protocole de validation.

Le contexte équivalent structuré pour ingestion automatique est disponible dans
[`collab/agent_state_snapshot_2026-07-29.json`](collab/agent_state_snapshot_2026-07-29.json).

## Branches à lire

- `reorg/phase1` : état le plus avancé du noyau Titanium, de Cloe et des
  connecteurs MT5/MCP.
- `master` : socle principal antérieur, conservé pour comparaison.
- `feature/command-deck` : application Windows de collaboration en cours,
  publiée séparément afin de ne pas fusionner une fonctionnalité non approuvée.

## Architecture utile

```text
N1 ingestion/market
  -> N2 poles (SMC, spectral, fondamentaux, émotion, vision)
  -> N3 fusion / consensus / confluence
  -> N4 risk / RiskGate
  -> N5 execution (démo MT5 sous mur fail-closed)
  -> N6 feedback / Cloe / journaux

N0 transverse : core/state, core/flux, santé, contrats, collaboration, GitNexus
```

Entrées principales :

- `main.py` et `api/api_server.py` : démarrage et API locale.
- `fusion/confluence_demo_engine.py` : pipeline de décision démo.
- `risk/risk_gate.py` : porte de risque.
- `execution/demo_mt5_executor.py` : exécution **démo uniquement**.
- `ingestion/market/mt5_provider.py` : accès marché MT5.
- `mcp_server.py` : pont MCP vers les services locaux.
- `core/cloe_reflex.py` : veto local Cloe, additif et fail-open sur panne.

## Garde-fous non négociables

- Compte réel : **PAPER ONLY**, aucun ordre réel.
- Exécution permise uniquement sur le compte MT5 de démonstration autorisé,
  avec contrôle fail-closed.
- Aucun changement de logique de trading en production sans protocole M2.
- Cloe est un veto additif : elle ne peut pas ouvrir un trade refusé par le
  moteur déterministe.
- Ne jamais demander, afficher, enregistrer ou committer une clé API.

## État de validation connu

- Correctifs MT5/MCP ciblés : **57/57 tests réussis**.
- Suite globale la plus récente : **844 réussis, 1 ignoré, 26 échecs de
  référence hors périmètre**.
- Les 26 échecs doivent être traités comme dette connue, pas comme suite verte.
- GitNexus répertorie 26 633 symboles, 69 089 relations et 300 flux ; l'index
  doit être régénéré après récupération du dépôt pour refléter le dernier HEAD.

## Prompt de revue conseillé à Kimi 3

> Lis d'abord `KIMI3_START_HERE.md`, `AGENTS.md`,
> `collab/AGENT_STATE_SNAPSHOT_2026-07-29.md`, puis
> `collab/ETAT_ACTUEL.md`. Analyse la branche `reorg/phase1` comme état courant
> et compare `feature/command-deck` sans la fusionner. Cartographie les flux
> ingestion → fusion → risque → exécution, vérifie les invariants PAPER/DEMO,
> puis classe les anomalies P0/P1/P2 avec fichier, symbole, preuve, impact,
> test rouge proposé et correctif minimal. Ne propose aucun ordre réel, aucune
> clé API et aucun assouplissement du mur démo/réel.

## Ce qui n'est pas publié

Les exclusions ne sont pas du code manquant :

- `.env`, clés, jetons, credentials et sauvegardes de configuration ;
- `.claude/` brut (credentials, historique et caches de session) ;
- `.agents/` installé localement (copie d'outillage, pas état projet) ;
- index `.gitnexus/`, modèles locaux, `venv`, `.pyembed`, `bin/obj` ;
- journaux actifs, positions, PnL instantané et caches de marché.

L'état utile des agents et sous-chantiers est consolidé dans `collab/` sans
publier leurs secrets ni leurs sessions privées.
