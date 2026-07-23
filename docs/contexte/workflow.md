# Workflow

## Avant de toucher quoi que ce soit
1. Lire `AGENTS.md`, `CLAUDE.md`, `collab/README.md` et la documentation concernée.
2. Vérifier `git status` : le dépôt contient déjà de nombreuses modifications non committées.
3. Créer/compléter la tâche dans `collab/TASKS.md` : owner, périmètre et critère de fait.
4. Pour un symbole runtime, appliquer la règle GitNexus d’impact ; pour documentation/tests non mutatifs, le contrôle est facultatif (`AGENTS.md`).
5. Ne jamais lire/committer `.env`, secrets ou états runtime ignorés.

## Pour faire un changement
1. **Hermes** cadre, assigne et consigne le contexte ; **Claude** implémente ; **Codex** relit indépendamment ; **Florent** arbitre.
2. Identifier le module propriétaire et les tests voisins ; annoncer les fichiers concernés dans `collab/LOG.md`.
3. Modifier la source de vérité : configuration dans `utils/config.py`, guard dans `execution/guards.py`, route dans `api/`.
4. Ajouter/adapter le test ciblé sous `tests/`, puis joindre diff et preuves à la tâche.
5. Codex écrit son verdict dans `collab/REVIEWS.md`. Sans verdict croisé, le code trading reste `REVIEW`.
6. Florent valide `DONE` ou renvoie en travail ; tracer la décision dans `collab/LOG.md`.
7. Pour API/engine, signaler qu’un redémarrage de `main.py` est nécessaire ; HTML/JS/CSS est relu par requête selon `CLAUDE.md`.

## Avant de considérer quelque chose comme terminé
- [ ] Pas de mode live ni contournement PAPER ONLY.
- [ ] Tests pertinents verts.
- [ ] Configuration centralisée et données sensibles exclues.
- [ ] Aucun changement runtime/secret ajouté au commit.
- [ ] Effet sur JARVIS/endpoints 8090 évalué.

## Deploy
[EN ATTENTE : procédure de déploiement versionnée.] Le dépôt ne contient pas de workflow CI/CD versionné ; l’exécution locale documentée est `venv\Scripts\python.exe main.py` sur le port 8090.