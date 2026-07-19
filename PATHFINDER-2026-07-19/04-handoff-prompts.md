# Handoffs

## Claude — revue puis implémentation

Lire la spécification normative. Ne pas câbler `event_mirror`, ajouter de route ou
modifier `lifespan` avant le plan approuvé. Commencer par une revue du prototype
`core/event_plane.py`/`core/event_mirror.py`, avec impacts GitNexus ciblés, puis
tests de crash, concurrence, corruption et replay. NATS/F0 sont des lots séparés.
PAPER/DEMO ONLY ; aucun CommandGateway actif.

## Hermes — perception

Consommer uniquement la projection compacte Cortex et les événements significatifs
read-only. Traiter les données stale/gap/unknown comme non fiables. Ne jamais
interpréter un événement comme une commande et ne jamais demander un sink direct.

## Codex — red-team

Vérifier avant chaque lot : impact GitNexus, idempotence, ack incertain, failover,
lease/époque, intégrité, singleton, absence de dépendance vers l'exécution, tests de
panne et rollback. Exécuter `detect_changes` avant commit et rendre un verdict
explicite GO/REQUEST CHANGES.

## Florent — gate finale

Recevoir les preuves : tests, health, soak 24 h, panne NATS, digest identique,
rollback et diff sans décision/exécution/risque. Autoriser uniquement la production
d'observabilité. Toute capacité PAPER/DEMO future exige un nouveau go distinct.
