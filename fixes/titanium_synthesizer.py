#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════╗
║         TITANIUM V9 — SYNTHESIS ENGINE  (7-reports edition)     ║
║         Agrège les 7 rapports d'agents Claude Code              ║
║         → Plan d'action priorisé + bugs P0 + param recommandés  ║
╚══════════════════════════════════════════════════════════════════╝

UTILISATION :
─────────────
  # Mode standard (tous les fichiers dans le même dossier que le script) :
  python titanium_synthesizer.py

  # Mode chemin personnalisé :
  python titanium_synthesizer.py --dir C:\\Users\\toi\\claude-code\\rapports

  # Spécifier chaque fichier manuellement :
  python titanium_synthesizer.py \\
    --codemap   code_map.md \\
    --flow      signal_flow.md \\
    --params    param_registry.json \\
    --smc       smc_audit.md \\
    --perf      performance_audit.md \\
    --signal    signal_config_audit.md \\
    --reversal  reversal_patterns_report.md

  # Choisir le fichier de sortie :
  python titanium_synthesizer.py --output synthesis_v9.md

PRÉREQUIS :
───────────
  pip install anthropic
  Variable d'environnement : ANTHROPIC_API_KEY=sk-ant-...
  (ou fichier .env dans le même dossier)

RAPPORTS ATTENDUS (scores agents) :
────────────────────────────────────
  code_map.md                 ✅  ~65 fonctions, 29 routes, 7 loops
  signal_flow.md              ✅  7 stages, mermaid flowchart
  param_registry.json         ✅  ~130 paramètres, 9 catégories
  smc_audit.md                ✅  6.5/10 — 5 PASS, 4 WARN, 1 FAIL
  performance_audit.md        ✅  5.5/10 — 3 bugs P0 dont Sharpe formula
  signal_config_audit.md      ✅  5/10  — SCORE_MIN_REQUIRED jamais appliqué
  reversal_patterns_report.md ✅  5/10  — 12 patterns existants, 7 manquants
"""

import os
import sys
import argparse
from pathlib import Path
from datetime import datetime

# ── Chargement optionnel du .env ──────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── Vérification Anthropic SDK ────────────────────────────────
try:
    import anthropic
except ImportError:
    print("❌  SDK Anthropic manquant. Lance : pip install anthropic")
    sys.exit(1)


# ═════════════════════════════════════════════════════════════
#  CONFIG
# ═════════════════════════════════════════════════════════════

MODEL      = "claude-opus-4-6"
MAX_TOKENS = 8192

DEFAULT_FILES = {
    "codemap":  "code_map.md",
    "flow":     "signal_flow.md",
    "params":   "param_registry.json",
    "smc":      "smc_audit.md",
    "perf":     "performance_audit.md",
    "signal":   "signal_config_audit.md",
    "reversal": "reversal_patterns_report.md",
}

AGENT_SCORES = {
    "smc_audit.md":               "6.5/10 — 5 PASS, 4 WARN, 1 FAIL",
    "performance_audit.md":       "5.5/10 — 3 bugs P0 dont Sharpe formula incorrecte",
    "signal_config_audit.md":     "5/10  — SCORE_MIN_REQUIRED jamais appliqué",
    "reversal_patterns_report.md":"5/10  — 12 patterns existants, 7 patterns manquants",
}

LABELS = {
    "codemap":  ("Code Map (65 fonctions)",        "code_map.md"),
    "flow":     ("Signal Flow (7 stages)",         "signal_flow.md"),
    "params":   ("Param Registry (130 params)",    "param_registry.json"),
    "smc":      ("SMC Audit [6.5/10]",             "smc_audit.md"),
    "perf":     ("Performance Audit [5.5/10]",     "performance_audit.md"),
    "signal":   ("Signal Config Audit [5/10]",     "signal_config_audit.md"),
    "reversal": ("Reversal Patterns [5/10]",       "reversal_patterns_report.md"),
}

SYSTEM_PROMPT = """Tu es l'architecte principal de Titanium Dashboard v9, un système de trading algorithmique SMC (Smart Money Concepts) multi-assets (BTC/USDT, ETH/USDT, SOL/USDT, PAXG/USDT, XAUUSD) développé en Python avec frontend HTML/JS.

