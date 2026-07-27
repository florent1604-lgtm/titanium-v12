# Noyau mémoire de Cloe (LLM local) — documentation

Mémoire **persistante, hiérarchisée** de Cloe. Le modèle (Ollama) est interchangeable ;
l'identité et les apprentissages vivent ici (`memory.json`), hors du modèle. Code :
`core/cloe/memory.py`. Accès : `from core.cloe import get_cloe`.

## Hiérarchie (du plus stable au plus volatil)
| Catégorie | Rôle | Forme |
|---|---|---|
| `identity` | Qui est Cloe : rôle, contraintes non négociables | dict clé→entrée |
| `architecture` | La pyramide + pointeurs vers les organes (où regarder) | dict |
| `findings` | Ce que Cloe a **appris** (faits mesurés, réutilisables) | dict |
| `directives` | Décisions de Florent (le master) | dict |
| `analyses` | Journal horodaté des analyses/propositions (ring borné 40) | liste |

## Pourquoi (rapidité)
`brief()` condense la hiérarchie en un contexte COMPACT que le LLM lit en préfixe : il n'a plus
à re-dériver le contexte à chaque appel et le prompt reste court → décisif sur CPU (~4 tok/s).
La mémoire persiste → les apprentissages s'accumulent d'une session à l'autre.

## API
- `remember(category, key, content, meta=None)` — upsert (hors `analyses`).
- `log_analysis(summary, meta=None)` — ajoute une analyse (ring).
- `recall(category=None)` — lecture.
- `brief(max_chars=2600)` — contexte compact pour le LLM.
- `forget(category, key)`.

⚠️ `memory.json` = donnée locale (gitignorée). Ne jamais y mettre de secret.
