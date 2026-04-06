"""assistant/lip_sync.py — Mapping phonèmes FR → visèmes VRM + génération frames.

Deux approches combinées :
  1. Énergie RMS : amplitude audio → valeur jawOpen (mouvement global)
  2. Phonèmes : texte → IPA (via phonemizer) → visèmes VRM (précision)

Visèmes VRM standard (@pixiv/three-vrm) :
  aa  → bouche ouverte (a, â)
  ih  → bouche étirée (i, é)
  ou  → lèvres arrondies (u, ou)
  ee  → bouche semi-ouverte (e, è)
  oh  → bouche ronde (o, ô)
  <silence> → fermeture progressive

Les 52 blendshapes du modèle hinzka incluent aussi :
  jawOpen, mouthFunnel, mouthPucker, mouthSmileLeft, mouthSmileRight
  → accessibles comme custom expressions

Dépendances (optionnelles pour meilleure précision) :
  pip install phonemizer   (+ eSpeak NG : https://github.com/espeak-ng/espeak-ng/releases)
"""
from __future__ import annotations
import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# ── Tables de mapping ─────────────────────────────────────────────────────────

# IPA → visème VRM
_IPA_TO_VISEME: Dict[str, str] = {
    # Voyelles françaises
    "a": "aa", "ɑ": "aa", "ɑ̃": "aa",  # a ouvert
    "e": "ee", "ɛ": "ee", "ɛ̃": "ee",  # e ouvert
    "ə": "ee",                           # e muet
    "i": "ih", "y": "ih",               # i, u français
    "o": "oh", "ɔ": "oh", "ɔ̃": "oh",  # o ouvert
    "u": "ou", "ø": "ou", "œ": "ou",  # ou, eu
    "œ̃": "ou",
    # Consonants bilabiales → PP
    "p": "PP", "b": "PP", "m": "PP",
    # Labiodentales → FF
    "f": "FF", "v": "FF",
    # Dentales → TH (approximation)
    "θ": "TH", "ð": "TH",
    # Alvéolaires → DD
    "t": "DD", "d": "DD", "n": "DD", "l": "DD",
    # Vélaires → kk
    "k": "kk", "ɡ": "kk", "ŋ": "kk",
    # Fricatives → SS ou CH
    "s": "SS", "z": "SS",
    "ʃ": "CH", "ʒ": "CH",
    # Nasales → nn
    "n": "nn", "m": "PP",
    # Roulées → RR
    "r": "RR", "ʁ": "RR",
    # Semi-voyelles
    "j": "ih", "w": "ou", "ɥ": "ou",
    # Silence
    " ": "sil", "\n": "sil",
}

# Règles graphème → visème (approximation sans phonemizer)
_GRAPHEME_TO_VISEME: List[Tuple[str, str]] = [
    # Digraphes français (ordre important : plus long en premier)
    ("eau", "oh"), ("eu", "ou"), ("ou", "ou"), ("oi", "aa"), ("ai", "ee"),
    ("ei", "ee"), ("au", "oh"), ("on", "oh"), ("an", "aa"), ("en", "aa"),
    ("in", "ee"), ("un", "ou"), ("ch", "CH"), ("gn", "nn"), ("ph", "FF"),
    ("qu", "kk"), ("th", "DD"),
    # Voyelles simples
    ("a", "aa"), ("â", "aa"), ("à", "aa"),
    ("e", "ee"), ("é", "ee"), ("è", "ee"), ("ê", "ee"), ("ë", "ee"),
    ("i", "ih"), ("î", "ih"), ("ï", "ih"),
    ("o", "oh"), ("ô", "oh"),
    ("u", "ou"), ("û", "ou"), ("ü", "ou"),
    ("y", "ih"),
    # Consonnes
    ("b", "PP"), ("p", "PP"), ("m", "PP"),
    ("f", "FF"), ("v", "FF"),
    ("l", "DD"), ("d", "DD"), ("t", "DD"), ("n", "DD"),
    ("k", "kk"), ("c", "kk"), ("g", "kk"),
    ("s", "SS"), ("z", "SS"),
    ("j", "CH"), ("g", "CH"),
    ("r", "RR"),
    ("h", "sil"),
]

