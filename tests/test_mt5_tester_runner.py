from __future__ import annotations

import hashlib
import json
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
import tools.mt5_tester_runner as runner_module

from tools.mt5_tester_runner import (
    ExperimentManifest,
    ReportValidationError,
    PreflightError,
    RunState,
    RunStateStore,
    align_daily_returns,
    daily_net_returns,
    evaluate_native_run,
    launch_isolated_tester,
    main,
    parse_native_report,
    preflight,
    prepare_run,
    render_ini,
    write_ini_utf16le,
)


def _manifest_mapping() -> dict:
    return {
        "schema_version": "mt5-native-experiment/v1",
        "run_id": "xau-h1-20260712-a",
        "mode": "paper",
        "expert": {"name": "TitaniumV3", "sha256": "a" * 64},
        "symbol": "XAUUSD",
        "period": "H1",
        "model": 1,
        "deposit": 10_000,
        "currency": "EUR",
        "leverage": 100,
        "candidates": {
            "baseline": {"parameters": {"RiskPct": 0.5, "ScoreMin": 9}},
            "strict": {"parameters": {"RiskPct": 0.25, "ScoreMin": 11}},
        },
        "segments": {
            "dev": {"start": "2023-01-01T00:00:00Z", "end": "2024-01-01T00:00:00Z"},
            "selection": {"start": "2024-01-01T00:00:00Z", "end": "2025-01-01T00:00:00Z"},
            "final": {"start": "2025-01-01T00:00:00Z", "end": "2026-01-01T00:00:00Z"},
        },
        "costs": {"spread_points": 25, "commission_per_lot_eur": 7.0},
        "selection_rule": "max_expectancy",
        "block_length": 5,
        "bootstrap_replications": 200,
        "bootstrap_seed": 17,
    }


def _manifest() -> ExperimentManifest:
    return ExperimentManifest.from_mapping(_manifest_mapping())


def test_manifest_is_paper_only_and_rejects_secret_fields():
    data = _manifest_mapping()
    data["mode"] = "live"
    with pytest.raises(ValueError, match="paper"):
        ExperimentManifest.from_mapping(data)

    data = _manifest_mapping()
    data["broker"] = {"password": "must-not-enter-artifacts"}
    with pytest.raises(ValueError, match="secret|credential"):
        ExperimentManifest.from_mapping(data)


def test_manifest_hash_is_canonical_and_segments_do_not_overlap():
    first = _manifest_mapping()
    second = dict(reversed(list(first.items())))
    assert ExperimentManifest.from_mapping(first).preregistration_hash == (
        ExperimentManifest.from_mapping(second).preregistration_hash
    )

    overlapping = _manifest_mapping()
    overlapping["segments"]["selection"]["start"] = "2023-12-31T00:00:00Z"
    with pytest.raises(ValueError, match="overlap"):
        ExperimentManifest.from_mapping(overlapping)


def test_prepare_run_is_exclusive_and_records_canonical_manifest(tmp_path: Path):
    manifest = _manifest()
    run_dir = prepare_run(manifest, tmp_path)
    saved = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert saved["preregistration_hash"] == manifest.preregistration_hash
    assert json.loads((run_dir / "state.json").read_text(encoding="utf-8"))["state"] == "PLANNED"
    with pytest.raises(FileExistsError):
        prepare_run(manifest, tmp_path)


def test_ini_is_utf16le_cloud_free_and_contains_no_credentials(tmp_path: Path):
    manifest = _manifest()
    report = (tmp_path / "native" / "baseline-dev.xml").resolve()
    content = render_ini(manifest, "baseline", "dev", report)
    assert "UseCloud=0" in content
    assert f"Report={report}" in content
    assert "Login=" not in content
    assert "Password=" not in content
    assert "Server=" not in content

    ini = tmp_path / "baseline-dev.ini"
    write_ini_utf16le(ini, content)
    raw = ini.read_bytes()
    assert raw.startswith(b"\xff\xfe")
    assert raw.decode("utf-16") == content


