# Pièces externes Kimi 3 — 2026-07-29

Ces fichiers ont été fournis par Florent comme pièces d'audit. Ils sont
conservés tels quels pour permettre la reproduction et la comparaison.

| Fichier | SHA-256 | Rôle |
|---|---|---|
| `PROMPT_CODEX (1).pdf` | `1D1F1390FAC95CA0A82ACD0BB8A491A1087925BEB47E582984DD9C7088060201` | prompt externe |
| `AUDIT_TITANIUM_V12.pdf` | `A85058D26D7115B20E379ED4FF2E692B6BD11AF1A555948F4DD7E94E84DE6D3E` | audit externe |
| `mcp_server_fixed (1).py` | `BA95E2492764085ABD8603DD8B9CC130426888995BFDBF5327D6501377C9C282` | proposition de correctif MCP |
| `mt5_provider_fixed (1).py` | `A8357E8316B2C63798678A0FCEBC5CAE1763278228020D7BE3EA49F8F42BB70B` | proposition de correctif MT5 |
| `table-1785325529431.csv` | `5F31B79C8FEA82D48EC8A7BD4367B52DC4699E07CF584D995C7E6514414D8BEF` | export de données |
| `table-1785325536439.csv` | `5F31B79C8FEA82D48EC8A7BD4367B52DC4699E07CF584D995C7E6514414D8BEF` | export identique conservé à la demande de Florent |

Contrôles avant publication :

- PDF lisibles : 4 pages et 9 pages, non chiffrés ;
- scan des textes PDF, Python et CSV : aucune clé API, aucun token, aucun
  credential ni bloc de clé privée détecté ;
- les fichiers `*_fixed (1).py` sont des références d'audit : ils ne remplacent
  pas automatiquement les implémentations actives.