# Poids par défaut de chaque visème (0-1 amplitude de blendshape)
_VISEME_WEIGHTS: Dict[str, Dict[str, float]] = {
    "aa": {"aa": 0.9, "jawOpen": 0.7},
    "ih": {"ih": 0.8, "jawOpen": 0.3},
    "ou": {"ou": 0.85, "jawOpen": 0.4, "mouthFunnel": 0.3},
    "ee": {"ee": 0.75, "jawOpen": 0.35},
    "oh": {"oh": 0.8, "jawOpen": 0.55, "mouthFunnel": 0.2},
    "PP": {"PP": 0.6, "jawOpen": 0.0},
    "FF": {"FF": 0.5, "jawOpen": 0.1},
    "TH": {"TH": 0.5, "jawOpen": 0.15},
    "DD": {"DD": 0.4, "jawOpen": 0.2},
    "kk": {"kk": 0.5, "jawOpen": 0.2},
    "SS": {"SS": 0.4, "jawOpen": 0.1},
    "CH": {"CH": 0.5, "jawOpen": 0.2},
    "nn": {"nn": 0.3, "jawOpen": 0.05},
    "RR": {"RR": 0.4, "jawOpen": 0.25},
    "sil": {"jawOpen": 0.0},
}


@dataclass
class LipFrame:
    """Une frame d'animation lip-sync (à envoyer au renderer)."""
    time_ms: float                                  # temps depuis début (ms)
    shapes:  Dict[str, float] = field(default_factory=dict)  # blendshape → valeur


# ── Génération de frames ──────────────────────────────────────────────────────

def grapheme_to_viseme_sequence(text: str) -> List[str]:
    """Convertit le texte en séquence de visèmes par règles graphème.

    Fallback rapide sans phonemizer.
    """
    text  = text.lower()
    text  = re.sub(r"[^a-zàâäéèêëîïôùûüç\s]", " ", text)
    visemes: List[str] = []
    i = 0
    while i < len(text):
        matched = False
        for grapheme, vis in _GRAPHEME_TO_VISEME:
            if text[i:].startswith(grapheme):
                visemes.append(vis)
                i += len(grapheme)
                matched = True
                break
        if not matched:
            visemes.append("sil")
            i += 1
    return visemes


def ipa_to_viseme_sequence(ipa_text: str) -> List[str]:
    """Convertit du texte IPA en séquence de visèmes."""
    visemes = []
    for char in ipa_text:
        vis = _IPA_TO_VISEME.get(char)
        if vis:
            visemes.append(vis)
    return visemes


def try_phonemize(text: str, language: str = "fr-fr") -> Optional[List[str]]:
    """Essaie de convertir via phonemizer (IPA). None si non disponible."""
    try:
        from phonemizer import phonemize
        ipa = phonemize(
            text,
            backend="espeak",
            language=language,
            with_stress=False,
            language_switch="remove-flags",
        )
        return ipa_to_viseme_sequence(ipa)
    except Exception:
        return None


