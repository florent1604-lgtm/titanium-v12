# Rapport de la nuit — 28/07/2026

*Fenêtre : 27/07 14:40 UTC → 28/07 04:40 UTC (~14 h). Source : journal non censuré
(`data/journal/titanium_journal.sqlite3`) + `/health` + `/confluence/demo/status` en direct.*

---

## 1. En un coup d'œil

| Indicateur | Valeur |
|---|---|
| Compte démo (login 50061786) | **equity 300.25 €** · balance 327.70 € · **flottant −27.45 €** |
| Positions ouvertes | **18** |
| Ordres ouverts sur la nuit | **82** (≈ 64 déjà refermés par SL/TP/gestion) |
| Signaux / décisions | 6 012 / 6 012 |
| Refus journalisés (ghosts) | **3 730** (le bot a filtré ~62 % de ses intentions) |
| Cycle fusion | OK, 149 symboles suivis, 0 erreur |
| RiskGate | **actif en véto additif** (pas encore porte unique) |

**Lecture :** le compte est en **repli** (equity 300 contre ~353 le 27/07). C'est cohérent
avec l'état connu : la stratégie est **structurellement net-négative** et le sizing par
**confiance Cloe** garde volontairement des lots petits pendant qu'on **collecte les données**.
La nuit n'a rien cassé — elle a produit de la donnée d'apprentissage.

---

## 2. Crypto — la vérité (elle n'était PAS éteinte)

`crypto_enabled: true`, `orders_armed: true`, watchlist crypto = BTCUSD, ETHUSD, XRPUSD,
LTCUSD, BCHUSD, ADAUSD. **La crypto a bien été scannée toute la nuit** (167 décisions/actif).

**Ce qui a tradé** (via l'auto-univers, noms Axi à tiret) :
`MANA-USD ×3`, `AAVE-USD`, `AVAX-USD`, `BNB-USD`, `ETH-JPY`, `XRP-JPY` → **8 entrées crypto**.

**Ce qui n'a PAS tradé, et pourquoi** (c'est le vrai point) :

| Actif | Décisions | Fills | Raison dominante |
|---|---|---|---|
| **BTCUSD** | 167 | 0 | **BRAIN_SIDE_CONFLICT ×87** (le cerveau/consensus contredit le sens) + BLOCK_PILLAR_MISSING ×36 + WAIT_NO_SETUP ×29 + `RISK_LOT_MIN_EXCEEDS` ×4 (lot min 0.1 > budget risque ~2.4 €) |
| **ETHUSD** | 167 | 0 | **WAIT_NO_SETUP ×134** (pas de setup, légitime) + pilier manquant ×29 |

➡️ **BTC est bloqué**, pas éteint : soit le cerveau refuse le sens (52 % des cycles), soit
le lot minimum de 0.1 BTC pèse **plus** que le budget-risque rétréci par la confiance basse
(~2,4 €). ETH, lui, n'avait tout simplement **aucun setup**.

**Conséquence pour ta demande « réactive la crypto » :** elle est déjà active et armée.
Pour que **BTC/ETH tirent réellement**, il faut lever un des deux verrous — décision à prendre
(voir §5), je n'ai **rien changé au sizing sans ton go** (ça contredirait ta règle « lot petit
tant qu'on perd »).

---

## 3. Tous les actifs MT5 — le scan tourne déjà

- Le moteur démo scanne **149 symboles MT5 en continu** (auto-univers `CONFLUENCE_DEMO_AUTO_UNIVERSE=1`).
- Le **scan d'opportunités quotidien a tourné cette nuit à 00:33 UTC** sur les 141 actifs
  liquides → **0 nouvelle opportunité chaude** retenue (filtre persistance/récence).
- ✅ **J'ai relancé un scan complet frais à ta demande** (`POST /opportunities/run`) — en cours
  (`running: true`, « scan univers… »). Résultat visible sur `/opportunities/status`.

Les entrées de la nuit couvrent **~44 symboles** : FX (EUR/GBP/AUD/USD croisés, exotiques
NOK/HUF/THB/SGD/PLN/CNH…), indices (US30, EU50, US500/S&P.fs, GER/UK/FRA), matières
(XAU, XPT, COPPER, USOIL/UKOIL/BRENT/WTI), et la crypto ci-dessus. Le balayage est **large**.

---

## 4. Ce que le bot a refusé (3 730 ghosts) — ses garde-fous travaillent

| Raison de refus | Occurrences | Sens |
|---|---|---|
| `BLOCK_PILLAR_MISSING` | 1 982 | Pas assez de piliers de confluence → prudence |
| `RISKGATE_DENY:FONDAMENTAUX_BLOCK` | 585 | Véto macro/news du RiskGate |
| `COUNTER_TREND_BLOCKED` | 584 | Filtre anti-fade (contre-tendance sans retournement prédit) |
| `BRAIN_SIDE_CONFLICT` | 429 | Le cerveau/consensus contredit le sens |
| `RISKGATE_DENY:COUT_TROP_ELEVE` | 66 | Coût aller-retour trop lourd |
| `NOT_BETTER_SETUP` | 60 | Multi-position refusée (setup pas strictement meilleur) |
| `RISKGATE_DENY:CONTRE_TENDANCE` | 20 | Contre-tendance H4 nette |
| `GEOM_TOPOLOGY_ALERT` | 9 | Rupture de régime géométrique |

➡️ Le RiskGate **agit déjà** (671 refus fondamentaux/coût/contre-tendance cette nuit) même
s'il n'est pas encore la porte unique d'exécution.

### ⚠️ 2 anomalies techniques à corriger (mineures)
- **`retcode 10030 Unsupported filling mode` ×6** sur les futures `.fs` : `CAC40.fs`,
  `EUSTX50.fs`, `SPI200.fs ×3`, `HSI.fs`. Ces symboles rejettent l'ordre → **mode de
  remplissage (FOK/IOC) à adapter par symbole**. On perd ces entrées pour rien.
- **`retcode 10018 Market closed` ×4** : entrées tentées sur marché fermé (nuit/week-end) →
  bruit inoffensif, mais on pourrait gater par horaires d'ouverture.

---

## 5. Décisions qui t'appartiennent

1. **Faire tirer BTC/ETH ?** Deux leviers possibles (je n'ai rien touché) :
   - (a) **Relever le budget-risque crypto** pour absorber le lot min 0.1 BTC — mais ça
     casse la prudence « lot ∝ confiance » tant que la confiance crypto est < 0,5.
   - (b) **Laisser tel quel** : BTC ne tire que quand cerveau + piliers + budget s'alignent
     (le plus prudent, cohérent avec la phase de collecte).
   - Mon avis : **(b)** pour l'instant — la confiance crypto mesurée est encore négative,
     forcer BTC = agrandir une perte connue. On rouvre BTC quand la donnée le justifie.
2. **Corriger le filling-mode `.fs` (10030) ?** Oui, c'est un bug franc (entrées perdues) —
   petit fix par symbole, je peux le faire au prochain go.

---

## 6. État des lieux

- **Crypto : ACTIVE** (scannée + armée + a tradé les alt-coins). BTC/ETH bloqués par garde-fous, pas éteints.
- **Univers MT5 : 149 scannés en continu** + scan quotidien fait (00:33) + **rescan frais relancé**.
- **Compte démo en repli** (equity 300, flottant −27) — attendu, phase de collecte, sizing prudent.
- **Rien n'a cassé cette nuit** ; le journal non censuré capture tout (signaux, refus, entrées).

*Bot en marche · branche `reorg/phase1` · RiskGate en véto additif · TP=2.25 (optimum mesuré).*
