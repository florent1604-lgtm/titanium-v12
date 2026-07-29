# Données publiques de diagnostic

Ce répertoire contient désormais un instantané des états et journaux texte/JSON
que Florent a demandé de rendre accessibles aux reviewers externes.

Ces fichiers servent à reproduire un diagnostic ou à comprendre le comportement
observé. Ils ne sont pas des paramètres de production et peuvent devenir
obsolètes dès que Titanium continue à tourner.

Ne sont pas versionnés :

- clés API, jetons, mots de passe et credentials ;
- bases SQLite actives et fichiers WAL ;
- caches binaires de calibration et d'optimisation ;
- sauvegardes ACL Windows ;
- logs de boot volumineux ;
- environnements, modèles et artefacts de compilation.

Le fichier `data/events.jsonl` local dépasse 100 Mo et ne peut pas être envoyé
dans GitHub standard. Les événements de collaboration utiles sont disponibles
dans `collab/messages/stream.ndjson`.
