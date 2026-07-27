"""core/obs.py — observabilité structurée (structlog). Réorg Phase 2 (27/07/2026).

Infra N0 : logger STRUCTURÉ partagé avec `correlation_id` (le fil qui relie un signal à sa
décision et à son fill dans le journal). Adoption PROGRESSIVE : le logging stdlib existant
(utils/logger, 94 modules) reste en place ; le nouveau code réorganisé utilise `get_logger`
d'ici. N'importe aucun module métier (invariant #6)."""
from __future__ import annotations

import logging

import structlog

_configured = False


def _configure() -> None:
    global _configured
    if _configured:
        return
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,      # correlation_id lié au contexte
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.format_exc_info,
            structlog.processors.KeyValueRenderer(
                key_order=["timestamp", "level", "logger", "event", "correlation_id"]),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=True,
    )
    _configured = True


def get_logger(name: str | None = None):
    """Logger structuré (clé=valeur). Ex.: log.info('placed', symbol='BTCUSD', lot=0.1)."""
    _configure()
    return structlog.get_logger(name)


def bind_correlation(correlation_id: str) -> None:
    """Lie un correlation_id au contexte courant → présent sur tous les logs suivants."""
    structlog.contextvars.bind_contextvars(correlation_id=correlation_id)


def clear_correlation() -> None:
    structlog.contextvars.clear_contextvars()
