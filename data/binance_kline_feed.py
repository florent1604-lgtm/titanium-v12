"""data/binance_kline_feed.py — Clôture de bougie AUTORITAIRE & basse latence (Binance).

Réponse au P0 « bougie clôturée non fiable » (red-team Codex + demande Florent :
source la plus rapide et fiable). Le flux WS `@kline_<interval>` de Binance porte
un champ `k.x` = **isClosed** : quand `x=true`, l'échange a OFFICIELLEMENT fermé la
bougie, poussé à l'instant même. C'est l'horloge de RÉFÉRENCE — pas notre horloge
locale, pas l'agrégation aggTrade (dont le bucket courant n'est jamais « fermé »),
pas le REST (qui renvoie la kline en formation).

⚠️ NON câblé au pipeline de décision (consigne Florent : on finit les vérifs Codex
et on le laisse relancer sa boucle avant tout câblage prod). Ici : la SOURCE + une
mesure de latence, prêtes à l'emploi et re-reviewables.
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Callable, Optional

INTERVALS = {"M1": "1m", "M5": "5m", "M15": "15m", "M30": "30m",
             "H1": "1h", "H4": "4h", "D1": "1d"}


class CloseDedup:
    """Garde de DÉDUPLICATION + ORDRE par (symbole, intervalle). Binance peut renvoyer
    deux fois la même bougie fermée (reconnexion, doublon de stream) ou un message en
    retard. `accept(cndl)` = True une seule fois par clôture, et jamais pour un
    close_time ≤ au dernier accepté (hors-ordre). PUR, testable sans réseau."""

    def __init__(self) -> None:
        self._last: dict = {}

    @staticmethod
    def _identity(cndl: Optional[dict]):
        if not cndl or not cndl.get("is_closed"):
            return None
        key = (cndl.get("symbol"), cndl.get("interval"))
        ct = cndl.get("close_time_ms")
        if not all(key) or ct is None:
            return None
        return key, ct

    def is_new(self, cndl: Optional[dict]) -> bool:
        """Vérifie sans muter : un callback en échec doit rester rejouable."""
        ident = self._identity(cndl)
        if ident is None:
            return False
        key, ct = ident
        prev = self._last.get(key)
        return prev is None or ct > prev

    def commit(self, cndl: Optional[dict]) -> bool:
        """Marque la clôture traitée, uniquement APRÈS succès du consommateur."""
        ident = self._identity(cndl)
        if ident is None or not self.is_new(cndl):
            return False
        key, ct = ident
        self._last[key] = ct
        return True

    def accept(self, cndl: Optional[dict]) -> bool:
        """Compatibilité pour les usages purs : vérifie puis commit immédiatement."""
        return self.commit(cndl)


def parse_kline_msg(msg: dict, recv_ms: Optional[int] = None) -> Optional[dict]:
    """Extrait une bougie d'un message kline WS. PUR (testable sans réseau).
    Retourne None si ce n'est pas un kline. `is_closed` = drapeau autoritaire `x`."""
    k = msg.get("k") if isinstance(msg, dict) else None
    if not isinstance(k, dict) or "x" not in k:
        return None
    recv_ms = recv_ms if recv_ms is not None else int(time.time() * 1000)
    close_ms = int(k["T"])                         # heure de clôture officielle (ms)
    return {
        "symbol": msg.get("s") or k.get("s"),
        "interval": k.get("i"),
        "open_time_ms": int(k["t"]),
        "close_time_ms": close_ms,
        "open": float(k["o"]), "high": float(k["h"]),
        "low": float(k["l"]), "close": float(k["c"]), "volume": float(k["v"]),
        "is_closed": bool(k["x"]),                  # ← LE signal de clôture autoritaire
        # latence = quand on REÇOIT le 'closed' vs l'heure de clôture officielle
        "close_latency_ms": (recv_ms - close_ms) if bool(k["x"]) else None,
    }


async def stream_closed_candles(symbols, interval: str, on_closed: Callable[[dict], None],
                                *, base: str = "wss://stream.binance.com:9443") -> None:
    """Écoute les flux kline et n'appelle `on_closed(candle)` que sur `x=true`
    (bougie officiellement fermée). Reconnexion sur erreur. Read-only, aucun ordre."""
    import aiohttp
    iv = INTERVALS.get(interval, interval)
    streams = "/".join(f"{s.replace('/', '').lower()}@kline_{iv}" for s in symbols)
    url = f"{base}/stream?streams={streams}"
    dedup = CloseDedup()                    # survit aux reconnexions (dédup/ordre)
    backoff = 1.0
    while True:
        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.ws_connect(url, heartbeat=30) as ws:
                    backoff = 1.0
                    async for raw in ws:
                        if raw.type != aiohttp.WSMsgType.TEXT:
                            continue
                        data = json.loads(raw.data)
                        payload = data.get("data", data)
                        cndl = parse_kline_msg(payload)
                        if dedup.is_new(cndl):          # x=true, ni doublon ni hors-ordre
                            res = on_closed(cndl)
                            if asyncio.iscoroutine(res):  # callback async supporté
                                await res
                            dedup.commit(cndl)           # jamais avant succès du callback
        except Exception:
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)


async def _measure(symbol: str = "BTCUSDT", interval: str = "M1", n: int = 2) -> None:
    """Mesure la latence de clôture sur `n` bougies (démo de la fiabilité)."""
    got = []
    def on_closed(c):
        got.append(c)
        print(f"  {c['symbol']} {c['interval']} close={c['close']} "
              f"latence_cloture={c['close_latency_ms']} ms")
        if len(got) >= n:
            raise asyncio.CancelledError
    try:
        await stream_closed_candles([symbol], interval, on_closed)
    except asyncio.CancelledError:
        pass


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print("Mesure de latence de clôture (flux @kline, drapeau x=isClosed)…")
    asyncio.run(_measure())
