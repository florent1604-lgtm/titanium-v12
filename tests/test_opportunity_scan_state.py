from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest


def _load_module():
    path = Path("core/opportunity_scan.py").resolve()
    spec = importlib.util.spec_from_file_location("opportunity_scan_state_test", path)
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get("pandas")
    sys.modules["pandas"] = types.ModuleType("pandas")
    try:
        assert spec.loader is not None
        spec.loader.exec_module(module)
    finally:
        if previous is None:
            sys.modules.pop("pandas", None)
        else:
            sys.modules["pandas"] = previous
    return module


def test_load_state_does_not_restore_transient_running_flag(tmp_path, monkeypatch):
    scan = _load_module()
    state_path = tmp_path / "opportunities.json"
    state_path.write_text(
        json.dumps(
            {
                "last_run": "2026-07-09T12:53:59+00:00",
                "running": True,
                "progress": "scan univers…",
                "last_error": "MT5 initialize: Authorization failed",
                "ranking": [{"symbol": "XAUUSD"}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(scan, "OPP_PATH", state_path)

    scan._load_state()

    assert scan.opp_state["running"] is False
    assert scan.opp_state["progress"] is None
    assert scan.opp_state["last_run"] == "2026-07-09T12:53:59+00:00"
    assert scan.opp_state["ranking"] == [{"symbol": "XAUUSD"}]


def test_scan_blocking_rejects_an_empty_universe(monkeypatch):
    scan = _load_module()
    optimizer = types.ModuleType("tools.asset_optimizer")
    optimizer.list_universe = lambda: []
    optimizer.run_pass1 = lambda _uni: pytest.fail("pass1 must not run on an empty universe")
    optimizer.run_pass2 = lambda _uni, _shortlist: pytest.fail("pass2 must not run")
    monkeypatch.setitem(sys.modules, "tools.asset_optimizer", optimizer)

    with pytest.raises(RuntimeError, match="OPPORTUNITY_UNIVERSE_EMPTY"):
        scan._scan_blocking()
