# CollabHub Command Deck Master Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Livrer le Command Deck natif Windows, son chat partagé, le suivi des échecs, le broker d'actions supervisées et le lanceur Bureau.

**Architecture:** Quatre sous-projets indépendamment testables partagent les contrats de la spécification `docs/superpowers/specs/2026-07-22-collabhub-command-deck-native-design.md`. Ils sont exécutés dans l'ordre ci-dessous ; aucun lot ultérieur ne peut contourner les gardes validées par un lot antérieur.

**Tech Stack:** Python 3.12/Starlette/SQLite, HTML/CSS/ES modules, Node 24 `node:test`, .NET 8 WPF, WebView2 `1.0.4078.44`, PowerShell 7/Windows PowerShell 5.1.

## Global Constraints

- Relire `collab/ETAT_ACTUEL.md`, `collab/HERMES_BRIDGE.md` et le tail du bus avant le premier lot puis avant la livraison.
- PAPER/DEMO ONLY ; compte réel 60261188 absent de toute capacité.
- GitNexus `impact upstream` avant toute modification de symbole ; avertir avant HIGH/CRITICAL.
- `detect_changes --scope staged` avant chaque commit et `compare master` avant livraison.
- Aucun secret, jeton, mot de passe ou exception brute persisté.
- Aucun retry automatique de tâche ou d'action.
- GitNexus `rename`/`group_sync` exige Florent + un superviseur ; aucune dégradation à une signature.
- CommandGateway et commandes DEMO restent désactivés tant que leur re-revue n'est pas GO.
- Les autres changements présents dans le worktree partagé ne doivent jamais être ajoutés aux commits de ce chantier.
- Les lectures machine restent celles du compte Windows ; les secrets sont masqués et toute écriture hors V12 ou au Registre traverse le broker.

---

## Ordre des sous-plans

1. [Contrats, tâches et session CollabHub](2026-07-22-collabhub-tasking-session.md)
   - Produit les API authentifiées, les tâches et les tentatives manuelles.
   - Gate : tests Python verts et cinq outils MCP inchangés.
2. [Interface partagée et coque WPF](2026-07-22-command-deck-ui-wpf.md)
   - Produit le Command Deck A réutilisable dans Titanium.
   - Gate : parité navigateur/WebView2 et identité Florent via HostBridge.
3. [Windows Action Broker](2026-07-22-windows-action-broker.md)
   - Produit preview, confirmation, sauvegarde, exécution allowlistée et audit.
   - Gate : aucune opération non allowlistée, sensible ou non réversible implicite.
4. [Lanceur et packaging](2026-07-22-command-deck-launcher-packaging.md)
   - Produit `Lancer CollabHub.exe`, l'installation Bureau et l'E2E Windows.
   - Gate : lancement idempotent, aucune collision de port, Titanium non démarré.

## Traçabilité de la spécification

| Exigence approuvée | Sous-plan / preuve attendue |
|---|---|
| Historique Claude/Codex/Hermes/Florent | CollabHub tasking + replay/offset UI |
| Chat et intervention Florent | session Windows attestée + `chat.publish` |
| Agents, santé et actions centralisées | rail/dock Command Deck + HostBridge allowlisté |
| `Échecs à suivre`, retry manuel | ledger d'échecs + nouvelle tentative explicite |
| Réutilisation future dans Titanium | module `collab_ui` sans primitive WPF |
| Écritures locales/Registre supervisées | preview, digest, backup, confirmation, helper UAC |
| Exécutable Bureau + VS Code + agents | launcher idempotent et diagnostic partiel |
| Aucun démarrage trading implicite | test E2E et absence de capacité compte réel |

## Gate de livraison globale

- [ ] Exécuter toutes les suites Python, Node et .NET listées dans les sous-plans.
- [ ] Exécuter `node .gitnexus/run.cjs detect-changes -s compare -b master -r titanium-v12` et expliquer tout risque HIGH/CRITICAL.
- [ ] Vérifier manuellement le compte MT5 ; refuser la livraison si le compte réel devient atteignable.
- [ ] Vérifier manuellement confirmation native, refus, expiration, anti-rejeu et prompt UAC séparé pour une cible L4 de test.
- [ ] Publier SHA-256 de l'exécutable et copie sur le Bureau.
- [ ] Consigner preuves et verdicts dans `collab/LOG.md`, `collab/REVIEWS.md` et CollabHub.