def test_state_machine_consumes_final_only_once(tmp_path: Path):
    store = RunStateStore(tmp_path / "state.json")
    store.initialize()
    store.transition(RunState.PLANNED, RunState.PREFLIGHT)
    store.transition(RunState.PREFLIGHT, RunState.DEV)
    store.transition(RunState.DEV, RunState.SELECTION)
    store.transition(RunState.SELECTION, RunState.FINAL_LOCKED)
    store.transition(RunState.FINAL_LOCKED, RunState.FINAL_CONSUMED)
    with pytest.raises(RuntimeError, match="expected FINAL_LOCKED"):
        store.transition(RunState.FINAL_LOCKED, RunState.FINAL_CONSUMED)


def test_state_machine_consumes_final_only_once_under_concurrency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    store = RunStateStore(tmp_path / "state.json")
    store.initialize()
    store.transition(RunState.PLANNED, RunState.PREFLIGHT)
    store.transition(RunState.PREFLIGHT, RunState.DEV)
    store.transition(RunState.DEV, RunState.SELECTION)
    store.transition(RunState.SELECTION, RunState.FINAL_LOCKED)

    original_write = runner_module._atomic_json_write

    def slow_write(path, value):
        time.sleep(0.05)
        original_write(path, value)

    monkeypatch.setattr(runner_module, "_atomic_json_write", slow_write)
    start = threading.Event()
    outcomes = []

    def consume_final():
        start.wait()
        try:
            store.transition(RunState.FINAL_LOCKED, RunState.FINAL_CONSUMED)
            outcomes.append("ok")
        except RuntimeError:
            outcomes.append("rejected")

    workers = [threading.Thread(target=consume_final) for _ in range(4)]
    for worker in workers:
        worker.start()
    start.set()
    for worker in workers:
        worker.join(timeout=5)

    assert not any(worker.is_alive() for worker in workers)
    assert outcomes.count("ok") == 1
    assert outcomes.count("rejected") == 3
    assert store.read()["history"].count(RunState.FINAL_CONSUMED.value) == 1


def _healthy_preflight(tmp_path: Path) -> dict:
    isolated_terminal = tmp_path / "tester" / "terminal64.exe"
    isolated_data = isolated_terminal.parent
    isolated_terminal.parent.mkdir(parents=True, exist_ok=True)
    isolated_terminal.touch()
    return {
        "paper_only": True,
        "terminal_executable": str(isolated_terminal),
        "terminal_data_dir": str(isolated_data),
        "live_terminal_executable": r"C:\Program Files\MetaTrader 5\terminal64.exe",
        "live_terminal_data_dir": r"C:\Users\flore\AppData\Roaming\MetaQuotes\Terminal\LIVE",
        "network_isolated": True,
        "cloud_disabled": True,
        "strong_password_configured": True,
        "opportunity_scan_active": False,
        "mt5_source_age_seconds": 2.0,
        "mt5_max_age_seconds": 15.0,
        "market_session": True,
        "agent_count": 2,
    }


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("paper_only", False, "paper"),
        ("network_isolated", False, "network"),
        ("cloud_disabled", False, "cloud"),
        ("strong_password_configured", False, "password"),
        ("opportunity_scan_active", True, "opportunity"),
        ("mt5_source_age_seconds", 60.0, "stale"),
        ("agent_count", 3, "agent"),
    ],
)
def test_preflight_fails_closed(field: str, value: object, message: str, tmp_path: Path):
    health = _healthy_preflight(tmp_path)
    health[field] = value
    with pytest.raises(PreflightError, match=message):
        preflight(health)


def test_preflight_rejects_live_terminal_or_shared_data_dir(tmp_path: Path):
    health = _healthy_preflight(tmp_path)
    health["live_terminal_executable"] = health["terminal_executable"]
    with pytest.raises(PreflightError, match="isolated terminal"):
        preflight(health)

    health = _healthy_preflight(tmp_path)
    health["live_terminal_data_dir"] = health["terminal_data_dir"]
    with pytest.raises(PreflightError, match="isolated data"):
        preflight(health)


@pytest.mark.parametrize("market_session", ["true", "false", 1, 0, None])
def test_preflight_requires_strict_boolean_market_session(
    market_session: object, tmp_path: Path
):
    health = _healthy_preflight(tmp_path)
    health["market_session"] = market_session
    health["agent_count"] = 8
    with pytest.raises(PreflightError, match="market session"):
        preflight(health)


def test_preflight_requires_portable_data_dir_bound_to_terminal(tmp_path: Path):
    health = _healthy_preflight(tmp_path)
    health["terminal_data_dir"] = str(tmp_path / "different-data-dir")
    Path(health["terminal_data_dir"]).mkdir()
    with pytest.raises(PreflightError, match="portable data"):
        preflight(health)


