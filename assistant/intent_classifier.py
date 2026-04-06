"""assistant/intent_classifier.py — Classification d'intention avec sklearn.

Utilise TF-IDF sur caractères (bigrammes/trigrammes) + LinearSVC pour
classifier les requêtes vocales françaises en catégories sémantiques.

Catégories :
  signal   — Requêtes sur les signaux actifs (BTC, ETH, SOL, PAXG)
  position — Requêtes sur les positions, PnL, capital
  risk     — Requêtes sur le risque macro, drawdown, circuit breaker
  report   — Demandes de rapport ou résumé
  optim    — Requêtes sur l'optimisation, winrate, performance
  system   — Requêtes sur l'état des services
  general  — Tout le reste (conversation, salutations, etc.)

Dépendances :
  pip install scikit-learn
"""
from __future__ import annotations
import logging
import math
from typing import Tuple, Optional

logger = logging.getLogger(__name__)

# ── Données d'entraînement ─────────────────────────────────────────────────────

_TRAINING_DATA = [
    # ── signal ────────────────────────────────────────────────────────────────
    ("quel est le signal btc",                   "signal"),
    ("signal bitcoin",                           "signal"),
    ("signal eth",                               "signal"),
    ("signal ethereum",                          "signal"),
    ("signal sol",                               "signal"),
    ("signal solana",                            "signal"),
    ("signal paxg",                              "signal"),
    ("signal or",                                "signal"),
    ("y a-t-il un signal",                       "signal"),
    ("signaux actifs",                           "signal"),
    ("trade actif",                              "signal"),
    ("opportunite de trade",                     "signal"),
    ("quelle direction",                         "signal"),
    ("long ou short",                            "signal"),
    ("score du signal",                          "signal"),
    ("analyse btc",                              "signal"),
    ("que penses-tu du bitcoin",                 "signal"),
    ("signal en cours",                          "signal"),
    ("y a t il un setup",                        "signal"),
    ("quel actif regarder",                      "signal"),
    ("setup valide",                             "signal"),
    ("order block",                              "signal"),
    ("fair value gap",                           "signal"),
    ("bos choch",                                "signal"),
    ("structure de marche",                      "signal"),

    # ── position ──────────────────────────────────────────────────────────────
    ("mes positions",                            "position"),
    ("positions ouvertes",                       "position"),
    ("combien j ai gagne",                       "position"),
    ("mon pnl",                                  "position"),
    ("profit",                                   "position"),
    ("perte",                                    "position"),
    ("equity",                                   "position"),
    ("capital",                                  "position"),
    ("solde",                                    "position"),
    ("mes trades",                               "position"),
    ("trade ouvert",                             "position"),
    ("combien j ai aujourd hui",                 "position"),
    ("resultat du jour",                         "position"),
    ("combien ai-je gagne aujourd hui",          "position"),
    ("quel est mon profit",                      "position"),
    ("combien j ai perdu",                       "position"),
    ("analyse les positions ouvertes",           "position"),

    # ── risk ──────────────────────────────────────────────────────────────────
    ("risque macro",                             "risk"),
    ("quel est le risque",                       "risk"),
    ("drawdown",                                 "risk"),
    ("circuit breaker",                          "risk"),
    ("danger",                                   "risk"),
    ("exposition",                               "risk"),
    ("macro economie",                           "risk"),
    ("risque global",                            "risk"),
    ("contexte macro",                           "risk"),
    ("fed taux",                                 "risk"),
    ("recession",                                "risk"),
    ("volatilite",                               "risk"),
    ("vix",                                      "risk"),
    ("peur du marche",                           "risk"),
    ("sentiment de marche",                      "risk"),
    ("bear market",                              "risk"),
    ("bull market",                              "risk"),

    # ── report ────────────────────────────────────────────────────────────────
    ("rapport du jour",                          "report"),
    ("fais le rapport",                          "report"),
    ("resume",                                   "report"),
    ("bilan",                                    "report"),
    ("rapport complet",                          "report"),
    ("fais moi un resume",                       "report"),
    ("rapport de trading",                       "report"),
    ("donne moi un bilan",                       "report"),
    ("synthese",                                 "report"),
    ("recap",                                    "report"),
    ("resume de la journee",                     "report"),
    ("rapport hebdomadaire",                     "report"),

    # ── optim ─────────────────────────────────────────────────────────────────
    ("optimisation",                             "optim"),
    ("meilleure config",                         "optim"),
    ("parametres optimaux",                      "optim"),
    ("winrate",                                  "optim"),
    ("sharpe",                                   "optim"),
    ("performance du bot",                       "optim"),
    ("backtest",                                 "optim"),
    ("quel est le winrate",                      "optim"),
    ("taux de reussite",                         "optim"),
    ("rendement",                                "optim"),
    ("retour sur investissement",                "optim"),
    ("sharpe ratio",                             "optim"),
    ("meilleur stop loss",                       "optim"),

    # ── system ────────────────────────────────────────────────────────────────
    ("etat du systeme",                          "system"),
    ("titan actif",                              "system"),
    ("ollama fonctionne",                        "system"),
    ("statut",                                   "system"),
    ("services actifs",                          "system"),
    ("est-ce que tu fonctionnes",                "system"),
    ("es-tu en ligne",                           "system"),
    ("services en marche",                       "system"),
    ("gitnexus",                                 "system"),
    ("bot actif",                                "system"),
    ("etat du bot",                              "system"),
    ("systeme operationnel",                     "system"),
    ("tout fonctionne",                          "system"),

    # ── general ───────────────────────────────────────────────────────────────
    ("bonjour",                                  "general"),
    ("merci",                                    "general"),
    ("comment ca va",                            "general"),
    ("qui es-tu",                                "general"),
    ("explique moi",                             "general"),
    ("aide moi",                                 "general"),
    ("que peux-tu faire",                        "general"),
    ("bonne nuit",                               "general"),
    ("a bientot",                                "general"),
    ("super",                                    "general"),
    ("parfait",                                  "general"),
    ("ok merci",                                 "general"),
]

