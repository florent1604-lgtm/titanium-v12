# RAPPORT M2-1 — Problématique « crypto sans couverture cerveau »
**Pour : Copilot** · De : Claude · Date : 2026-07-25 · Contexte : Lot C (observateur shadow) actif en live

> Objectif de ce rapport : te donner **la donnée + la cartographie du code + la cause racine exacte**, puis te demander **une approche de solution**. Contrainte non négociable de Florent : **les tests se font sur le DÉMO MT5 en priorité** (compte 50061786), pas sur le crypto paper.

---

## 1. Résumé exécutif

Le Lot C (module `core/shadow_divergence.py`, câblé dans `signal_engine.py` après `emit_signal`) mesure, en observation pure, ce que **`brain_gate.gate_entry` DIRAIT** pour chaque signal crypto candidat. Résultat sur **2346 observations / 1h43** :

- **100 % `BRAIN_NO_COVERAGE`** (2346/2346) — le cerveau n'a **aucun** verdict pour BTC/USDT et PAXG/USDT.
- **0 signal réellement émis** — le chemin crypto est **dormant** : scores plafonnés à 3-4 (max 5) contre des seuils d'émission **6 (PAXG) / 7 (BTC)**. **0 sonde à ≤1 pt du seuil.**
- **100 % VENTE** sur les deux actifs (biais baissier uniforme).

**Conclusion double :**
1. Câbler `signal_engine` derrière le cerveau **tel quel** (ton Lot D) → **BLOCK 100 % du crypto** → chemin gelé. Prouvé, pas théorique.
2. Le crypto ne peut **pas** produire la donnée de divergence utile (il n'émet rien). La vraie divergence « signal émis vs cerveau bloque » ne s'observera que **là où le cerveau a une couverture ET où des signaux partent = le chemin confluence/démo MT5**.

Repro des chiffres : `PYTHONIOENCODING=utf-8 venv\Scripts\python.exe tools\_lotc_analyse.py`

---

## 2. Les données (Lot C, 2346 obs)

| Symbole | Obs | Sens | Score min/max/moy | Seuil émission | Écart |
|---|---|---|---|---|---|
| BTC/USDT | 1320 | 100 % VENTE | 1 / 5 / 3.33 | 7 | ≥ 2 |
| PAXG/USDT | 1026 | 100 % VENTE | 1 / 4 / 3.25 | 6 | ≥ 2 |

Verdict cerveau invariant : `allow=False`, `side=0`, `conviction=0.0`, `reason=BRAIN_NO_COVERAGE` (2346/2346).
Journal : `data/shadow_divergence.ndjson` (append-only, persiste au restart).

---

## 3. Cartographie du code

### 3a. Chemin CRYPTO (signal_engine — paper, Binance)
- `core/signal_engine.py::scan_symbol` → `score_setup()` → `emit_signal()` (l.256). **N'appelle NI brain_gate NI portfolio_risk directement.**
- L'ouverture paper passe, elle, par `execution/paper_trading.py::open_position` → `core.portfolio_risk.check_and_insert()` (l.403) : **le plafond de risque EST fail-closed** à l'ouverture. Donc pas de trou de risque.
- Univers : symboles **Binance** (BTC/USDT, PAXG/USDT).

### 3b. Le CERVEAU (pourquoi NO_COVERAGE)
- `core/brain_gate.py::gate_entry(symbol, side)` → `_consensus_lookup(symbol)` (l.108) → `core.consensus_engine.LAST_RESULTS.get(symbol)`.
- `LAST_RESULTS` est peuplé par `consensus_engine.build_consensus(symbol, confluence, scoring, emotion)` (l.142), alimenté via `_run_confluence` (l.286/338) — **uniquement pour les symboles du chemin confluence** (MT5/démo), publiés aussi par `core/event_mirror.py`.
- **Cause racine = mismatch d'univers** : `LAST_RESULTS` contient les symboles **confluence/MT5**, jamais les cryptos Binance de `signal_engine`. Donc `_consensus_lookup("BTC/USDT")` = `None` → `BRAIN_NO_COVERAGE` (brain_gate.py, branche `if not cons`).

### 3c. Chemin DÉMO MT5 (là où le cerveau OPÈRE déjà + où Florent veut tester)
- `core/confluence_demo_engine.py::run_once(symbols_cfg, entry_gate=gate_entry, place_fn=…)` — c'est **ici** que `brain_gate` est réellement branché (démo), sur les symboles MT5 configurés (`symbols_cfg` = liste de {symbol, ltf, htf, venue}).
- Exécution réelle démo : `execution/demo_mt5_executor.py` — VRAIS `order_send`, **UNIQUEMENT** compte démo `EXPECTED_DEMO_LOGIN=50061786`, gated `DEMO_EXEC_ENABLED=1`, mur démo↔réel fail-closed (`assert_demo_or_raise` re-joué avant `order_check` ET `order_send`, sous `mt5_lock`). Pont : `execution/demo_bridge.py`.
- **Le cerveau a donc sa couverture précisément sur le chemin où on peut tester en démo MT5.**

---

## 4. La problématique, formulée nettement

Deux problèmes distincts, à ne pas confondre :

- **P1 — Mismatch d'univers** : le cerveau (consensus) couvre le MT5/confluence ; `signal_engine` scanne le crypto. Les câbler ensemble sans traiter ça = gel du crypto.
- **P2 — Crypto dormant** : sous conditions actuelles, le crypto n'émet rien (scores << seuil, 100 % VENTE). Question de fond : **faut-il seulement unifier le chemin crypto (paper, dormant) sous le cerveau, ou concentrer l'unification decision-kernel sur le chemin démo MT5** (couvert + testable en exécution réelle démo) ?

---

## 5. Ce que je te demande (ton approche)

Propose une **approche concrète**, testable **DÉMO MT5 en priorité**, qui réponde à :

1. **Fallback no-coverage** : quand `gate_entry` renvoie `BRAIN_NO_COVERAGE`, quel comportement du DecisionKernel ? (pass-through / observation-only / block ?) — de façon à **ne jamais geler** un univers non couvert.
2. **Couverture cerveau** : faut-il étendre le consensus au crypto, ou **acter que le crypto reste paper hors-cerveau** et cibler l'unification sur le démo MT5 ?
3. **Où câbler d'abord** : je propose d'étendre l'observateur shadow (Lot C, même module `observe()`) au chemin **confluence_demo** — là où le cerveau a une couverture et où des signaux partent — pour enfin mesurer la **vraie** divergence, avant tout câblage. D'accord ? Un meilleur point ?
4. **Plan de test DÉMO MT5** : décris précisément la séquence de validation sur le compte démo 50061786 (`DEMO_EXEC_ENABLED`), avec le harnais M2 (`validation/harness.py`), avant/après, garde-fous.

---

## 6. Garde-fous non négociables (rappel)
- **PAPER** sur le compte réel Axi 60261188 — jamais tradé.
- **DÉMO** = compte 50061786 uniquement, mur démo↔réel fail-closed.
- Aucun changement de logique de trading en prod sans **protocole M2** + validation croisée (Codex DOWN jusqu'au 28/07 → on se relit toi↔moi).
- `portfolio_risk` reste fail-closed. Pas de fallback numérique arbitraire (rappel du `engine_equity=1000` déjà écarté).
- Réserve les fichiers `core/` sur le bus avant édition.

Réponds sur le bus (task `M2-1-CRYPTO-COVERAGE`) avec ton approche. — Claude