def test_launcher_uses_no_shell_and_low_priority_without_taskkill(tmp_path: Path):
    health = _healthy_preflight(tmp_path)
    terminal = Path(health["terminal_executable"])
    health["terminal_data_dir"] = str(terminal.parent)
    approved = preflight(health)
    expert = terminal.parent / "MQL5" / "Experts" / "TitaniumV3.ex5"
    expert.parent.mkdir(parents=True)
    expert.write_bytes(b"approved-ea")
    manifest_data = _manifest_mapping()
    manifest_data["expert"]["sha256"] = hashlib.sha256(expert.read_bytes()).hexdigest()
    manifest = ExperimentManifest.from_mapping(manifest_data)
    config = (tmp_path / "tester.ini").resolve()
    write_ini_utf16le(
        config,
        render_ini(manifest, "baseline", "dev", (tmp_path / "report.xml").resolve()),
    )
    terminal.touch()
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    result = launch_isolated_tester(
        approved,
        manifest,
        config,
        timeout_seconds=30,
        runner=fake_run,
    )
    assert result.returncode == 0
    command, kwargs = calls[0]
    assert command[0] == str(terminal)
    assert command[1] == "/portable"
    assert command[2] == f"/config:{config}"
    assert kwargs["cwd"] == str(terminal.parent.resolve())
    assert kwargs["shell"] is False
    assert kwargs["creationflags"] & 0x00004000
    assert all("taskkill" not in item.lower() for item in command)


def test_launcher_rejects_expert_binary_hash_mismatch(tmp_path: Path):
    health = _healthy_preflight(tmp_path)
    terminal = Path(health["terminal_executable"])
    health["terminal_data_dir"] = str(terminal.parent)
    approved = preflight(health)
    expert = terminal.parent / "MQL5" / "Experts" / "TitaniumV3.ex5"
    expert.parent.mkdir(parents=True)
    expert.write_bytes(b"not-the-preregistered-ea")
    config = (tmp_path / "tester.ini").resolve()
    write_ini_utf16le(
        config,
        render_ini(_manifest(), "baseline", "dev", (tmp_path / "report.xml").resolve()),
    )

    with pytest.raises(PreflightError, match="expert.*hash"):
        launch_isolated_tester(approved, _manifest(), config, timeout_seconds=30)


@pytest.mark.parametrize(
    ("original", "tampered"),
    [
        ("UseCloud=0", "UseCloud=1"),
        ("UseCloud=0", "UseCloud=0\r\nusecloud=1"),
        ("Expert=TitaniumV3", "Expert=OtherEA"),
        ("ShutdownTerminal=1", "ShutdownTerminal=0"),
    ],
)
def test_launcher_rejects_tampered_tester_config(
    original: str, tampered: str, tmp_path: Path
):
    health = _healthy_preflight(tmp_path)
    terminal = Path(health["terminal_executable"])
    approved = preflight(health)
    expert = terminal.parent / "MQL5" / "Experts" / "TitaniumV3.ex5"
    expert.parent.mkdir(parents=True)
    expert.write_bytes(b"approved-ea")
    manifest_data = _manifest_mapping()
    manifest_data["expert"]["sha256"] = hashlib.sha256(expert.read_bytes()).hexdigest()
    manifest = ExperimentManifest.from_mapping(manifest_data)
    config = (tmp_path / "tester.ini").resolve()
    content = render_ini(manifest, "baseline", "dev", (tmp_path / "report.xml").resolve())
    write_ini_utf16le(config, content.replace(original, tampered))

    with pytest.raises(PreflightError, match="config"):
        launch_isolated_tester(
            approved,
            manifest,
            config,
            timeout_seconds=30,
            runner=lambda *args, **kwargs: pytest.fail("tampered config reached process launch"),
        )


def _expected_report(segment: str = "dev", candidate: str = "baseline") -> dict:
    manifest = _manifest()
    spec = manifest.segments[segment]
    return {
        "symbol": manifest.symbol,
        "period": manifest.period,
        "model": str(manifest.model),
        "expert": manifest.expert_name,
        "from": f"{spec.start:%Y.%m.%d}",
        "to": f"{spec.end:%Y.%m.%d}",
        "parameters": manifest.candidates[candidate],
    }


