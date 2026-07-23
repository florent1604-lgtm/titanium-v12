"""Normalisation de l'heure serveur MT5 vers UTC (sans connexion MT5)."""
from datetime import datetime, timezone

from data import mt5_provider as mp


def _server_epoch(wall_time: datetime) -> int:
    """Encode une heure murale serveur comme le champ ``time`` observé chez Axi."""
    return int(wall_time.replace(tzinfo=timezone.utc).timestamp())


def test_server_time_to_utc_applique_offset_hiver_et_ete():
    raw = [
        _server_epoch(datetime(2026, 1, 15, 12, 0)),
        _server_epoch(datetime(2026, 7, 15, 12, 0)),
    ]

    idx = mp._server_epoch_to_utc(raw, server_timezone="Europe/Helsinki")

    assert idx[0].isoformat() == "2026-01-15T10:00:00+00:00"  # UTC+2
    assert idx[1].isoformat() == "2026-07-15T09:00:00+00:00"  # UTC+3


def test_server_time_to_utc_reste_monotone():
    raw = [
        _server_epoch(datetime(2026, 7, 15, 12, 0)),
        _server_epoch(datetime(2026, 7, 15, 12, 15)),
    ]

    idx = mp._server_epoch_to_utc(raw, server_timezone="Europe/Helsinki")

    assert str(idx.tz) == "UTC"
    assert idx.is_monotonic_increasing
    assert (idx[1] - idx[0]).total_seconds() == 900
