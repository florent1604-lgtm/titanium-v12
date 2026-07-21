"""CommandGateway FM — frontière efférente GOUVERNÉE (palier C1 SHADOW).

⚠️ C1 = SHADOW STRICT, PAPER/DEMO ONLY, ZÉRO handler, ZÉRO effet. Aucun ordre réel n'est
jamais autorisé. Ce paquet reçoit des propositions NON FIABLES, journalise avant de répondre,
évalue une politique DÉTERMINISTE et s'arrête après la décision shadow (aucun dispatch). Le
registre de handlers est VIDE ; la table `authorizations` reste VIDE par invariant.

Spec : docs/superpowers/specs/2026-07-19-commandgateway-fm-design.md (Codex, validée Florent
20/07/2026). Ce lot n'implémente QUE le noyau pur (contrats, registre, policy, journal,
orchestrateur process-local) + tests. PAS de transport named-pipe/service Windows, PAS de
publication d'audit EventPlane (registre gelé non étendu), PAS de câblage JARVIS.
"""