Tu reçois 7 rapports produits en parallèle par des agents spécialisés Claude Code :

1. **code_map.md** — Cartographie : ~65 fonctions, 29 routes API, 7 boucles principales
2. **signal_flow.md** — Flux de signal en 7 stages (mermaid flowchart)
3. **param_registry.json** — ~130 paramètres tunables en 9 catégories
4. **smc_audit.md** — Audit SMC : score 6.5/10 (5 PASS, 4 WARN, 1 FAIL)
5. **performance_audit.md** — Audit perf : score 5.5/10 (3 bugs P0 dont Sharpe formula)
6. **signal_config_audit.md** — Audit config : score 5/10 (SCORE_MIN_REQUIRED jamais appliqué)
7. **reversal_patterns_report.md** — Patterns : score 5/10 (12 existants, 7 manquants)

Score global estimé : ~5.5/10 — système fonctionnel mais bugs critiques non résolus.

Produis une synthèse stratégique selon ce format EXACT :

---

## 🔬 DIAGNOSTIC GLOBAL
Synthèse croisée en 6-8 phrases. Thèmes communs, contradictions entre rapports, état réel du système.

## 🚨 BUGS CRITIQUES P0 (corriger avant tout)
Pour chaque bug : **[FICHIER/CLASSE]** `nom_methode()` — Description — Impact trading — Fix recommandé.

## 🎯 PLAN D'ACTION PRIORISÉ

### PRIORITÉ 1 — CRITIQUE (cette semaine)
**[COMPOSANT]** Action | Impact sur score | Fichier Python

### PRIORITÉ 2 — IMPORTANT (sprint J+7)
Même format.

### PRIORITÉ 3 — OPTIMISATION (backlog)
Même format.

## ⚙️ PARAMÈTRES À MODIFIER IMMÉDIATEMENT
Tableau markdown :
| Paramètre | Valeur actuelle | Valeur recommandée | Source | Justification |

## 🔄 PATTERNS SMC MANQUANTS — IMPLÉMENTATION
Pour chacun des 7 patterns manquants : nom, logique pseudo-Python, stage signal_flow concerné.

## 🧪 PLAN DE VALIDATION SÉQUENTIEL
Backtest unitaire → walk-forward → paper trading → live. Critères go/no-go à chaque étape.

## 📈 PROJECTION SCORE
Score actuel → après P1 → cible finale. Justification par composant.

## ⚠️ RISQUES & DÉPENDANCES
Dépendances entre modifications, risques de régression, ordre d'implémentation imposé.

---