def _xml_report(segment: str = "dev", candidate: str = "baseline") -> str:
    expected = _expected_report(segment, candidate)
    parameters = "".join(
        f'<parameter name="{name}" value="{value}" />'
        for name, value in expected["parameters"].items()
    )
    return f"""<?xml version="1.0" encoding="utf-8"?>
<mt5-report>
  <meta symbol="{expected['symbol']}" period="{expected['period']}"
        model="{expected['model']}" expert="{expected['expert']}"
        from="{expected['from']}" to="{expected['to']}" />
  <parameters>{parameters}</parameters>
  <metrics>
    <metric name="Profit Factor" value="1,42" />
    <metric name="Total Net Profit" value="98,50" />
  </metrics>
  <deals>
    <deal time="2023.01.02 12:00:00" profit="100,00" commission="-2,00" swap="-0,50" />
    <deal time="2023.01.03 12:00:00" profit="-25,00" commission="-1,00" swap="0,00" />
  </deals>
</mt5-report>
"""


def test_xml_native_report_is_validated_and_preserves_native_metrics(tmp_path: Path):
    path = tmp_path / "report.xml"
    path.write_text(_xml_report(), encoding="utf-8")
    report = parse_native_report(path, _expected_report())
    assert report.metadata["symbol"] == "XAUUSD"
    assert report.metrics["profit_factor"] == pytest.approx(1.42)
    assert report.metrics["total_net_profit"] == pytest.approx(98.5)
    assert len(report.sha256) == 64
    assert len(report.deals) == 2


def test_native_report_metadata_mismatch_is_fail_closed(tmp_path: Path):
    path = tmp_path / "report.xml"
    path.write_text(_xml_report().replace('symbol="XAUUSD"', 'symbol="EURUSD"'), encoding="utf-8")
    with pytest.raises(ReportValidationError, match="symbol"):
        parse_native_report(path, _expected_report())


def test_html_native_report_is_parsed_without_executing_markup(tmp_path: Path):
    path = tmp_path / "report.html"
    path.write_text(
        """<html><body><table>
        <tr><td>Symbol:</td><td>XAUUSD</td></tr>
        <tr><td>Period:</td><td>H1</td></tr>
        <tr><td>Model:</td><td>1</td></tr>
        <tr><td>Expert:</td><td>TitaniumV3</td></tr>
        <tr><td>From:</td><td>2023.01.01</td></tr>
        <tr><td>To:</td><td>2024.01.01</td></tr>
        <tr><td>Inputs:</td><td>RiskPct=0.5; ScoreMin=9</td></tr>
        <tr><td>Profit Factor:</td><td>1,42</td></tr>
        <tr><th>Time</th><th>Profit</th><th>Commission</th><th>Swap</th></tr>
        <tr><td>2023.01.02 12:00:00</td><td>100,00</td><td>-2,00</td><td>-0,50</td></tr>
        </table><script>raise new Error('must never execute')</script></body></html>""",
        encoding="utf-8",
    )
    report = parse_native_report(path, _expected_report())
    assert report.metrics["profit_factor"] == pytest.approx(1.42)
    assert report.deals[0].net == pytest.approx(97.5)


def test_html_native_report_rejects_malformed_deal_instead_of_truncating(tmp_path: Path):
    path = tmp_path / "report.html"
    path.write_text(
        """<html><body><table>
        <tr><td>Symbol:</td><td>XAUUSD</td></tr>
        <tr><td>Period:</td><td>H1</td></tr>
        <tr><td>Model:</td><td>1</td></tr>
        <tr><td>Expert:</td><td>TitaniumV3</td></tr>
        <tr><td>From:</td><td>2023.01.01</td></tr>
        <tr><td>To:</td><td>2024.01.01</td></tr>
        <tr><td>Inputs:</td><td>RiskPct=0.5; ScoreMin=9</td></tr>
        <tr><th>Time</th><th>Profit</th><th>Commission</th><th>Swap</th></tr>
        <tr><td>malformed-time</td><td>100,00</td><td>-2,00</td><td>-0,50</td></tr>
        <tr><td>2023.01.03 12:00:00</td><td>20,00</td><td>-1,00</td><td>0,00</td></tr>
        </table></body></html>""",
        encoding="utf-8",
    )
    with pytest.raises(ReportValidationError, match="deal"):
        parse_native_report(path, _expected_report())


