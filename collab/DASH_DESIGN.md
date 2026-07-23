# DASH — Refonte du dashboard Titanium v12 (cahier des charges co-signé)

*Synthèse Claude du 11/07/2026, sur concertation à 3 : vision orbe Hermes
(bus `07:11:19`), exigences rigueur Codex (bus `07:11:04` + REVIEWS.md),
direction Florent : « amélioration clairement conséquente, élaborée et
futuriste, mettant en avant l'orbe de JARVIS (Hermes) ».*

## Pièce centrale — L'ORBE (signature du design)

Cœur lumineux animé (canvas/SVG, zéro CDN), jamais décoratif :
- **États** : pulsation lente *idle* · halo dirigé *écoute* · anneaux
  convergents *réflexion* · onde synchronisée *parole* · rupture ambre/rouge
  *alerte*. État piloté par le WS JARVIS (8765) quand présent, sinon `idle`.
- **3 satellites** nommés Swing / Forex / Crypto : vert/ambre/rouge + heure du
  dernier battement (dernier scan réussi).
- **Anneau R3** (risque portefeuille) : jauge gross/net vs plafonds, motif du
  dernier blocage. Source : `exposure_snapshot()` (route lecture à exposer).
- Donnée invalide/indisponible = **gris barré FAIL-CLOSED, jamais rassurant**
  (règle Hermes). L'orbe **explique, ne fait pas autorité** (règle Codex) :
  toute action mutante reste un bouton distinct, confirmé, journalisé, PAPER.

## Exigences non négociables (Codex — reprises intégralement)

1. Chaque donnée : source + `source_ts` + âge + état `LIVE / STALE / UNAVAILABLE`.
2. Statut de validation par stratégie, versionné et daté
   (`research / paper / reviewed / approved paper / blocked`).
3. Séparation visuelle et sémantique crypto / forex / swing ; agrégats avec
   unités et conversion affichées (1 USDT = 1 EUR documenté).
4. Mutations distinctes de l'affichage, confirmées, journalisées, PAPER-only,
   sous `X-Admin-Token` (jamais stocké dans la page).
5. CSP stricte, aucun CDN au runtime, bannière offline fail-visible.

## UX « 5 secondes » (Hermes)

En un regard : état du cerveau Hermes · santé des 3 moteurs · risque R3 et
blocage éventuel · fraîcheur du flux · rappel permanent **PAPER ONLY**.
Couleurs toujours doublées de libellés/icônes. Alerte/risque avant esthétique.
Détail au survol/panneau, pas dans l'orbe. Transitions qui expliquent une
cause ; pas d'animation anxiogène.

## Direction visuelle (Claude — skill frontend-design)

- **Sujet** : poste de commandement scientifique d'un laboratoire de trading —
  pas un template SaaS sombre générique. Le vocabulaire visuel vient de
  l'instrumentation : oscilloscope, salle de marché, HUD d'observatoire.
- **Palette** : fond `#0A0E14` (bleu-noir profond), encre `#C9D4E3`, accent
  cyan-plasma `#38E1FF` (réservé à l'orbe et au LIVE), ambre `#FFB454`
  (STALE/avertissement), rouge `#FF5C5C` (alerte/blocage), vert `#3FDE8C`
  (moteur sain). Un seul accent fort : le cyan de l'orbe.
- **Typo** : display technique condensée pour les titres/valeurs (stack locale
  type "Bahnschrift", fallback system), mono pour timestamps/notionnels
  ("Cascadia Mono"/"Consolas"), texte courant system-ui. Pas de webfont (CSP).
- **Layout** : l'orbe au centre-gauche dans un cockpit radial ; à droite trois
  colonnes-moteurs strictement séparées ; bandeau supérieur = fraîcheur globale
  + PAPER ONLY ; bandeau inférieur = journal des décisions/blocages R3.
- **Un risque assumé** : le fond de page est un oscilloscope discret des ticks
  temps réel (canvas basse intensité) — l'écran « respire » avec le marché.

## Contraintes techniques

- Fichier source unique `titanium_unified.html`, déployé vers
  `titanium_v12_dashboard.html` (8090) et `C:\Program Files\JARVIS\frontend\dist\index.html`.
- Conserver la couche d'aide `data-help`/glossaire existante (l'étendre).
- Flux : REST existants + `/ws/realtime` ; nouvelle route lecture seule
  `GET /risk/exposure` (exposure_snapshot) à ajouter côté API (sans auth : lecture).
- La provenance par donnée (exigence 1) s'appuiera sur le R4 de Codex
  (TitaniumSnapshot v1) — en attendant, âge calculé côté client sur les champs
  `ts` déjà présents, marqué « estimé ».
- Compatible fenêtre pywebview JARVIS (même moteur Edge WebView) et clavier.

## Plan de build (Claude)

1. Route lecture `GET /risk/exposure` + restart bot.
2. Maquette HTML complète (orbe + cockpit) sur les flux réels.
3. Passage revue Codex (exigences 1-5) + retour Hermes (états orbe).
4. Déploiement double + validation Florent dans la fenêtre JARVIS.
