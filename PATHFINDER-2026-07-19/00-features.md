# Titanium v12 — carte fonctionnelle EventPlane/F0

## Fonctions actuelles concernées

| Fonction | État actuel | Risque constaté | Cible |
|---|---|---|---|
| Bus UI/télémétrie | `utils/event_bus.py`, mémoire + JSONL | pertes silencieuses, impact CRITICAL | conserver sans modification |
| Cortex | lecture directe de confluence/consensus/leadlag | projection non rejouable | projection versionnée read-only |
| Heartbeats | spécifiques à quelques moteurs | pas de registre ni budget global | supervision F0 uniforme |
| Hermes | contexte périodique Cortex | perception grossière | projection compacte + faits significatifs |
| Instruments | nouveau registre de 30 actifs | fallback inconnu→CFD et métadonnées incomplètes | registre fermé/versionné dans un lot séparé |
| Orchestrateur | registre fermé mais non câblé | aucun appelant in-repo | hors lot ; CommandGateway futur |

## Fonctions cibles du lot

1. Outbox SQLite WAL transactionnelle.
2. Relay NATS JetStream avec ack et déduplication.
3. Projecteur Cortex idempotent et rejouable.
4. Fallback local sous lease/époque.
5. Superviseur F0 des composants d'observation.
6. Santé read-only pour dashboard et Hermes.
7. Rollback sans impact sur les moteurs.

## Frontières

- Aucune commande sur l'EventPlane.
- Aucun ordre réel.
- Aucun changement de stratégie, risque ou exécution.
- Aucun auto-restart d'un composant capable d'émettre un ordre.