def generate_lip_frames(
    text: str,
    duration_sec: float,
    fps: int = 30,
    use_phonemizer: bool = True,
) -> List[LipFrame]:
    """Génère les frames d'animation lip-sync pour un texte + durée donnée.

    Args:
        text: Texte prononcé.
        duration_sec: Durée totale du clip audio.
        fps: Images par seconde pour l'animation.
        use_phonemizer: Tenter phonemizer avant fallback graphème.

    Returns:
        Liste de LipFrame avec timestamps en ms.
    """
    # Obtenir la séquence de visèmes
    visemes = None
    if use_phonemizer:
        visemes = try_phonemize(text)
    if not visemes:
        visemes = grapheme_to_viseme_sequence(text)

    if not visemes:
        visemes = ["sil"]

    total_frames = max(1, int(duration_sec * fps))
    frame_dur_ms = 1000.0 / fps
    frames: List[LipFrame] = []

    # Distribuer les visèmes uniformément sur la durée
    vis_per_frame = len(visemes) / total_frames

    for fi in range(total_frames):
        t_ms      = fi * frame_dur_ms
        vis_idx   = min(int(fi * vis_per_frame), len(visemes) - 1)
        vis       = visemes[vis_idx]
        weights   = _VISEME_WEIGHTS.get(vis, {"jawOpen": 0.0})

        # Fade-in au début + fade-out à la fin
        fade      = 1.0
        fade_frames = int(fps * 0.08)  # 80ms fade
        if fi < fade_frames:
            fade = fi / fade_frames
        elif fi > total_frames - fade_frames:
            fade = (total_frames - fi) / fade_frames

        shaped = {k: round(v * fade, 3) for k, v in weights.items()}
        frames.append(LipFrame(time_ms=round(t_ms, 1), shapes=shaped))

    # Frame finale : fermeture
    frames.append(LipFrame(
        time_ms=round(duration_sec * 1000 + 100, 1),
        shapes={"jawOpen": 0.0, "aa": 0.0, "ih": 0.0, "ou": 0.0, "ee": 0.0, "oh": 0.0},
    ))

    return frames


def generate_rms_frames(
    audio: np.ndarray,
    sample_rate: int,
    fps: int = 30,
    smooth: float = 0.3,
) -> List[LipFrame]:
    """Génère les frames lip-sync à partir de l'énergie RMS de l'audio.

    Plus simple mais donne un bon résultat naturel.
    Peut être combiné avec generate_lip_frames() pour du RMS + phonèmes.
    """
    frames: List[LipFrame] = []
    samples_per_frame = max(1, sample_rate // fps)
    n_frames = len(audio) // samples_per_frame
    frame_dur_ms = 1000.0 / fps

    prev_val = 0.0
    for fi in range(n_frames):
        start = fi * samples_per_frame
        end   = start + samples_per_frame
        chunk = audio[start:end]

        # RMS normalisé (0-1)
        rms = float(np.sqrt(np.mean(chunk ** 2)))
        rms = min(1.0, rms * 8.0)   # amplification

        # Lissage exponentiel
        val = smooth * rms + (1 - smooth) * prev_val
        prev_val = val

        jaw_open = round(val * 0.8, 3)
        frames.append(LipFrame(
            time_ms=round(fi * frame_dur_ms, 1),
            shapes={"jawOpen": jaw_open, "aa": round(val * 0.5, 3)},
        ))

    # Fermeture finale
    frames.append(LipFrame(
        time_ms=round(n_frames * frame_dur_ms + 100, 1),
        shapes={"jawOpen": 0.0, "aa": 0.0},
    ))
    return frames


def blend_frames(
    phoneme_frames: List[LipFrame],
    rms_frames: List[LipFrame],
    phoneme_weight: float = 0.6,
) -> List[LipFrame]:
    """Mélange les frames phonèmes et RMS pour un résultat plus naturel."""
    if not rms_frames:
        return phoneme_frames
    if not phoneme_frames:
        return rms_frames

    # Utiliser les timestamps des frames phonèmes
    result = []
    rms_dict = {f.time_ms: f for f in rms_frames}
    rms_times = sorted(rms_dict.keys())

    for pf in phoneme_frames:
        # Trouver le frame RMS le plus proche
        closest_t = min(rms_times, key=lambda t: abs(t - pf.time_ms), default=None)
        rf = rms_dict.get(closest_t)

        blended_shapes = dict(pf.shapes)
        if rf:
            for key, rval in rf.shapes.items():
                if key in blended_shapes:
                    blended_shapes[key] = round(
                        phoneme_weight * blended_shapes[key] + (1 - phoneme_weight) * rval, 3
                    )
                else:
                    blended_shapes[key] = round((1 - phoneme_weight) * rval, 3)

        result.append(LipFrame(time_ms=pf.time_ms, shapes=blended_shapes))

    return result