def test_daily_native_returns_are_aligned_on_a_common_grid(tmp_path: Path):
    report_path = tmp_path / "report.xml"
    report_path.write_text(_xml_report(), encoding="utf-8")
    report = parse_native_report(report_path, _expected_report())
    baseline = daily_net_returns(report.deals, initial_deposit=10_000)
    strict = {"2023-01-03": 0.01, "2023-01-04": -0.005}
    aligned = align_daily_returns({"baseline": baseline, "strict": strict})
    assert len(aligned["baseline"]) == 3
    assert aligned["baseline"][2] == 0.0
    assert aligned["strict"][0] == 0.0


def test_native_reports_feed_m2_and_never_authorize_live(tmp_path: Path):
    manifest = _manifest()
    reports = {}
    for candidate in manifest.candidates:
        reports[candidate] = {}
        for segment in manifest.segments:
            if segment == "final" and candidate != "baseline":
                continue
            path = tmp_path / f"{candidate}-{segment}.xml"
            xml = _xml_report(segment, candidate)
            if candidate == "strict":
                xml = xml.replace('profit="100,00"', 'profit="40,00"')
            path.write_text(xml, encoding="utf-8")
            reports[candidate][segment] = path
    result = evaluate_native_run(manifest, reports)
    assert result["selected_candidate"] == "baseline"
    assert result["status"] in {
        "INSUFFICIENT_EVIDENCE",
        "OBSERVATION",
        "VALIDATED_FOR_FORWARD_PAPER",
    }
    assert result["status"] != "LIVE"
    assert result["native_preregistration_hash"] == manifest.preregistration_hash


def test_native_evaluation_never_reads_non_selected_final_report(tmp_path: Path):
    manifest = _manifest()
    reports = {}
    for candidate in manifest.candidates:
        reports[candidate] = {}
        for segment in ("dev", "selection"):
            path = tmp_path / f"{candidate}-{segment}.xml"
            xml = _xml_report(segment, candidate)
            if candidate == "strict":
                xml = xml.replace('profit="100,00"', 'profit="40,00"')
            path.write_text(xml, encoding="utf-8")
            reports[candidate][segment] = path

    baseline_final = tmp_path / "baseline-final.xml"
    baseline_final.write_text(_xml_report("final", "baseline"), encoding="utf-8")
    reports["baseline"]["final"] = baseline_final
    strict_final = tmp_path / "strict-final.xml"
    strict_final.write_text("this holdout must never be parsed", encoding="utf-8")
    reports["strict"]["final"] = strict_final

    result = evaluate_native_run(manifest, reports)
    assert result["selected_candidate"] == "baseline"
    assert "final" in result["native_reports"]["baseline"]
    assert "final" not in result["native_reports"]["strict"]


def test_native_m2_preserves_trade_count_separately_from_daily_observations(tmp_path: Path):
    manifest = _manifest()
    reports = {}
    for candidate in manifest.candidates:
        reports[candidate] = {}
        for segment in ("dev", "selection"):
            path = tmp_path / f"{candidate}-{segment}.xml"
            xml = _xml_report(segment, candidate)
            if candidate == "strict":
                xml = xml.replace('profit="100,00"', 'profit="40,00"')
            path.write_text(xml, encoding="utf-8")
            reports[candidate][segment] = path
    final_path = tmp_path / "baseline-final.xml"
    final_path.write_text(
        _xml_report("final", "baseline").replace(
            "2023.01.03 12:00:00", "2023.01.02 18:00:00"
        ),
        encoding="utf-8",
    )
    reports["baseline"]["final"] = final_path

    result = evaluate_native_run(manifest, reports)
    selected = next(
        item for item in result["candidates"] if item["name"] == result["selected_candidate"]
    )
    assert selected["final"]["trades"] == 2
    assert selected["final"]["observations"] == 1


def test_prepare_cli_creates_run_without_launching_mt5(tmp_path: Path):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(_manifest_mapping()), encoding="utf-8")
    assert main(["prepare", str(manifest_path), "--runs-root", str(tmp_path / "runs")]) == 0
    assert (tmp_path / "runs" / "xau-h1-20260712-a" / "state.json").exists()
