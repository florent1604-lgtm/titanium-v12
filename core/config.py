"""core/config.py — Config TYPÉE unifiée (N0, socle). Réorg Phase 1.3 (27/07/2026).

`utils/config.py` reste la source runtime des ~94 modules qui l'importent (on ne casse rien).
Ce module ajoute, EN PLUS, une vue **typée et validée** (pydantic-settings) des paramètres qui
gouvernent la décision dans la pyramide (exécution démo, confluence, raffinement, filtre
tendance, gestion dynamique, caps de risque, toggles de pôles). Adoption progressive : les
niveaux réorganisés liront `get_settings()` au lieu de constantes éparses (Phase 1.4+).

INVARIANT #6 (socle ne dépend de rien) : n'importe aucun module métier. `extra="ignore"` →
les dizaines d'autres variables d'env non modélisées ici ne font pas échouer la validation.
Aucun SECRET n'est exposé ici (ADMIN_TOKEN, clés API restent hors de cette vue, gérés ailleurs).
"""
from __future__ import annotations

from pathlib import Path
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    """Vue typée des paramètres de décision. Les noms de champs (snake_case) sont appariés
    aux variables d'env MAJUSCULES de façon insensible à la casse."""
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE) if _ENV_FILE.exists() else None,
        env_file_encoding="utf-8", extra="ignore", case_sensitive=False,
    )

    # ── Infra ──
    uvicorn_host: str = "127.0.0.1"
    port: int = 8090

    # ── Exécution DÉMO MT5 (N5) ──
    demo_exec_enabled: bool = False
    demo_expected_login: int = 0
    demo_risk_pct: float = 0.5
    demo_max_positions: int = 3
    demo_max_pos_per_symbol: int = 1
    demo_max_spread_frac_of_sl: float = 0.75

    # ── Gestion dynamique des positions (N4/N5) ──
    demo_manage_enabled: bool = False
    demo_manage_seconds: int = 15
    demo_breakeven_r: float = 0.8
    demo_trail_start_r: float = 1.2
    demo_trail_dist_r: float = 0.8

    # ── Confluence / fusion (N3) ──
    confluence_demo_enabled: bool = False
    confluence_demo_ltf: str = "M15"
    confluence_demo_htf: str = "H4"
    confluence_demo_seconds: int = 300
    confluence_rotate_batch: int = 10
    confluence_demo_auto_universe: bool = False
    confluence_aggressive_min: int = 4
    confluence_aggressive_exec: bool = False

    # ── Filtre de tendance anti-fade (N4) ──
    confluence_trend_align: bool = False
    confluence_trend_align_min_atr: float = 0.25

    # ── Raffinement d'entrée par TF inférieurs (N3/N4) ──
    entry_refine_enabled: bool = False
    entry_refine_ltf: str = "M5"
    entry_refine_micro_tf: str = "M1"
    entry_refine_sl_floor_frac: float = 0.6

    # ── Porte neuronale (N4) ──
    brain_gate_permissive: bool = False

    # ── Caps de risque portefeuille (N4) ──
    risk_max_strategy_pct: float = 40.0
    risk_max_cluster_pct: float = 60.0
    risk_max_net_pct: float = 100.0

    # ── Toggles de pôles / boucles ──
    fundamentals_enabled: bool = True
    spectral_enabled: bool = False
    swing_enabled: bool = False
    forex_enabled: bool = False
    opp_scan_enabled: bool = False

    @field_validator("confluence_demo_ltf", "confluence_demo_htf",
                     "entry_refine_ltf", "entry_refine_micro_tf")
    @classmethod
    def _upper_tf(cls, v: str) -> str:
        return (v or "").strip().upper()

    def summary(self) -> dict:
        """Vue courte non sensible pour /health et le dashboard (aucun secret)."""
        return {
            "port": self.port, "demo_exec": self.demo_exec_enabled,
            "demo_login": self.demo_expected_login,
            "manage": self.demo_manage_enabled,
            "breakeven_R": self.demo_breakeven_r, "trail": [self.demo_trail_start_r, self.demo_trail_dist_r],
            "trend_align": self.confluence_trend_align, "refine": self.entry_refine_enabled,
            "auto_universe": self.confluence_demo_auto_universe,
            "max_pos_per_symbol": self.demo_max_pos_per_symbol,
        }


_settings: Settings | None = None


def get_settings(reload: bool = False) -> Settings:
    """Retourne la vue de config typée (singleton). `reload=True` relit le `.env`."""
    global _settings
    if _settings is None or reload:
        _settings = Settings()
    return _settings
