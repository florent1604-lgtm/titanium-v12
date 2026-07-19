from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException

import api.auth as auth


def test_auth_module_does_not_depend_on_runtime_trading_config():
    source = Path("api/auth.py").read_text(encoding="utf-8")
    assert "from utils.config import ADMIN_TOKEN" not in source


def test_require_admin_is_fail_closed_without_server_token(monkeypatch):
    monkeypatch.setattr(auth, "ADMIN_TOKEN", "")
    with pytest.raises(HTTPException) as error:
        asyncio.run(auth.require_admin("presented"))
    assert error.value.status_code == 403


def test_require_admin_accepts_only_the_exact_server_token(monkeypatch):
    monkeypatch.setattr(auth, "ADMIN_TOKEN", "server-secret")
    with pytest.raises(HTTPException) as error:
        asyncio.run(auth.require_admin("wrong"))
    assert error.value.status_code == 403
    asyncio.run(auth.require_admin("server-secret"))
