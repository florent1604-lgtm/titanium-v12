"""indicators/trix.py — TRIX indicator + paramètres optimisés par walk-forward."""
from __future__ import annotations
from typing import Optional, Dict, Any
import pandas as pd
import pandas_ta as ta
from utils.logger import get_logger

logger = get_logger(__name__)

# Paramètres STRICT par défaut (remplacés par walk-forward)
DEFAULT_STRICT_PARAMS: Dict[str, Any] = {
    "trix_length": 9,
    "trix_signal": 21,
    "rsi_entry_long":  28.0,
    "rsi_entry_short": 72.0,
}


def compute_trix(df: pd.DataFrame, length: int = 9, signal: int = 21) -> Dict[str, float]:
    """Calcule TRIX + ligne de signal.

    Returns dict avec 'trix', 'signal', 'cross_up', 'cross_down'.
    """
    result = {"trix": 0.0, "signal": 0.0, "cross_up": False, "cross_down": False}
    if df is None or len(df) < length * 3 + signal:
        return result
    try:
        trix_df = ta.trix(df["close"], length=length, signal=signal)
        if trix_df is None or trix_df.empty:
            return result
        cols = list(trix_df.columns)
        trix_col   = next((c for c in cols if "TRIX" in c and "s" not in c.lower()), None)
        signal_col = next((c for c in cols if "TRIXs" in c or "Signal" in c.lower()), None)
        if not trix_col:
            return result
        trix_val   = float(trix_df[trix_col].iloc[-1])
        signal_val = float(trix_df[signal_col].iloc[-1]) if signal_col else 0.0
        prev_trix  = float(trix_df[trix_col].iloc[-2]) if len(trix_df) >= 2 else trix_val
        prev_sig   = float(trix_df[signal_col].iloc[-2]) if signal_col and len(trix_df) >= 2 else signal_val

        result["trix"]       = trix_val if not pd.isna(trix_val) else 0.0
        result["signal"]     = signal_val if not pd.isna(signal_val) else 0.0
        result["cross_up"]   = prev_trix < prev_sig and trix_val > signal_val
        result["cross_down"] = prev_trix > prev_sig and trix_val < signal_val
    except Exception as e:
        logger.debug("[TRIX] compute error: %s", e)
    return result


def trix_signal(df: pd.DataFrame, params: Optional[Dict[str, Any]] = None, side: str = "ACHAT") -> bool:
    """Vérifie si TRIX valide un signal dans la direction donnée."""
    p = params or DEFAULT_STRICT_PARAMS
    res = compute_trix(df, length=int(p.get("trix_length", 9)), signal=int(p.get("trix_signal", 21)))
    if "ACHAT" in side:
        return res["trix"] > 0 or res["cross_up"]
    else:
        return res["trix"] < 0 or res["cross_down"]
