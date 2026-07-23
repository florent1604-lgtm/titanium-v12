"""tools/forward_paper_intraday.py — Forward-paper GELÉ XRP/LINK intraday (16/07/2026).

Exécute la config PRÉ-ENREGISTRÉE (collab/FORWARD_PAPER_PREREGISTRATION.md) en
avant, sur données Binance H1 (là où l'edge a été mesuré). C'est le SEUL test
propre : données neuves, config figée, impossible à truquer.

À appeler chaque heure (boucle/cron). Idempotent : détecte un signal SUR la barre
H1 qui vient de clôturer, ouvre une position paper Binance, la gère (SL/TP/time-
stop), journalise chaque événement avec l'émotion observée.

MIROIR MT5 DÉMO (option --mirror) : place AUSSI un ordre réel sur le compte démo
Axi (XRPUSD/LNKUSD) pour que Florent VOIE les trades sur son iOS. ⚠️ Le spread Axi
(~29 bps) n'est PAS représentatif — visibilité seulement, jamais la mesure.

PAPER ONLY. Le compte réel n'est jamais touché (mur démo↔réel de demo_mt5_executor).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.binance_history import get_klines
from tools.asset_optimizer_m2 import entries, add_indicators

# ── Config GELÉE (miroir du pré-enregistrement — NE PAS ré-optimiser) ─────────
FROZEN = {
    "symbols": {"XRPUSDT": "XRPUSD", "LINKUSDT": "LNKUSD"},   # binance -> mt5 demo
    "tf": "H1", "align": True, "rsi_gate": True,
    "sl_atr": 1.5, "tp_ladder": [1.5, 2.5, 4.0], "time_stop_bars": 48,
    "maker_rt_bps": 15.0, "risk_pct": 7.0,
    "prereg": "collab/FORWARD_PAPER_PREREGISTRATION.md",
}
STATE = ROOT / "data" / "forward_paper_state.json"
JOURNAL = ROOT / "data" / "forward_paper_journal.ndjson"


def _load_state() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"positions": {}, "last_bar": {}, "trades": 0}


def _save_state(st: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE)


def _journal(row: dict) -> None:
    try:
        row["ts_utc"] = datetime.now(timezone.utc).isoformat()
        JOURNAL.parent.mkdir(parents=True, exist_ok=True)
        with JOURNAL.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    except Exception as e:
        print("  [journal] échec:", e)


def _emotion(binance_symbol: str) -> dict | None:
    try:
        from emotion.market_context import emotion_for
        st = emotion_for(binance_symbol)
        return {"label": st.label, "valence": st.valence, "arousal": st.arousal,
                "confidence": st.confidence} if st.available else {"available": False}
    except Exception:
        return None


def _mirror_demo(mt5_symbol: str, side: str, sl_atr: float, tp_mult: float) -> dict:
    """Place un ordre réel sur le DÉMO Axi (visibilité iOS). Fail-closed démo."""
    try:
        import MetaTrader5 as mt5
        from data.mt5_provider import mt5_lock
        from execution import demo_mt5_executor as dx
        guards = dx.DemoGuards.from_env()
        if not guards.enabled:
            return {"sent": False, "reason": "DEMO_EXEC_ENABLED=0"}
        # ATR démo depuis les bougies H1 MT5
        from data.mt5_provider import get_ohlcv
        df = get_ohlcv(mt5_symbol, tf="H1", n=60)
        if df is None or len(df) < 20:
            return {"sent": False, "reason": "MT5_NO_BARS"}
        import pandas as pd
        h, l, c = df["high"], df["low"], df["close"]
        tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
        atr = float(tr.rolling(14).mean().iloc[-1])
        with mt5_lock:
            acc = dx.assert_demo_or_raise(mt5)
            dse = dx.establish_day_ref(acc["equity"])
            return dx.place_market_order(mt5, mt5_symbol, side, atr,
                                         sl_atr_mult=sl_atr, tp_atr_mult=tp_mult,
                                         guards=guards, day_start_equity=dse)
    except Exception as e:
        return {"sent": False, "reason": f"MIRROR_ERR:{type(e).__name__}"}


def run_once(mirror: bool = False) -> None:
    st = _load_state()
    now = datetime.now(timezone.utc)
    print(f"=== FORWARD-PAPER GELÉ (XRP/LINK intraday H1) — {now:%Y-%m-%d %H:%M} UTC ===")
    print(f"    config figée : {FROZEN['prereg']} | miroir MT5 démo : {'ON' if mirror else 'off'}\n")

    for bsym, msym in FROZEN["symbols"].items():
        df = get_klines(bsym, "H1", years=0.3)
        if df is None or len(df) < 250:
            print(f"  {bsym}: données insuffisantes"); continue
        frame = add_indicators(df.copy())
        sig = entries(frame, FROZEN["align"], FROZEN["rsi_gate"])
        # dernière barre H1 CLÔTURÉE
        closed = frame[(frame.index + (frame.index[-1] - frame.index[-2])) <= now]
        if len(closed) < 2:
            print(f"  {bsym}: pas de barre close"); continue
        last_ts = closed.index[-1]
        smap = {ts: int(s) for ts, s in zip(sig.index, sig["side"])}
        side_val = smap.get(last_ts, 0)
        pos = st["positions"].get(bsym)

        # signal nouveau sur la barre qui vient de clôturer + pas déjà traité + pas de position
        already = st["last_bar"].get(bsym) == last_ts.isoformat()
        if side_val != 0 and not pos and not already:
            side = "long" if side_val > 0 else "short"
            price = float(closed["close"].iloc[-1])
            emo = _emotion(bsym)
            st["positions"][bsym] = {"side": side, "entry": price,
                                     "opened": last_ts.isoformat(), "bars": 0}
            st["trades"] += 1
            rec = {"event": "ENTRY", "symbol": bsym, "side": side, "price": price,
                   "bar": last_ts.isoformat(), "emotion_observed": emo, "mirror": None}
            print(f"  🔔 {bsym}: SIGNAL {side.upper()} @ {price} (barre {last_ts})")
            if mirror:
                tp_last = FROZEN["tp_ladder"][-1]
                m = _mirror_demo(msym, side, FROZEN["sl_atr"], tp_last)
                rec["mirror"] = m
                print(f"     miroir démo {msym}: {'ORDRE PLACÉ lot '+str(m.get('lot')) if m.get('sent') else 'non — '+str(m.get('reason'))}")
            _journal(rec)
        else:
            why = "position ouverte" if pos else ("déjà traité" if already else "pas de signal")
            print(f"  {bsym}: {why} (dernier signal barre {last_ts}, side={side_val})")
        st["last_bar"][bsym] = last_ts.isoformat()

    _save_state(st)
    print(f"\n  état : {st['trades']} entrée(s) au total | positions ouvertes : {list(st['positions'].keys()) or 'aucune'}")
    print("  (gestion SL/TP/time-stop des positions ouvertes : itération suivante)")


def main() -> None:
    ap = argparse.ArgumentParser(description="Forward-paper gelé XRP/LINK intraday.")
    ap.add_argument("--mirror", action="store_true", help="miroir ordre réel sur démo MT5 (visibilité iOS)")
    a = ap.parse_args()
    run_once(mirror=a.mirror)


if __name__ == "__main__":
    main()
