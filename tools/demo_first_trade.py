"""tools/demo_first_trade.py — Premier ordre RÉEL sur le compte DÉMO (étape D).

One-shot manuel : vérifie le garde-fou démo, choisit le 1er symbole négociable
du panier validé (+ forex, souvent ouvert la nuit), calcule ATR/direction et
place UN ordre à 5 % de risque. Fail-closed : rien n'est envoyé si le compte
n'est pas la démo attendue, si le marché est fermé, ou si un garde bloque.

Usage : venv\\Scripts\\python.exe tools\\demo_first_trade.py
À lancer terminal MT5 ouvert, bot 8090 ARRÊTÉ (évite la contention MT5).
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

import MetaTrader5 as mt5
from execution import demo_mt5_executor as dx
from execution.demo_mt5_executor import DemoGuards

# Garde-fous explicites (5 % risque, kill-switch large pour ce test démo).
GUARDS = DemoGuards(enabled=True, risk_pct=5.0, max_positions=3,
                    daily_loss_limit_pct=25.0, max_spread_points=60,
                    min_free_margin_pct=30.0)

# Panier validé (indices testeur natif) + forex (souvent ouvert la nuit).
CANDIDATS = ["EURUSD", "GBPUSD", "XAUUSD", "USTECH", "NAS100.fs", "HSI.fs"]


def atr_et_direction(rates) -> tuple[float, str]:
    df = pd.DataFrame(rates)
    high, low, close = df["high"], df["low"], df["close"]
    prev = close.shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    atr = float(tr.rolling(14).mean().iloc[-2])
    ema = close.ewm(span=50, adjust=False).mean()
    direction = "long" if close.iloc[-2] > ema.iloc[-2] else "short"
    return atr, direction


def main() -> None:
    if not mt5.initialize():
        print("MT5 init échec:", mt5.last_error()); return
    try:
        # Garde-fou N°1 : compte démo attendu (sinon on s'arrête net).
        try:
            acc = dx.assert_demo_or_raise(mt5)
            print(f"Compte DÉMO OK : login {acc['login']} {acc['server']} "
                  f"{acc['currency']} — equity {acc['equity']}")
        except dx.DemoExecutionRefused as exc:
            print("REFUS FAIL-CLOSED:", exc); return

        for sym in CANDIDATS:
            if not mt5.symbol_select(sym, True):
                print(f"  {sym}: non sélectionnable"); continue
            si = mt5.symbol_info(sym)
            if si is None or si.trade_mode == mt5.SYMBOL_TRADE_MODE_DISABLED:
                print(f"  {sym}: marché fermé/négoce désactivé"); continue
            rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 120)
            if rates is None or len(rates) < 60:
                print(f"  {sym}: pas assez de données"); continue
            atr, direction = atr_et_direction(rates)
            if atr <= 0:
                print(f"  {sym}: ATR invalide"); continue
            r = dx.place_market_order(mt5, sym, direction, atr, sl_atr_mult=2.0,
                                      tp_atr_mult=3.0, guards=GUARDS)
            if r["sent"]:
                print(f"\n>>> PREMIER TRADE DÉMO PLACÉ : {sym} {direction.upper()} "
                      f"lot {r['lot']} @ {r['price']} (SL {r['sl']:.2f} / TP {r['tp']:.2f}) "
                      f"— risque {r['risk_money']} {acc['currency']}")
                return
            print(f"  {sym} {direction}: non envoyé — {r['reason']}")
        print("\nAucun trade placé (marchés fermés ou gardes actifs). "
              "Réessayer à l'ouverture des marchés.")
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
