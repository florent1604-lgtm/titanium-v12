# Audit — github.com/microsoft/JARVIS (HuggingGPT) · 11/07/2026

*Analyse Claude (v1). Contre-audit Codex attendu (session 13h03). Avis Hermes
sollicité. Décision d'intégration : Florent, après revue croisée.*

## Ce qu'est ce repo

Projet de **recherche** Microsoft (2023) alias **HuggingGPT** : un LLM
(ChatGPT) sert de **chef d'orchestre** — il décompose une demande en tâches,
choisit des modèles experts sur HuggingFace Hub, les exécute, puis synthétise
la réponse. Trois briques : `hugginggpt` (le système), `taskbench` (benchmark
d'automatisation de tâches), `easytool` (instructions d'outils condensées pour
agents LLM). MIT. Python + Vue. **Dormant depuis ~2023-2024** (« planning/rebuilding »).

## Verdict sécurité : NE PAS INTÉGRER LE CODE — 7 constats

1. **Code de recherche non maintenu** : dépendances figées 2023 (gradio,
   transformers, pytorch anciens) portant des CVE connues depuis ; aucune
   correction à attendre. Dette supply-chain immédiate.
2. **Secrets en clair** : clé OpenAI + token HuggingFace dans
   `config.default.yaml`. Contraire à notre posture P0 (fail-closed, secrets
   hors code/config versionnée).
3. **LLM-contrôleur = surface d'injection de prompt** : le plan d'exécution
   sort du LLM et est exécuté sans validation — une entrée malveillante peut
   détourner la sélection/paramètres d'outils. C'est EXACTEMENT la classe de
   risque que Codex a marquée CRITICAL sur `hermes -z` (R6b). OWASP LLM01,
   taux de succès 50-84 % selon configuration.
4. **Téléchargement automatique de modèles HF** (jusqu'à 284 Go ;
   `trust_remote_code` implicite, pickles) : exécution de code tiers à
   l'installation = supply chain non maîtrisée.
5. **Serveur web local sans authentification** (REST 8004 + front Vue) — le
   défaut exact qu'on vient de corriger sur Titanium (P0).
6. **Matériel incompatible** : ≥ 24 Go VRAM GPU requis ; machine Florent =
   CPU-only, 15 Go RAM. Seul le mode « lite » tournerait = tout part dans le
   cloud (HF Inference API) — perte de la maîtrise locale.
7. **Obsolescence fonctionnelle** : le contrôleur par défaut cible
   `text-davinci-003`, modèle RETIRÉ par OpenAI — le repo ne tourne plus tel
   quel sans modification.

## Ce qu'on PREND (les idées, réimplémentées chez nous, jamais le code)

| Brique | Idée | Application Titanium/JARVIS |
|---|---|---|
| HuggingGPT | **Orchestration en 4 étapes** : planification → sélection d'outil → exécution → synthèse | Formaliser le cerveau Hermes : intention vocale → plan JSON typé → outil choisi dans un REGISTRE FERMÉ (endpoints Titanium whitelistés) → exécution → réponse parlée. Auditables : le plan est loggé AVANT exécution |
| HuggingGPT | **Registre d'outils déclaratif** (métadonnées par outil) | Déclarer les actions `titanium_connector` (P&L, positions, swing, opportunités…) dans un registre JSON consommé par Hermes — ajout d'une commande vocale = 1 entrée de registre, zéro code cerveau |
| EasyTool | **Instructions d'outils condensées** (moins de tokens, meilleure sélection) | Compresser le pack de connaissance JARVIS + descriptions d'outils pour Hermes → réponses plus rapides sur notre CPU et moins d'erreurs de routage |
| TaskBench | **Benchmark de l'automatisation de tâches** | Corpus de commandes JARVIS mesurable → tests de PARITÉ R6 (Hermes vs ancien cerveau) et non-régression du routage vocal (le bug « relance Titanium »→« EA App » y serait un cas rouge) |

**Synergie R6b** : l'étape « plan validé contre un registre fermé AVANT
exécution » est précisément la parade à l'injection signalée par Codex — on
sécurise Hermes en adoptant ce patron, sans lui retirer ses outils (décision
Florent : tester d'abord, sécuriser ensuite).

## Conditions non négociables si intégration de patrons

- Réimplémentation native (aucun `pip install` depuis ce repo, aucun code copié).
- Aucun téléchargement de modèle automatique ; aucun `trust_remote_code`.
- Secrets : `.env` local uniquement, jamais dans un yaml versionné.
- Le plan du LLM = **entrée non fiable** : validation stricte contre le
  registre (outil inconnu → refus, paramètre hors schéma → refus, fail-closed).
- Paper-only inchangé : aucun outil du registre ne peut émettre d'ordre réel.