# ── Classificateur ─────────────────────────────────────────────────────────────

_pipeline = None
_build_attempted = False


def _build() -> None:
    """Construit et entraîne le pipeline sklearn."""
    global _pipeline, _build_attempted
    _build_attempted = True

    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.svm import LinearSVC
        from sklearn.pipeline import Pipeline

        texts  = [t for t, _ in _TRAINING_DATA]
        labels = [l for _, l in _TRAINING_DATA]

        pipeline = Pipeline([
            ("tfidf", TfidfVectorizer(
                analyzer="char_wb",
                ngram_range=(2, 4),
                min_df=1,
                sublinear_tf=True,
            )),
            ("clf", LinearSVC(max_iter=3000, C=1.5, class_weight="balanced")),
        ])
        pipeline.fit(texts, labels)
        _pipeline = pipeline
        logger.info("[INTENT] Classificateur prêt (%d exemples, %d classes)",
                    len(texts), len(set(labels)))

    except ImportError:
        logger.info("[INTENT] scikit-learn non installé — classification désactivée")
        _pipeline = None
    except Exception as e:
        logger.warning("[INTENT] Erreur construction classificateur: %s", e)
        _pipeline = None


def classify(text: str) -> Tuple[str, float]:
    """Classifie le texte en (intent, confidence).

    Args:
        text: Texte de l'utilisateur (brut ou normalisé).

    Returns:
        Tuple (intent_name, confidence_0_1).
        Retourne ("general", 0.0) si sklearn n'est pas disponible.
    """
    global _pipeline, _build_attempted

    if not _build_attempted:
        _build()

    if _pipeline is None:
        return "general", 0.0

    try:
        clean = _normalize(text)
        intent = _pipeline.predict([clean])[0]

        # decision_function → score de marge → sigmoid pour confidence
        scores = _pipeline.decision_function([clean])[0]
        if hasattr(scores, "__len__") and len(scores) > 1:
            raw_score = float(max(scores))
        else:
            raw_score = float(scores) if not hasattr(scores, "__len__") else float(scores[0])

        confidence = 1.0 / (1.0 + math.exp(-raw_score))
        return intent, round(confidence, 3)

    except Exception as e:
        logger.debug("[INTENT] Erreur classify: %s", e)
        return "general", 0.0


def _normalize(text: str) -> str:
    """Normalise le texte pour la classification."""
    import unicodedata
    text = text.lower().strip()
    # Supprimer accents pour meilleure généralisation
    text = "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )
    return text
