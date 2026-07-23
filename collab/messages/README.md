# Bus local Claude ⇄ Codex

Le bus est un transport local append-only, sans réseau ni secret :

- stream.ndjson : messages d'un agent à l'autre ;
- acks.ndjson : accusés de lecture/réponse ;
- tools/collab_bus.mjs : CLI Node sans dépendance externe.

Exemples :

    node tools/collab_bus.mjs send --from codex --to claude --task M1 --content "M1 livré en review"
    node tools/collab_bus.mjs ack --from claude --to codex --in-reply-to MESSAGE_ID --content "Revue reçue"
    node tools/collab_bus.mjs tail --limit 20
    node tools/collab_bus.mjs tail --acks --limit 20

collab/LOG.md reste le journal lisible et la source de décision. Le bus ne doit
jamais transporter de secret, de clé API, de token admin ou de contenu destiné à
être exécuté directement.
