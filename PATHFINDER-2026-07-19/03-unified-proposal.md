# Proposition unifiée

## Architecture

- **Plan de faits :** SQLite WAL outbox + NATS JetStream.
- **Plan de projection :** Cortex idempotent, versionné, rejouable.
- **Plan de santé :** superviseur F0.
- **Plan IA :** Hermes read-only sur projection compacte et événements.
- **Plan de commande :** séparé, inactif et hors lot.

## Séquence sûre

1. Auditer les prototypes dormants.
2. Terminer B0 SQLite par TDD.
3. Installer/tester NATS isolément.
4. Ajouter relay synthétique.
5. Ajouter F0 et injection de pannes.
6. Ajouter miroir Cortex read-only off par défaut.
7. Ajouter santé dashboard/Hermes.
8. Soak test 24 h et rollback.
9. Activation observabilité sur go final.

## Critère d'unification

Le système est unifié lorsque NATS, SQLite et Cortex produisent le même digest de
projection après replay, que les composants ont une santé explicite et que cette
infrastructure peut être arrêtée sans changer une décision ou une position.

## Référence normative

`docs/superpowers/specs/2026-07-19-titanium-eventplane-nats-sqlite-f0-design.md`
