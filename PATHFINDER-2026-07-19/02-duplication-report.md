# Rapport de duplications et préoccupations transverses

## 1. Événements et états

- `utils/event_bus.py` gère UI/JSONL et ne doit pas être étendu.
- `core/cortex.py` agrège directement trois moteurs.
- plusieurs moteurs maintiennent leur propre heartbeat.
- `domain/titanium_snapshot.py` possède déjà provenance/fraîcheur pour les
  stratégies, mais avec un contrat différent du Cortex.

**Décision :** ne pas fusionner ces modules par refactor massif. Ajouter un plan
parallèle et migrer les consommateurs après preuves de replay.

## 2. Instruments

Le nouveau `core/instruments.py` centralise 30 instruments, mais des listes restent
dans `utils/config.py`, `core/portfolio_risk.py`, les assistants et les webhooks.
Le fallback `venue_of(inconnu) -> cfd` n'est pas fail-closed.

**Décision :** traiter dans un lot G séparé avant toute utilisation décisionnelle.

## 3. Supervision

Les heartbeats confluence/consensus existent, mais aucun registre central,
failure budget, singleton lease ou politique de restart uniforme n'a été trouvé.

**Décision :** F0 devient l'unique projection de santé, sans remplacer les gardes
locales ni le circuit breaker.

## 4. Risque de couplage

`api.api_server.lifespan` démarre de nombreuses boucles. Ajouter directement
relay, projecteur et miroir dans cette fonction augmenterait le couplage et le
risque de doublon.

**Décision :** concevoir un bootstrap observationnel unique et minimal, après
impact GitNexus ; aucun câblage avant tests de singleton et rollback.
