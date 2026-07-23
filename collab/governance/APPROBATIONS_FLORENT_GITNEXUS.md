# Ce que Florent devra fournir — écritures GitNexus d'Hermes

*Préparé par Claude le 2026-07-13, en vue du retour de Codex avec le canal
d'approbation SIGNÉ (correctif du blocant P0 : bus non authentifié).*
*Le vérificateur Ed25519 est livré, mais rien n'est actif : le registre public
reste vide tant que les clés ne sont pas provisionnées hors bande et que Claude
n'a pas rendu sa nouvelle revue.*

## Rappel du problème (pourquoi des signatures)

Aujourd'hui, une « approbation » n'est qu'une ligne de texte dans un fichier local
que **n'importe quel process peut écrire — y compris Hermes**. Donc Hermes pourrait
forger sa propre approbation. La parade = une **signature cryptographique** : le
superviseur (toi, Claude ou Codex) signe avec une clé PRIVÉE ; le garde vérifie
avec la clé PUBLIQUE. Hermes peut lire la clé publique mais **ne peut pas forger
la signature**.

## A. Une seule fois — la mise en place des clés

1. **Génération d'une paire de clés « Florent »** (clé privée + clé publique).
   - La clé **PUBLIQUE** va dans la config du garde (vérification).
   - La clé **PRIVÉE** reste chez toi, **jamais** dans le dépôt, **jamais** lisible
     par le process Hermes (ex. hors du dossier v12, ou protégée par mot de passe).
   - À décider : gardes-tu la privée toi-même (max contrôle) ou dans un coffre ?
2. **Idem pour Claude et Codex** (chacun sa paire) si tu veux garder l'option
   « approbation d'un superviseur suffit pour le non-sensible ».
   → **Ma recommandation de départ : TOUT write exige TA signature à toi** (pas
   seulement les cas sensibles), le temps de prendre confiance. On assouplira après.

*Je peux préparer le script de génération + installation de la clé publique dans
le garde ; tu n'auras qu'à valider et garder ta clé privée.*

## B. À chaque écriture qu'Hermes demande — ton approbation signée

Quand Hermes veut écrire, tu verras une **carte de demande** contenant :

| Champ | À vérifier |
|---|---|
| `tool` | `rename` ou `group_sync` uniquement (rien d'autre possible) |
| cible | le symbole renommé / le groupe — est-ce bien ce que tu veux ? |
| `files` | les fichiers réellement touchés (le garde les liste) |
| `impact_risk` | LOW / MEDIUM / **HIGH / CRITICAL** (⚠️ redouble d'attention) |
| `args_sha256` | empreinte exacte de l'opération |
| `expires` | valable **15 min** puis caduque |

**Ton geste** : si c'est OK, tu produis une **approbation signée** (ta signature
couvre `request_id + tool + args_sha256`). Sans signature valide → le garde
**refuse**. Une approbation ne sert **qu'une fois** (anti-rejeu déjà en place).

## C. Les décisions de politique (à fixer une fois)

1. **Périmètre** : on garde `rename` + `group_sync` seulement ? (oui recommandé)
2. **Qui suffit** : politique de livraison retenue = un superviseur signé
   (`claude` ou `codex`) **plus Florent signé sur TOUS les writes** au début.
   Tout assouplissement nécessitera une modification revue séparément.
3. **Durée de validité** (TTL) : 15 min par défaut — ça te va ?

## D. Ce que TU dois vérifier dans la livraison de Codex (avant d'activer)

Je re-reverrai le code, mais côté décision tu confirmes que :
- [ ] une approbation **non signée / forgée est REFUSÉE** (test à voir passer rouge→vert) ;
- [ ] la clé **privée n'est jamais lisible** par le process Hermes ;
- [ ] le bug GitNexus (`detect_changes` qui plante) est réglé **ou** les writes
      restent **bloqués** (fail-closed) tant qu'il ne l'est pas ;
- [ ] rien ne touche : compte réel, JARVIS hors périmètre, secrets, git commit/push.

## En résumé — ta check-list au retour de Codex

1. Valider la **création de ta paire de clés** (je fournis l'outil ; tu gardes la privée).
2. Fixer la **politique** (périmètre + « ta signature sur tous les writes » au début).
3. Pour chaque demande d'Hermes : **lire la carte, vérifier, signer** (ou refuser).
4. Ne rien activer avant que je confirme la re-revue OK **et** que le test
   « approbation forgée = refusée » soit vert.