Sois précis et technique. Cite classes, méthodes et paramètres exacts extraits des rapports. Priorise ce qui impacte directement le P&L."""


# ═════════════════════════════════════════════════════════════
#  HELPERS
# ═════════════════════════════════════════════════════════════

def load_file(path: Path, label: str) -> tuple:
    if not path.exists():
        print(f"  ⚠️   MANQUANT  {label:<45} ({path.name})")
        return f"[FICHIER NON DISPONIBLE : {path.name}]", False
    content = path.read_text(encoding="utf-8", errors="replace")
    size_kb = path.stat().st_size / 1024
    score   = AGENT_SCORES.get(path.name, "")
    extra   = f"  → {score}" if score else ""
    print(f"  ✅  {label:<45} {size_kb:>6.1f} KB{extra}")
    return content, True


def build_user_message(files: dict) -> str:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    sections = [
        ("📐 RAPPORT 1 — CODE MAP",            files["codemap"]),
        ("🔄 RAPPORT 2 — SIGNAL FLOW",         files["flow"]),
        ("🗂️  RAPPORT 3 — PARAM REGISTRY",      files["params"]),
        ("🏛️  RAPPORT 4 — SMC AUDIT [6.5/10]",  files["smc"]),
        ("📊 RAPPORT 5 — PERFORMANCE [5.5/10]", files["perf"]),
        ("⚡ RAPPORT 6 — SIGNAL CONFIG [5/10]", files["signal"]),
        ("🔁 RAPPORT 7 — REVERSAL PATTERNS [5/10]", files["reversal"]),
    ]
    msg = f"# SYNTHÈSE TITANIUM DASHBOARD V9\nGénérée le : {ts}\n\n"
    for title, content in sections:
        msg += f"---\n\n## {title}\n\n{content}\n\n"
    msg += "---\n\nProduis maintenant la synthèse stratégique complète selon le format demandé."
    return msg


def stream_synthesis(user_message: str) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("\n❌  Variable ANTHROPIC_API_KEY introuvable.")
        print("    → Windows : set ANTHROPIC_API_KEY=sk-ant-...")
        print("    → Linux/Mac : export ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    print(f"\n🤖  Synthèse en cours avec {MODEL} (streaming)...\n")
    print("═" * 65)

    full_text = ""
    with client.messages.stream(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    ) as stream:
        for text in stream.text_stream:
            print(text, end="", flush=True)
            full_text += text

    print("\n" + "═" * 65)
    return full_text


def save_output(content: str, output_path: Path):
    header = (
        f"---\n"
        f"# TITANIUM V9 — SYNTHÈSE STRATÉGIQUE (7 rapports)\n"
        f"# Générée le : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"# Modèle     : {MODEL}\n"
        f"# Score estimé avant synthèse : ~5.5/10\n"
        f"---\n\n"
    )
    output_path.write_text(header + content, encoding="utf-8")
    size_kb = output_path.stat().st_size / 1024
    print(f"\n💾  Sauvegardé → {output_path}  ({size_kb:.1f} KB)")


# ═════════════════════════════════════════════════════════════
#  MAIN
# ═════════════════════════════════════════════════════════════

def parse_args():
    p = argparse.ArgumentParser(
        description="Titanium V9 — Synthesis Engine (7 rapports)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--dir",      default=".",  help="Dossier contenant les 7 fichiers (défaut: .)")
    p.add_argument("--codemap",  default=None, help="Chemin code_map.md")
    p.add_argument("--flow",     default=None, help="Chemin signal_flow.md")
    p.add_argument("--params",   default=None, help="Chemin param_registry.json")
    p.add_argument("--smc",      default=None, help="Chemin smc_audit.md")
    p.add_argument("--perf",     default=None, help="Chemin performance_audit.md")
    p.add_argument("--signal",   default=None, help="Chemin signal_config_audit.md")
    p.add_argument("--reversal", default=None, help="Chemin reversal_patterns_report.md")
    p.add_argument("--output",   default=None, help="Fichier de sortie .md (auto-nommé si absent)")
    p.add_argument("--model",    default=MODEL,help=f"Modèle Claude (défaut: {MODEL})")
    return p.parse_args()


def main():
    args = parse_args()
    base = Path(args.dir)

    global MODEL
    MODEL = args.model

    print("╔══════════════════════════════════════════════════════════════╗")
    print("║    TITANIUM V9 — SYNTHESIS ENGINE  (7-reports edition)      ║")
    print("╚══════════════════════════════════════════════════════════════╝\n")
    print("📂  Chargement des 7 rapports...\n")

    arg_map = {
        "codemap": args.codemap, "flow":   args.flow,   "params": args.params,
        "smc":     args.smc,     "perf":   args.perf,   "signal": args.signal,
        "reversal":args.reversal,
    }
    paths = {k: Path(v) if v else base / DEFAULT_FILES[k] for k, v in arg_map.items()}

    files    = {}
    ok_count = 0
    for key, path in paths.items():
        label, _ = LABELS[key]
        content, ok = load_file(path, label)
        files[key] = content
        if ok:
            ok_count += 1

    print(f"\n  → {ok_count}/7 fichiers chargés")

    if ok_count == 0:
        print("\n❌  Aucun fichier trouvé. Vérifie --dir ou les chemins individuels.")
        sys.exit(1)
    if ok_count < 7:
        print("  ⚠️   Synthèse partielle — fichiers manquants signalés à Claude.\n")

    user_message = build_user_message(files)
    synthesis    = stream_synthesis(user_message)

    out = Path(args.output) if args.output else base / f"synthesis_v9_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
    save_output(synthesis, out)

    print("\n✅  Terminé. Ouvre le .md pour consulter le plan d'action complet.")


if __name__ == "__main__":
    main()
