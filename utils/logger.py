"""utils/logger.py — Logger structuré unique pour tout le projet."""
from __future__ import annotations
import logging
import sys
from utils.config import LOG_LEVEL

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)


def get_logger(name: str) -> logging.Logger:
    """Retourne un logger nommé. Utiliser au niveau module : logger = get_logger(__name__)"""
    return logging.getLogger(name)
