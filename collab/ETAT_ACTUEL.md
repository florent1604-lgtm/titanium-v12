# État actuel Titanium v12 — briefing de reprise (maj 2026-07-13)

*Document COMPACT de démarrage pour Claude, Codex et Hermes. À lire en premier.*
*Historique détaillé → `collab/LOG.md` ; tâches → `collab/TASKS.md`.*

## Projet & garde-fous (NON négociables)

- **Titanium v12** : bot de trading algo, `C:\Users\flore\Desktop\v12`, API FastAPI
  port **8090** (bindée 127.0.0.1, auth fail-closed `ADMIN_TOKEN`).
- **PAPER ONLY** sur le compte RÉEL Axi (login 60261188) — jamais tradé.
- Compte **DÉMO** (Axi-US50-Demo, login 50061786) pour test d'exécution réelle
  (`order_send`), sous **mur démo↔réel fail-closed** (refus si login ≠ démo).
- Aucun changement de **logique de trading** en prod sans **protocole M2**
  (segments verrouillés, PBO, Deflated Sharpe). Traçabilité dans `collab/`.
  **Jamais de secret** dans le bus/logs/mémoire d'agent.

## Équipe & collaboration

- **Claude** = gouverneur technique / architecte / implémenteur.
- **Codex** = auditeur / red-team indépendant (`codex exec` ; runtime réparé,
  install complète 0.144.2 ; `tools/codex.ps1` pointe vers l'install complète).
- **Hermes** = cerveau/orchestrateur JARVIS ; grandit vers l'autonomie LOCALE ;
  mémoire locale `%LOCALAPPDATA%\hermes\memories\MEMORY.md`/`USER.md` enrichie
  (curée, sans secret). Vision : autonomie graduelle, least-privilege.
- **Florent** = arbitre humain final.
- Bus append-only : `node tools/collab_bus.mjs send/tail`. **Lire le tail au démarrage.**

## État des chantiers (compact)

| Chantier | État |
|---|---|
| P0 sécurité, R1/R2/R3(+R3c) correctness | **DONE** |
| Dashboard **ORBE** (`/orbe`) | livré ; orbe neuronale sur registre GitNexus ; `/classic` préservé |
| **Patron A** (orchestration LLM fail-closed) | `domain/agent_registry.py` + `orchestrator.py` + `voice_intents.py` (VoiceMutationGate) + `llm_planner.py` ; câblé JARVIS en priorité absolue ; tests verts |
| **Segment ÉMOTION v2** | `emotion/emotion_engine.py` — circumplex VALENCE×AROUSAL ; PANIQUE≠CAPITULATION, EUPHORIE≠COMPLAISANCE, ESPOIR ; RSI retiré ; fidélité données. **Read-only, M2 avant usage décision** |
| **Exécution DÉMO MT5** (étape D) | `execution/demo_mt5_executor.py` (rev.3 fail-closed) + `demo_bridge.py` câblé swing/forex. **Armé** (`DEMO_EXEC_ENABLED=1`, risque 7%, kill-switch -50%, limité par marge). Bilan : `docs/BILAN_DEMO_2026-07-13.md` (exécution validée ; 0 signal stratégie encore) |
| **Garde écriture GitNexus signé** (Ed25519) | `mcp_gitnexus_gate.py` + `tools/gitnexus_write_policy.py` — **RÉPÉTITION E2E RÉUSSIE (2026-07-15)** avec les vraies clés de Florent : 2 sigs → ACCEPTED ; 1 seule → REFUSÉE ; rejeu → REFUSÉ ; expiration → REFUSÉE. Outils : `tools/gitnexus_e2e_rehearsal.py` (propose/verify, jamais de downstream), `tools/gitnexus_sign_gui.py` (fenêtre Tk ; getpass inutilisable en terminal VS Code). Clé superviseur-perso **régénérée** (passphrase perdue) ; registre 1 entrée/acteur. Blocant `detect_changes` **levé par Codex** (fix final `tools/gitnexus_detect_changes.mjs`, stdout→TemporaryFile, stress 5/5) — **relecture Claude requise avant tout write RÉEL** |
| GitNexus | route `/nexus` (redirige 4747) ; registre commun 1.6.9 |

## MAJ 16/07/2026 (nuit) — faits établis

- **Calibration OOS PROPRE (smoke EURUSD/USTECH/XAUUSD, fenêtre commune 2022→2026,
  coûts Axi +25 %, risque 7 %)** : le scalp M15 trade + souvent (0,6/j) mais
  **espérance NÉGATIVE après coûts** sur les 3 (EURUSD −2,97 $/j, USTECH −2,11,
  XAUUSD −3,58 ; PBO XAUUSD 0,60). **H4 = INSUFFICIENT** (trop peu de trades).
  **Gagnant = USTECH H1 : +3,36 $/j, PF 1,24, Sharpe 1,0** (survit +25 % coûts).
  ⟹ baisser la TF : OUI mais vers **H1**, pas M15. Réserve : MT5 sans L2, coût
  scalp = borne optimiste ⟹ vrai test scalp = **crypto Binance L2**. Rapport :
  `docs/RAPPORT_CALIBRATION_2026-07-15.md`. Config de prod **INCHANGÉE** (proposition
  seulement). **RUN COMPLET 149 actifs TERMINÉ (16/07)** : 29 CALIBRATED,
  120 INSUFFICIENT, **0 proposition prod**. Meilleur = USTECH H1 (esp +5,67 bps,
  DSR 0,026 ≪ 0,50 → OBSERVATION). **BUG point/price CORRIGÉ par Codex le 16/07** :
  fallback `point → trade_tick_size → digits`, reprise bornée de cotation et
  statut `DATA_SPEC_INVALID` distinct ; 64/64 tests + smoke MT5 read-only 3/3.
  Après correction point/price : 70 actifs `POINTS`/`INTEREST_OPEN` sont en
  relance isolée par Claude. Les 50 autres sont désormais débloqués ensemble par
  Codex : `INTEREST_CURRENT` (30 cryptos, prix de rollover journalier) et
  `CURRENCY_SYMBOL` (20, montant base/lot normalisé par le notionnel). 71/71
  tests + smoke MT5 read-only BTCUSD/HSI.fs. Ces 50 restent à rejouer et fusionner
  avant tout verdict statistique ; configuration production inchangée.
- **RELANCE batch1 (16/07, 70 actifs modes POINTS+INTEREST_OPEN débloqués par le
  fix point/price)** : 63 CALIBRATED / 7 INSUFFICIENT, **0 validable prod**. Plus
  proche = XAUGBP swing (esp +57,87 bps, DSR 0,645 ✓ MAIS 0,07 trade/j → recalé
  manque de trades). Motif confirmé : swing = fort edge/trade mais trop rare ;
  scalp/intraday = fréquent mais edge faible/négatif ; aucune TF ne réunit les deux.
  Reste 50 actifs (30 crypto INTEREST_CURRENT + 20 CURRENCY_SYMBOL) EN ATTENTE du
  fix swap Codex — les cryptos = terrain L2 de la thèse scalp, priorité.
- **VERDICT THÈSE SCALP (16/07) — NON, sur son propre terrain Binance.** Probe
  `tools/binance_scalp_probe.py` (réutilise le moteur Codex, données Binance spot,
  frais round-trip 15 maker/20 taker après red-team Codex sur le per-side→RT).
  Meilleure config scalp M15, in-sample (meilleur cas), MAKER : BTCUSDT −11,71,
  ETHUSDT −2,61, SOLUSDT −13,75 bps/trade → tous NÉGATIFS. Cause : edge ~qq bps <
  péage RT 15-20 bps. Le spread Axi tuait bien le scalp (Binance spread ~0) mais
  les FRAIS sont le mur. **Vraie piste = H1/intraday** (BTCUSD intraday +27,81 bps
  brut a de la marge). Driver M2 Binance propre (OOS+PBO+DSR) en cours côté Codex
  pour confirmation formelle. `tools/binance_history.py` = source données livrée.
- **Correction P0 Binance (16/07, Codex)** : le premier
  `binance_scalp_probe.py` est **diagnostique invalide pour un verdict chiffré** :
  il soustrayait 10/7,5 bps une seule fois alors que ce sont des frais par côté
  (20/15 bps aller-retour). Les résultats déjà négatifs ne deviennent donc pas
  meilleurs, mais leurs valeurs exactes ne doivent pas être citées. Le driver
  M2 isolé `tools/binance_optimizer_m2.py` applique 22,25 bps TAKER et 17,25 bps
  MAKER avec spread stressé ; 82/82 tests calibration/validation passent. Run
  réseau 10 actifs × 2 scénarios à lancer par Claude ; aucune production.
- **VERDICT FORMEL M2 BINANCE (16/07) — CONFIRMÉ : scalp = NON.** Run
  `tools/binance_optimizer_m2.py` (Codex), 10 cryptos × taker/maker, OOS+PBO+DSR,
  frais round-trip corrects (15 maker / 20 taker, scope round_trip_total). Sortie
  `data/calibration_binance_2026-07-16`. **0 proposition de production sur 20
  combinaisons.** Scalp expectancy nette négative partout en taker ; négative 9/10
  en maker ; seul ETHUSDT maker marginalement positif (+0,0038) mais proposed=null
  (ne passe pas DSR/PBO). La thèse scalp est close, sur son propre terrain, avec la
  méthode rigoureuse. **Config prod inchangée. Prochaine piste = H1/intraday.**
- **4 biais anti-scalp démontés** : entonnoir (scalp absent de la passe 1), OOS
  consommé par la sélection, bug fetch M15 (`--years 4` > limite d'appel → « no
  rates »), + une fausse contrainte de ma part (2,5 ans). Fetch corrigé = chunk
  `copy_rates_range` (99 989 barres, 4 ans, testé).
- **Trade démo validé bout-en-bout** : ordre manuel EURUSD LONG 0.17 @1.1464 vu
  par Florent sur MT5 iOS. Journal démo `execution/demo_journal.py` ACTIF (chaque
  tentative + émotion observée, non fatal). day-ref ré-écrite sur la VRAIE equity
  950,08 (P0 corrigé : un test écrivait la réf de prod).
- **Skill `collab-discipline`** créé (5 règles : résultat d'abord, contexte porté,
  1 doc fait foi, pas de vN, mesurer une fois). Refus assumé : intrusion/dark web.

## Décisions & attentes

- Risque démo **7%** (décision Florent, assumée — c'est de la démo).
- **En attente** : fix `detect_changes` (Codex/GitNexus) avant test bout-en-bout
  écriture ; re-revue Codex du segment émotion et de la démo rev.3 ; enrichir
  l'émotion (compléter le cycle : désespoir/thrill ; brancher vraies données) via M2.
- Vision produit : Hermes autonome/local **humanisé** dans sa décision (segment
  émotion) ; mentors Claude+Codex ; élargissement progressif ; **rien de caché,
  aucun secret, aucun clone** — au grand jour.

## Tests

`venv\Scripts\python.exe -m pytest tests/ -q`

## MAJ 17/07/2026 — ENTRY_DETECTION

- Claude a ajouté quatre briques **standalone, non câblées** :
  `core/candlestick_engine.py`, `core/volume_profile.py`, `core/fib_ote.py` et
  `core/sr_levels.py`, avec 20 tests annoncés verts côté Claude.
- Revue Codex : **BLOCK avant intégration au labo/score**. P0 commun : le pipeline
  ne garantit pas des bougies clôturées (dernière kline REST et bucket WS courant),
  donc les détecteurs peuvent repeindre malgré des fonctions localement causales.
- Autres P0 : `candlestick_engine.net_bias` compte des candidats non confirmés et
  double-compte des patterns corrélés ; `smc_engine.ob_status` peut retourner
  `tested` avant une cassure ultérieure (impact GitNexus **HIGH**) ; le score /16
  additif ne matérialise pas la confluence obligatoire de Florent.
- Handoff détaillé et lot correctif unique sur le fil `ENTRY_DETECTION` :
  `33240967-4ecd-4839-8df3-64a4ebfbf896`. **PAPER ONLY**, aucun câblage ni
  changement de logique production avant correctifs, re-revue et protocole M2.

## MAJ 17/07/2026 — ENTRY_DETECTION lot correctif 2 (re-revue Codex traitée)

Codex avait rendu (17/07 08:38, thread `REVUE_CONFLUENCE_LOTS_1_4`) : **BLOCK câblage /
GO modules isolés**, avec 7 points + son venv cassé (non portable). Claude a corrigé les
7 et débloqué le venv — **65/65 verts, dont preuve en venv NEUF** ; RIEN câblé, PAPER ONLY :

1. **fail-open `edge_ok` supprimé** : `edge_ok=None` (adapter), gate `require_edge`.
   **PROD = fail-closed** (edge non prouvé ⇒ `BLOCK_EDGE_UNPROVEN`) ; **DÉMO/EXPLORE**
   (`require_edge=False`) = on prend le trade sur MT5 pour **mesurer** (consigne Florent :
   backtester CHAQUE stratégie, ne pas trop restreindre).
2. **cohérence temporelle** : `decided_at` commun, as-of par TF, garde alignement HTF/LTF,
   prix de réf = dernière clôture LTF (plus d'intrabar).
3. **`data_valid` durci** : `closed_bars.validate_frame` (index monotone/unique, OHLC
   finies/cohérentes, staleness).
4. **`net_bias_on_df`** : automate de confirmation **N+1** (candidat actionnable seulement
   confirmé par la bougie close suivante).
5. `_etoile`/`_soldats` : `not bull` → **bear strict**.
6. `binance_kline_feed.CloseDedup` : **dédup + garde d'ordre** + callback async.
7. **trace** : reason-codes stables + `decision_id` + version (gate 1.1.0).
   + archi Codex : **setup_side** (reversal porté par le setup, trend = contexte) — à valider.

Venv Codex débloqué : `requirements-test.txt` + `tools/rebuild_test_venv.py` (venv neuf
`.venv_test`, chemin relatif) → `py -3.12 tools/rebuild_test_venv.py` = 65/65.

**En cours** : boucle Codex relancée (`codex exec </dev/null`) pour re-review + validation
du split continuation/reversal + relance de sa boucle. **Reste (lot 3)** : `ob_status`
touch→break (P0 GitNexus HIGH), durcissement VPOC/Fib/SR, labo confluence (multiplicité).

## MAJ 17/07/2026 (13h30) — ENTRY_DETECTION vérifié par les DEUX agents + lot 3

- **Python embeddable workdir-local** (`.pyembed/`, gitignore, `tools/setup_embed_python.sh`) :
  résout le vrai blocage Codex (son sandbox n'a AUCUN Python accessible). Codex a rejoué
  la suite LUI-MÊME → **PASS EXÉCUTABLE INDÉPENDANT (75/75, exit 0)**.
- **Lot 3 fait par Codex, test-first** : P0 `ob_status` touch→break corrigé (broken prime
  sur une touch antérieure ; GitNexus HIGH : has_ob_or_fvg_alignment → score_setup →
  scan_symbol → scan_loop) ; VPOC/Fib/SR durcis (rejet params/prix/OHLC/volumes non
  finis ou incohérents) **sans resserrer les stratégies**. Codex : **88 passed**.
- Vérif Claude (venv + embeddable) : lot + ob_status = **84/84**. Split reversal/continuation
  (setup_side/setup_family) validé : reversals contre-tendance autorisés, trend=contexte,
  DEMO/EXPLORE ouvert.
- **Verdict Codex** : **GO pour backtester CHAQUE stratégie en DÉMO/EXPLORE sur MT5** ;
  **BLOCK PROD/CÂBLAGE** jusqu'à protocole **M2** + go explicite Florent. Aucun ordre,
  aucun câblage prod. La stack de détection est BÂTIE et vérifiée des deux côtés ; reste
  à la brancher sur l'exécuteur DÉMO MT5 (mur démo↔réel) pour OBSERVER, sur go Florent.

## MAJ 17/07/2026 (11h46) — CÂBLAGE DÉMO CONFLUENCE (go Florent)

- **`core/confluence_demo_engine.py`** : câble la stack (adapter → portes ET, mode
  EXPLORE) sur l'exécuteur DÉMO MT5 (`demo_bridge.place_demo_async`). `decide()` pur,
  `run_once()` deps injectables (tests sans MT5/réseau). Sur ENTER → ATR (bougies
  clôturées) → ordre DÉMO. Fail-safe par symbole. État exposé (trace « pourquoi »).
- **DOUBLE GATE** : `CONFLUENCE_DEMO_ENABLED=0` (boucle) + `DEMO_EXEC_ENABLED=0`
  (ordres). Loop active seule = décisions OBSERVÉES sans ordre ; ordres seulement si
  les deux + **mur démo↔réel** (compte démo 50061786 requis). Rien vers le RÉEL.
- Câblé : `utils/config.CONFLUENCE_DEMO_*`, boucle `_confluence_demo_loop` (lifespan,
  gated), route `GET /confluence/demo/status`. Data MT5 `get_ohlcv` (M15+H4).
- Tests `tests/test_confluence_demo_engine.py` (5). Suite chantier = **89/89** (venv + .pyembed).
- **En attente** : revue red-team Codex du câblage (task `CONFLUENCE_DEMO_WIRING`) +
  Florent bascule MT5 sur le compte DÉMO + arme les 2 flags. Claude n'arme PAS lui-même.

- **Codex GO câblage démo** (task CONFLUENCE_DEMO_WIRING, 11h50) : aucun P0 ; mur
  démo↔réel confirmé en amont de order_send ; double gate OK ; 77 tests élargis verts.
  2 réserves non bloquantes TRAITÉES par Claude : heartbeat au statut + test SHORT
  (moteur démo 7/7). Réserve opérationnelle → prérequis Florent : terminal DÉMO dédié.

## MAJ 17/07/2026 (13h00 UTC) — MOTEUR CONFLUENCE DÉMO ARMÉ ET EN DIRECT

- `.env` : `CONFLUENCE_DEMO_ENABLED=1` (+ `DEMO_EXEC_ENABLED=1` déjà présent),
  `CONFLUENCE_DEMO_SYMBOLS=XAUUSD,EURUSD,US500,NAS100.fs` (US500.fs invalide → US500).
- Bot **redémarré proprement** (2 instances main.py doublonnées → 1 seule, venv).
  Compte MT5 = DÉMO 50061786 (equity ~951 USD). Boucle confluence active (5 min),
  0 erreur, décisions visibles sur `GET /confluence/demo/status` (trace « pourquoi »).
- 0 position (confluence sélective ; EURUSD le plus proche : 3/5 piliers short).
- **TODO durcissement (Codex)** : `mt5_provider.get_ohlcv/get_rates` étiquettent l'heure
  SERVEUR Axi (UTC+2/3) comme UTC → les timestamps de décision sont en heure serveur.
  Causalité OK ici (offset positif ⇒ bougie en formation bien retirée), mais FRAGILE si
  offset ≤ 0. À aligner (convertir l'heure serveur→UTC, ou passer un `now` serveur à
  closed_bars pour MT5). Décisions non faussées, mais à durcir avant tout passage prod.

## MAJ 18/07/2026 — CONFLUENCE MULTI-ACTIFS : crypto MT5 (ajusté Binance) + mission Codex

- **Crypto sur MT5** (décision Florent : MT5 = passerelle principale, ajusté Binance).
  Crypto Axi (BTCUSD,ETHUSD,XRPUSD,LTCUSD,BCHUSD,ADAUSD) LIVE + tradable 24/7 le
  week-end sur le démo → même moteur confluence, `venue=crypto` (pas de blocage we),
  MT5 data + exécution. `data/binance_ohlcv.py` (`reference_close`, `mt5_to_binance`)
  ajoute la RÉFÉRENCE Binance (prix + divergence, <0,35% constaté). Boucle confluence
  unique = CFD (`CONFLUENCE_DEMO_SYMBOLS`, venue cfd) + crypto (`CONFLUENCE_CRYPTO_SYMBOLS`,
  venue crypto), `ref_fn=reference_close`. `.env` : `CONFLUENCE_CRYPTO_ENABLED=1`.
- **Niveaux entry/SL/TP ladder** (1.5/2.5/4.0 ATR, R:R) dans Telegram + dashboard.
- **Route** `/confluence/demo/status` : watchlist CFD+crypto, `crypto_enabled`, `reference`.
  Dashboard : tag CRYPTO + ligne Binance. 73 tests verts, 0 erreur en direct.
- **MISSION CODEX** (`PLAN_CONFLUENCE_MULTIACTIFS`, demande Florent) : A red-team câblage
  crypto ; B **concordance inter-actifs (lead/lag) pour ANTICIPER** (base
  `latency_bench._best_lag_ms`, gardes stat, M2 avant câblage) ; C module agressif ;
  D durcissement heure serveur MT5→UTC ; E couverture 100% CFD ouverts. Codex relancé.
- **À FAIRE** : exécution ladder TP (sorties partielles) sur le démo ; les volets B/C/E.

## MAJ 18/07/2026 (07h10) — Codex : A/D livrés, B = plan M2 concordance

- **Codex A (câblage crypto)** : GO démo (BLOCK prod). Durci : référence Binance
  UNIQUEMENT venue=crypto, prix NaN/inf/≤0 rejetés, réseau HS → None non bloquant.
  ⚠️ L'ajustement Binance est **AFFICHÉ SEULEMENT** (ne décide pas) ; décisionnel = M2.
- **Codex D (heure serveur MT5→UTC)** : corrigé test-first (Axi EET/EEST → UTC via
  Europe/Helsinki, `MT5_SERVER_TIMEZONE` surchargeable) dans get_rates/get_ohlcv.
  Blast HIGH (forex+swing+confluence+forward) mais suite pleine = 514 passed (5 échecs
  = paper flaky pré-existants). **Effet vertueux** : la staleness détecte enfin les
  marchés fermés → CFD `data_valid=False` le week-end (correct), crypto actif.
- **Codex B (concordance lead/lag)** : BLOCK câblage. Plan M2 écrit
  `collab/PLAN_CONFLUENCE_LEAD_LAG_M2.md` (registre fermé, FDR+Holm, block bootstrap,
  PBO≤0.20, DSR≥0.50, coûts Axi, split 50/20/30). `_best_lag_ms` seul insuffisant.
- **Ordre Codex** : A → D → B(M2 offline) → E (inventaire read-only) → C (agressif, M2 séparé).
- État LIVE : bot relancé (UTC), crypto actif week-end, 0 erreur.

## MAJ 18/07/2026 (08h06) — CONCORDANCE inter-actifs : recherche à 3, verdict M2

- **Claude** : scanner lead/lag exploratoire `tools/lead_lag_scan.py` + boucle
  `core/lead_lag_engine.py` (route `/leadlag/status`, débrief Telegram) + 6 tests.
  1er scan crypto : candidats FAIBLES (SOL→BCH, ETH→XRP, LTC→BCH, lag~2, corr~0.13,
  flip 55-61%).
- **Codex M2 (verdict)** : **0 PAIRE NE SURVIT**. BH-FDR/Holm = 0 ; bootstrap gains
  strictement négatifs ; **coûts RT Axi (BCH 44.8 bps, XRP 36.2 bps) rendent tout net
  négatif** ; DSR=0. Le flip-rate court (58-60%) NE PERSISTE PAS OOS (uplift +0.06-0.08).
  Rapport : `collab/REVUE_LEADLAG_M2_CODEX_2026-07-18.md`.
- **Bug P0 trouvé par Codex** dans mon scanner : `_crypto_fetch` gardait la bougie EN
  FORMATION → faux lead/lag de transport. **CORRIGÉ** (bougie clôturée only, index trié/unique).
- **CONCORDANCE Claude↔Codex** : d'accord — les candidats actuels = **BRUIT**, non tradables.
- Suite : test turning-point PROPRE formalisé par Codex (flip résiduel, hazard baseline,
  purge+embargo, log-loss/Brier) ; élargir actifs/TF ; la boucle continue (pré-M2, ne
  décide RIEN). Hermes débriefe. AUCUN câblage trading.

## MAJ 18/07/2026 (14h) — Module AGRESSIF + lead/lag MULTI-TF (phase de test)

- **Agressif** (surcouche, sans toucher aux portes strictes) : setup 4/5 structuré
  (n_pillars≥`CONFLUENCE_AGGRESSIVE_MIN=4` ∧ trend_sr ∧ direction) → `summary.aggressive`
  + alerte Telegram ⚡. Exécution démo GATED `CONFLUENCE_AGGRESSIVE_EXEC` (défaut 0, tag
  `confluence-aggr`). À cadrer risque par Codex (famille M2 séparée).
- **Lead/lag MULTI-TF** M15/H1/H4 (`LEADLAG_TFS`). H4 donne un candidat PLUS FORT :
  SOL→ADA lag8 corr +0.24 flip55% (vs M15 0.14) → hypothèse macro-plus-nets-en-H4
  confirmée. Toujours pré-M2 (à valider Codex). Route `/leadlag/status` = by_tf.
- 61 tests verts. Bot relancé. Rien câblé décisionnel.

## MAJ 19/07/2026 — AUDIT ARCHI + axe G (référentiel instruments)

- Audit `collab/AUDIT_ARCHITECTURE_V12.md` : constat = **cerveau non câblé au runtime**
  (orchestrator/Patron A : 0 appelant in-repo, confirmé GitNexus). Contre-revue Codex
  `collab/CONTRE_REVUE_ARCHITECTURE_V12_CODEX_2026-07-19.md` : ACCORD + nuances fortes —
  **centre = PolicyKernel déterministe (pas le LLM)**, Hermes observe/propose, registre
  fermé = unique frontière efférente ; **bus actuel impropre au contrôle** ; D ≠ AND naïf
  (leadlag mort M2, émotion observationnelle). Priorité : invariants → G → E0/B0 → F0 → D0 → C0/C1.
- **Axe G EXÉCUTÉ** : `core/instruments.py` (référentiel unifié, 30 instruments, ticker+venue+
  binance_ref+classe), `binance_ohlcv.mt5_to_binance` délègue (rétro-compat), 27 tests. Hors
  chemin critique. GitNexus RESTAURÉ par Codex (axe A fait) + `tools/structural_mcp.py` (revu GO).
- **Prochain (à co-concevoir à 3)** : invariants + event plane control-grade + E0 cortex snapshot.
  Rien d'actif câblé sans design Codex + go Florent. Agressif tourne (data), consensus observe.

## MAJ 19/07/2026 — FUSION Hermes : B0 EventPlane livré (contrat Codex)

- Contrat de fondation `collab/CONTRAT_FUSION_HERMES_EVENTPLANE_COMMANDGATEWAY_2026-07-19.md`
  (Codex, 18 invariants). Vision actée : fusion Hermes 300% = afférent+mémoire+propositions,
  MAIS jamais sur la gâchette (efférent via registre fermé, revalidation déterministe au sink).
- Livré : **G** (`core/instruments.py`), **E0** (`core/cortex.py` + perception Hermes via le
  pack de connaissance), **B0** (`core/event_plane.py` : EventPlane SQLite/WAL append-only,
  hash-chaîné, idempotent, contrat Codex, 7 tests). B0 DORMANT (aucune commande, aucun effet).
- **Prochain** : C0 = miroir read-only (moteurs → faits dans B0). Proposé : mirror depuis le
  Cortex (sans toucher le code des moteurs). En attente revue Codex de B0 + accord C0.
- Agressif tourne (data), consensus observe. Rien d'actif sur le chemin critique.

## MAJ 19/07/2026 — FUSION : plan AFFERENT LIVE (observabilité read-only)

- Codex a durci mon B0 sur ma red-team : `core/event_registry.py` (registre GELÉ par
  digest SHA256 + `validate_payload` + `assert_secret_free` R-3) ; `event_plane` health
  `transport_mode=SQLITE_FALLBACK`. R-3/R-4/R-6 clos.
- Claude : `event_mirror` (C0a) RÉALIGNÉ sur le registre gelé (result/side/reason_codes…).
- **CÂBLÉ + LIVE (read-only)** : boucle `_eventplane_mirror_loop` (`EVENTPLANE_MIRROR_ENABLED=1`),
  routes `/eventplane/health` + `/eventplane/read`, cortex expose head_offset/intégrité.
  Chaîne afférente : moteurs → FAITS (EventPlane B0) → Cortex (E0) → perception Hermes.
  22 tests verts, 0 ordre, 0 CommandGateway, 0 effet trading.
- **RESTE pour l'EFFERENT** (CommandGateway, plus tard) : R-1 (NATS vs SQLite mono-hôte),
  R-2 (auth Hermes local), R-5 (autonomie démo hors gateway). À trancher avant tout C1.
- Agressif tourne (data), consensus observe.
