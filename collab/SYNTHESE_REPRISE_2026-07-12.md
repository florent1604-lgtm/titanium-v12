# Synthèse de reprise — Titanium v12 (2026-07-12)

*Point d'étape consolidé par Claude à la reprise « step-by-step » demandée par
Florent. Source de vérité : `collab/` (TASKS, LOG, REVIEWS + audits datés).
Rien de nouveau n'est mis en production ici : ce document sert à décider ensemble.*

## 1. État des services (vérifié)

- Titanium API `8090` : **UP** — cockpit ORBE en interface par défaut (`/`),
  ancien dashboard réversible sur `/classic`. 36/36 tests verts.
- JARVIS `8765`/`8080` : **UP** (repli Claude/Ollama ; cerveau Hermes en quota
  jusqu'à 23:07 le 11/07, donc de nouveau disponible aujourd'hui).
- Garde-fous P0 intacts : bind localhost, auth fail-closed, **paper-only**,
  MT5 données-seulement.

## 2. Ce qui est LIVRÉ et validé

- **R1/R2/R3 (+R3c)** : correctness DONE — dédup barre, écritures atomiques,
  garde de risque portefeuille fail-closed ET transactionnel sur les 3 moteurs.
- **Dashboard ORBE** : livré, testé navigateur, branché sur le registre GitNexus
  (180 symboles). Audit a posteriori des 5 exigences de Codex encore à faire.

## 3. Les 3 audits microsoft/JARVIS — CONVERGENCE

| | Code Microsoft | Les 4 patrons (idées) |
|---|---|---|
| **Claude** | NO-GO | réimplémenter, registre fermé avant exécution |
| **Hermes** | (implicite) | c) ACCEPTE ; a/b/d MODIFIE ; proxy de capacités paper-only |
| **Codex** | **NO-GO confirmé** | APPROVE **sous ordre strict** |

**Consensus sur le mécanisme clé** : le « registre fermé » doit être une **vraie
frontière d'exécution codée** (schéma JSON strict, handler codé, READ/MUTATE,
`require_admin`, paper-only, timeout/idempotence/fraîcheur), **jamais** une URL ou
commande fournie par le LLM. Les trois agents disent la même chose.

**Correction honnête de Codex sur mon audit initial** (à intégrer) : la config
Microsoft documente des **placeholders** de clés, pas la preuve de vraies clés
publiées ; le taux d'injection et le `trust_remote_code` implicite ne sont **pas
établis** pour ce repo précis. → mon `AUDIT_MS_JARVIS.md` est à amender sur ces
deux points.

**Ordre de priorité conjoint des 4 patrons :**
- **P0** — Registre fermé = frontière d'exécution réelle (la brique de sécurité).
- **P1** — Pipeline plan→sélection→exécution→synthèse (validation hors LLM ;
  la synthèse ne transforme jamais un échec en succès).
- **P1** — TaskBench Titanium à oracle déterministe AVANT R6 (routage, params,
  refus sûr, stale, injection, replay, timeout, mutation sans admin).
- **P2** — EasyTool (instructions condensées) généré/hashé depuis le registre,
  sécurité jamais compressée, déployé seulement si non-régression au benchmark.

→ **Décision attendue de Florent** : valider les 4 patrons dans cet ordre.

## 4. MetaTester 5 — verdict Codex : **NO-GO en l'état** pour 8 agents en semaine

3 P0 avant toute réactivation :
1. **Sécurité** : remplacer le mot de passe faible (hors repo/logs), `UseCloud=0`
   (MQL5 Cloud désactivé), firewall sur 2000-2015, + preuve depuis une autre
   machine du LAN que les ports sont injoignables.
2. **Isolation** : data-dir tester séparé ; **jamais** taskkill/restart du terminal
   Titanium, **jamais** tenir `mt5_lock` pendant un test (2 scripts PS historiques
   violent ce garde — à corriger).
3. **Gouverneur mesuré** : priorité basse, pause avant `opportunity_scan`, arrêt
   si fraîcheur/latence scan/CPU régressent.

Montée proposée : **2 agents** après preuves P0 → 3 en séance → 4 après preuve →
**8 uniquement hors séance/week-end** avec `opportunity_scan` suspendu + arrêt auto.

**Confirmé (mémoire virtuelle)** : le SQL ne nettoie PAS la mémoire/pagefile/caches
Windows. Vrais leviers = réduire la concurrence, priorité, pagefile system-managed,
corriger les fuites. `EmptyWorkingSet`/purge standby/pagefile off **aggravent**
souvent les défauts de page.

→ Design d'un `tools/mt5_tester_runner.py` proposé par Codex (INI UTF-16LE
UseCloud=0, machine d'états atomique, rapports natifs hashés, parser fail-closed,
alimente le protocole M2, statut max `FORWARD_PAPER`).

## 5. GitNexus — infra implémentée NON-production (Codex)

Spec corrigée avec **tous les P0/P1 de Claude** + arbitrage **/orbe conservé,
/nexus séparé**. TDD **17/17 verts** : miroir JARVIS assaini, manifeste de hashes,
anti-churn `data/*.json`, debounce 5/15 s, pause `opportunity_scan`, spawn basse
priorité, plan session/snapshot. Handshake MCP global **suspendu** (quota
plateforme jusqu'à 23:07) → **rien de global exécuté, aucun serveur relancé, aucune
prod**. Fichiers orbe non touchés (réservation Claude respectée). Hermes confirmé
comme client MCP GitNexus possible.

## 6. Proposition de reprise « ensemble », dans l'ordre

1. **Florent valide** (ou amende) : les 4 patrons dans l'ordre P0→P2, et le
   principe du registre-frontière comme socle R6b.
2. On **amende `AUDIT_MS_JARVIS.md`** avec la correction de Codex (placeholders,
   pas de preuve de clés/trust_remote_code) — honnêteté du dossier.
3. **MetaTester** : Florent applique les 3 P0 sécurité/isolation → on autorise
   2 agents avec preuves, puis on construit `mt5_tester_runner.py` (Codex) relié
   à M2.
4. **GitNexus** : quand tu veux, on fait tourner la vérif MCP (quotas OK
   maintenant) et on branche `/nexus` — sans toucher `/orbe`.
5. **R4 TitaniumSnapshot** (Codex) : couche provenance qui alimentera les statuts
   de validation par stratégie du dashboard.

Aucune de ces étapes n'est lancée sans ton go. On reprend au rythme des
validations.
