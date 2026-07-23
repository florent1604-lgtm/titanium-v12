"""Segment ÉMOTION (circumplex valence×arousal) — nourrit la décision (via M2)."""
from emotion.emotion_engine import (
    EmotionSignal, EmotionState, compute_emotion, register_signal, REGISTRY,
    PANIC, FEAR, CAPITULATION, HOPE, NEUTRAL, OPTIMISM, COMPLACENCY, EUPHORIA, ANXIETY,
)
__all__ = ["EmotionSignal", "EmotionState", "compute_emotion", "register_signal", "REGISTRY",
           "PANIC", "FEAR", "CAPITULATION", "HOPE", "NEUTRAL", "OPTIMISM",
           "COMPLACENCY", "EUPHORIA", "ANXIETY"]
