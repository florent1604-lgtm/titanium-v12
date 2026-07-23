b# Plan Titanium v12 — direction & priorités (Claude + Codex, arbitré par Florent)

*v0.2 — co-signé Claude + Codex (revue Codex intégrée, voir LOG.md 2026-07-10).*

## Direction produit (décidée par Florent — NON négociable)

- **Multi-stratégie conservé** : crypto + forex + swing. PAS de swing-only.
- **La veille sur les 141 actifs MT5 est conservée et centrale** (scan d'opportunités
  quotidien à l'ouverture asiatique + persistance).
- Le vrai défaut à corriger n'est donc PAS « supprimer les stratégies », mais les
  **séparer proprement** : chaque stratégie a son portefeuille, son risque, ses
  preuves ; plus de mélange confus dans un seul pot.
- Garde-fou permanent : **paper only, MT5 données seulement**. Aucun ordre réel sans
  la séquence validée (forward paper → démo → micro-lots) sur décision de Florent.

## Priorités (issues de l'audit, filtrées et re-priorisées)

### P0 — sécurité (vrai risque immédiat, à faire en premier)
- Binder l'API sur `127.0.0.1` (aujourd'hui `0.0.0.0` = exposé LAN).
- **[Codex] Le bind localhost ne suffit pas** : ajouter une **auth fail-closed testée**
  sur TOUTE mutation (refus par défaut, secret hors UI et hors logs) — contre un
  navigateur/process local compromis.
- Retirer / protéger les routes de mutation : `/services/github/push` (git push depuis
  le dashboard), `/paper/reset`, start/stop services.
- Retirer le bouton « Push » Git du dashboard.

### P1 — correctness (peu coûteux, fiabilise la mesure)
- **Dédoublonnage par barre** dans swing/forex : après une fermeture, interdire la
  ré-entrée sur la MÊME barre clôturée (stocker `bar_id` traité + cooldown).
- **Écritures d'état atomiques** (temp + rename) — **[Codex] + verrou mono-écrivain** :
  temp+rename évite les fichiers partiels mais PAS les *lost updates* entre process
  concurrents. Prévoir un seul écrivain par fichier d'état (lock / propriétaire unique).
- **[Codex] Data gate commun** avant TOUTE décision : barre/tick clôturé, `source_ts`,
  âge maximal, comportement explicite si le flux MT5 est absent ou stale (→ pas de trade).
- **Risque portefeuille centralisé** : limite d'exposition agrégée + limite de cluster
  corrélé (ex. US_INDICES : USTECH+NAS100) AVANT la 2e position — **[Codex] + plafonds
  par stratégie ET gross/net**, pas seulement par cluster.
- Fixer `jarvis_agent.py` (ligne 77 ne compile pas) ou le supprimer s'il est mort.
- **Contrat de données JARVIS** : aligner les champs (`realized_pnl`/`winrate`,
  score sur **16** et non 13) + fraîcheur (`source_ts`/`stale_after`).
- Marquer le contenu web (résumés news) comme **non fiable** avant de le donner au LLM
  (anti-injection de prompt).
- **Migration du cerveau JARVIS** : remplacer le couplage direct à Gemini par
  **Hermes Agent comme cerveau principal et mémoire/orchestrateur de référence**.
  Claude Code et Codex restent des agents spécialisés connectés via le pont MCP
  et le bus append-only. Prévoir une interface fournisseur explicite, timeouts,
  fallback, budgets et latence observables, secrets hors code, tests de
  non-régression des commandes JARVIS et migration progressive. Gemini reste
  disponible comme fallback temporaire jusqu’à validation de parité, décision
  de bascule de Florent et procédure de rollback testée.

### P2 — méthodologie (avant TOUT argent réel)
- Une **fonction de stratégie pure** partagée entre le live paper et le backtest
  (élimine la divergence backtest↔live ; l'audit vise surtout le vieux
  `engine/optimizer.py` crypto — le `asset_optimizer` est déjà proche).
- Découpage **3 segments** (dev / sélection-validation / test final verrouillé une seule
  fois) au lieu de réutiliser la même OOS pour shortlister ET valider.
- Seuil minimum de trades + **[Codex] block bootstrap** (adapté aux séries dépendantes,
  pas le bootstrap i.i.d.) ; seuils fixés AVANT de voir les résultats ; sinon statut
  « observation », jamais « validé ». **PBO / Deflated Sharpe complètent, ne remplacent pas.**

### P3 — dashboard & confort (plus tard, non bloquant)
- Séparer visuellement les stratégies (crypto / forex / swing) et afficher pour
  chaque chiffre : source, âge du flux, clôture de barre, coût, statut de validation.
- Assets CDN → option offline + CSP (poste de décision).

## Répartition proposée (à ajuster)

- **Claude** : P0 sécurité, P1 correctness (dedup, atomic, contrat JARVIS), archi de
  séparation des stratégies.
- **Codex** : revue critique de chaque lot Claude + P2 méthodologie (il est fort sur
  la rigueur statistique) + audit continu.
- **Florent** : arbitre chaque passage `REVIEW → DONE`.

## Question ouverte pour Codex (à remplir dans LOG.md)
1. Es-tu d'accord avec cette re-priorisation (sécurité d'abord, multi-stratégie conservé) ?
2. Un P0/P1 que tu juges mal placé ou manquant ?
3. Prends-tu la partie P2 méthodologie ?
