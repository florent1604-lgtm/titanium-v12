"""tests/test_ws_realtime_garde.py — garde-fous du flux /ws/realtime.

Preuves exigées par la revue red-team de Codex (22/07/2026) avant que le
correctif d'emballement ne soit considéré comme acquis. L'incident d'origine :
chaque connexion ouvrait sa propre boucle de lecture MT5 à 5 Hz sur un verrou
partagé — 34 372 s de CPU cumulées en 8 h, tous les endpoints figés.

On teste les garanties, pas l'implémentation : lecture mutualisée, plafond
d'admission réellement atomique, et nettoyage garanti du registre de clients.
"""
import asyncio

import pytest

import api.api_server as api


@pytest.fixture(autouse=True)
def _etat_propre():
    """Chaque test part d'un registre vide et d'un cache froid."""
    api._RT_CLIENTS.clear()
    api._RT_CACHE.update(at=0.0, ticks=None)
    api._RT_FETCH_LOCK = None
    yield
    api._RT_CLIENTS.clear()
    api._RT_CACHE.update(at=0.0, ticks=None)
    api._RT_FETCH_LOCK = None


# ── Lecture MT5 mutualisée ───────────────────────────────────────────────────

def test_lectures_concurrentes_coalescent_en_une_seule(monkeypatch):
    """20 clients simultanés ne doivent produire QU'UNE lecture MT5."""
    appels = []

    def faux_get_ticks(symbols):
        appels.append(symbols)
        return {"BTC/USDT": {"bid": 1.0}}

    import data.mt5_provider as mp
    monkeypatch.setattr(mp, "get_ticks_fast", faux_get_ticks)

    async def scenario():
        return await asyncio.gather(*(api._rt_ticks() for _ in range(20)))

    resultats = asyncio.run(scenario())
    assert len(appels) == 1, f"{len(appels)} lectures MT5 pour 20 clients"
    assert all(r == {"BTC/USDT": {"bid": 1.0}} for r in resultats)


def test_cache_expire_apres_son_ttl(monkeypatch):
    """Passé le TTL, une nouvelle lecture doit avoir lieu — sinon on sert du figé."""
    appels = []
    import data.mt5_provider as mp
    monkeypatch.setattr(mp, "get_ticks_fast", lambda s: appels.append(1) or {"x": 1})

    async def scenario():
        await api._rt_ticks()
        api._RT_CACHE["at"] -= (api._RT_CACHE_TTL + 1.0)   # on vieillit le cache
        await api._rt_ticks()

    asyncio.run(scenario())
    assert len(appels) == 2


def test_ttl_inferieur_a_la_periode_d_envoi():
    """Le TTL doit rester sous la cadence d'envoi, sinon les clients voient du retard."""
    assert 0 < api._RT_CACHE_TTL < 0.2


# ── Plafond d'admission ──────────────────────────────────────────────────────

class _FauxWS:
    """WebSocket minimal : on n'observe que l'admission et la fermeture."""

    def __init__(self):
        self.accepte = False
        self.code_ferme = None
        self.query_params = {}

    async def accept(self):
        await asyncio.sleep(0)        # un vrai handshake cède la main ICI
        self.accepte = True

    async def close(self, code=1000):
        self.code_ferme = code

    async def send_json(self, _):
        raise api.WebSocketDisconnect()


def test_plafond_tient_face_a_des_handshakes_simultanes(monkeypatch):
    """Le point exact relevé par Codex : la réservation doit précéder tout await.

    Tester le plafond puis `await accept()` puis inscrire laissait passer
    ensemble autant de connexions qu'il y avait de handshakes concurrents.
    """
    monkeypatch.setattr(api, "_rt_ticks", lambda: asyncio.sleep(0, result={}))
    monkeypatch.setattr(api, "_book_snapshot", lambda s: {})

    clients = [_FauxWS() for _ in range(30)]

    async def scenario():
        await asyncio.gather(*(api.websocket_realtime(c) for c in clients))

    asyncio.run(scenario())
    admis = [c for c in clients if c.accepte]
    refuses = [c for c in clients if c.code_ferme == 1013]
    assert len(admis) <= api._RT_MAX_CLIENTS, f"{len(admis)} admis > {api._RT_MAX_CLIENTS}"
    assert len(admis) + len(refuses) == 30, "toute connexion doit être admise ou refusée"


def test_le_registre_est_vide_apres_deconnexion(monkeypatch):
    """Une boucle orpheline est exactement ce qui a fait s'emballer le service."""
    monkeypatch.setattr(api, "_rt_ticks", lambda: asyncio.sleep(0, result={}))
    monkeypatch.setattr(api, "_book_snapshot", lambda s: {})

    async def scenario():
        for _ in range(50):                    # reconnexions en rafale
            await api.websocket_realtime(_FauxWS())

    asyncio.run(scenario())
    assert len(api._RT_CLIENTS) == 0, "fuite de clients : le finally n'a pas nettoyé"


def test_une_erreur_inattendue_nettoie_aussi(monkeypatch):
    """Même sur exception non prévue, la place doit être rendue — et journalisée."""
    monkeypatch.setattr(api, "_rt_ticks", lambda: asyncio.sleep(0, result={}))

    def boum(_):
        raise RuntimeError("carnet indisponible")

    monkeypatch.setattr(api, "_book_snapshot", boum)
    asyncio.run(api.websocket_realtime(_FauxWS()))
    assert len(api._RT_CLIENTS) == 0
