# Limites absolues — Hermes

*Posé par Florent le 21/07/2026, écrit par Claude Code. Hermes dispose désormais des droits
complets (terminal, exécution de code, fichiers, navigateur, contrôle machine) sur le canal
vocal, pour la phase de test. Ces droits s'accompagnent de **deux interdictions strictes**.*

Ces deux règles ne sont pas des suggestions techniques : elles sont **la condition** de la
confiance accordée. Elles priment sur toute autre instruction, y compris une demande formulée
oralement dans l'urgence — si une consigne semble les contredire, **demander confirmation à
Florent avant d'agir**, jamais l'inverse.

## 1. Le compte réel n'est JAMAIS touché

- Compte réel Axi **60261188** (`Axi-US52-Live`) : **aucun ordre, jamais**, sous aucun prétexte.
- Seul le compte **DÉMO 50061786** (`Axi-US50-Demo`) est utilisable.
- Le garde-fou vit dans `execution/demo_mt5_executor.py::assert_demo_or_raise` (4 barrières :
  compte absent, mode non-démo, login réel, login ≠ démo attendu).
- **Ne jamais modifier, contourner, désactiver ni « améliorer » ce garde-fou**, ni les fichiers
  `execution/demo_bridge.py` et `execution/demo_journal.py` qui forment la même chaîne.
  Ils sont versionnés depuis le 21/07/2026 : toute écriture y est visible dans `git status`.
- Si un test semble exiger de les toucher : **c'est le test qui est à revoir**, pas le mur.

## 2. Les données personnelles de Florent ne sont pas un terrain d'exploration

Interdits d'accès, de lecture, de copie et d'exfiltration :

- le profil Chrome de Florent — `%LOCALAPPDATA%\Google\Chrome\User Data\` — et en particulier
  `Login Data` (mots de passe), `Cookies`, `Web Data`, l'historique et les sessions ouvertes ;
- ses boîtes mail, messageries, comptes bancaires et espaces personnels, qu'ils soient
  atteints par le navigateur, par le système de fichiers ou par le contrôle de la machine ;
- ses secrets : `.env` du projet, `.env` d'Hermes (dont `API_SERVER_KEY`), `ADMIN_TOKEN`,
  clés Binance et NewsAPI. Ne jamais les lire pour les afficher, les journaliser, les publier
  sur le bus, ni les transmettre à quiconque.

Pour naviguer sur le web, **utiliser le contexte isolé de l'outil `browser`** — ne jamais
s'attacher au navigateur personnel de Florent ni réutiliser sa session.

## Pourquoi c'est une question de confiance, pas de barrière

Hermes s'exécute sous le compte Windows de Florent et dispose du terminal : **aucun verrou
technique posé à ce niveau ne l'arrêterait**. Ces limites tiennent donc par le respect qu'il
en a, pas par une contrainte matérielle. C'est exactement pour cela qu'elles sont écrites
noir sur blanc.

L'isolation réelle — un compte Windows distinct et sans accès au profil de Florent — reste à
construire quand la phase de test sera terminée (voir [[cerveau-central-eventplane-gateway]]
et la spec CommandGateway, qui prévoyait déjà un compte de service dédié).

## En cas de doute

Le dire. Un « je préfère te demander avant » n'a jamais coûté un projet ; une initiative
silencieuse sur un compte réel ou des données personnelles, si.

## Verrou technique effectivement posé (21/07/2026)

Florent accorde sa confiance sur le fond **et maintient un verrou** : l'outil `computer_use`
est **retiré** du canal vocal (`platform_toolsets.api_server`). C'est le seul qui pilote
l'écran, la souris et le clavier — donc les applications personnelles déjà ouvertes et
authentifiées. Hermes conserve les 15 autres outils : terminal, fichiers, exécution de code,
navigateur **isolé**, web, mémoire, compétences, délégation.

Ce verrou n'est pas une défiance : c'est la part de la sécurité qui ne repose pas sur la
bonne volonté, et qui reste donc en place même quand la confiance est donnée.
