"""Fail-closed orchestration helpers for native MT5 Strategy Tester runs.

The module prepares and validates *paper-only* experiments.  It never discovers,
kills, restarts, or reconfigures the MetaTrader terminal used by Titanium.
Actual execution requires an explicitly isolated tester executable and data dir.
"""

from __future__ import annotations

import hashlib
import argparse
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import threading
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence


SCHEMA_VERSION = "mt5-native-experiment/v1"
BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SAFE_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,63}$")
_HEX_64 = re.compile(r"^[0-9a-fA-F]{64}$")
_SECRET_KEYS = {
    "api_key",
    "authorization",
    "credential",
    "credentials",
    "login",
    "password",
    "secret",
    "server",
    "token",
}
_TOP_LEVEL_KEYS = {
    "schema_version",
    "run_id",
    "mode",
    "expert",
    "symbol",
    "period",
    "model",
    "deposit",
    "currency",
    "leverage",
    "candidates",
    "segments",
    "costs",
    "selection_rule",
    "block_length",
    "bootstrap_replications",
    "bootstrap_seed",
}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _parse_timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO-8601 timestamp")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed


def _contains_secret_key(value: object, path: str = "manifest") -> str | None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            if normalized in _SECRET_KEYS or any(
                normalized.endswith(f"_{secret}") for secret in _SECRET_KEYS
            ):
                return f"{path}.{key}"
            found = _contains_secret_key(item, f"{path}.{key}")
            if found:
                return found
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            found = _contains_secret_key(item, f"{path}[{index}]")
            if found:
                return found
    return None


def _require_safe_id(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise ValueError(f"{field} must be a safe identifier")
    return value


def _require_finite_number(value: object, field: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite number")
    number = float(value)
    if not math.isfinite(number) or (positive and number <= 0):
        raise ValueError(f"{field} must be a finite positive number")
    return number


def _validate_parameter_value(value: object, field: str) -> None:
    if not isinstance(value, (str, int, float, bool)) or value is None:
        raise ValueError(f"{field} must be a scalar")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{field} must be finite")
    if isinstance(value, str) and ("\n" in value or "\r" in value):
        raise ValueError(f"{field} contains a newline")


@dataclass(frozen=True)
class SegmentSpec:
    name: str
    start: datetime
    end: datetime
    start_raw: str
    end_raw: str


@dataclass(frozen=True)
class ExperimentManifest:
    """Validated immutable view of a native MT5 experiment manifest."""

    run_id: str
    mode: str
    expert_name: str
    expert_sha256: str
    symbol: str
    period: str
    model: int
    deposit: float
    currency: str
    leverage: int
    candidates: Mapping[str, Mapping[str, object]]
    segments: Mapping[str, SegmentSpec]
    canonical_json: str
    preregistration_hash: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "ExperimentManifest":
        if not isinstance(value, Mapping):
            raise ValueError("manifest must be an object")
        data = json.loads(_canonical_json(value))
        secret_path = _contains_secret_key(data)
        if secret_path:
            raise ValueError(f"secret or credential field forbidden: {secret_path}")
        unknown = set(data) - _TOP_LEVEL_KEYS
        missing = _TOP_LEVEL_KEYS - set(data)
        if unknown:
            raise ValueError(f"unknown manifest fields: {sorted(unknown)}")
        if missing:
            raise ValueError(f"missing manifest fields: {sorted(missing)}")
        if data["schema_version"] != SCHEMA_VERSION:
            raise ValueError(f"schema_version must be {SCHEMA_VERSION}")
        if data["mode"] != "paper":
            raise ValueError("MT5 native validation is paper only")

        run_id = _require_safe_id(data["run_id"], "run_id")
        expert = data["expert"]
        if not isinstance(expert, Mapping) or set(expert) != {"name", "sha256"}:
            raise ValueError("expert must contain exactly name and sha256")
        expert_name = _require_safe_id(expert["name"], "expert.name")
        expert_sha256 = str(expert["sha256"])
        if not _HEX_64.fullmatch(expert_sha256):
            raise ValueError("expert.sha256 must be a 64-character hex digest")

        symbol = _require_safe_id(data["symbol"], "symbol")
        period = _require_safe_id(data["period"], "period")
        currency = _require_safe_id(data["currency"], "currency")
        if not isinstance(data["model"], int) or isinstance(data["model"], bool):
            raise ValueError("model must be an integer")
        deposit = _require_finite_number(data["deposit"], "deposit", positive=True)
        if not isinstance(data["leverage"], int) or data["leverage"] <= 0:
            raise ValueError("leverage must be a positive integer")

        candidates_raw = data["candidates"]
        if not isinstance(candidates_raw, Mapping) or not candidates_raw:
            raise ValueError("candidates must be a non-empty object")
        candidates: dict[str, Mapping[str, object]] = {}
        for name, candidate in candidates_raw.items():
            safe_name = _require_safe_id(name, "candidate name")
            if not isinstance(candidate, Mapping) or set(candidate) != {"parameters"}:
                raise ValueError(f"candidate {safe_name} must contain exactly parameters")
            parameters = candidate["parameters"]
            if not isinstance(parameters, Mapping):
                raise ValueError(f"candidate {safe_name} parameters must be an object")
            copied_parameters: dict[str, object] = {}
            for key, parameter_value in parameters.items():
                if not isinstance(key, str) or not _SAFE_KEY.fullmatch(key):
                    raise ValueError(f"candidate {safe_name} has an unsafe parameter name")
                _validate_parameter_value(parameter_value, f"candidate {safe_name}.{key}")
                copied_parameters[key] = parameter_value
            candidates[safe_name] = copied_parameters

        segments_raw = data["segments"]
        if not isinstance(segments_raw, Mapping) or list(segments_raw) != ["dev", "selection", "final"]:
            if not isinstance(segments_raw, Mapping) or set(segments_raw) != {"dev", "selection", "final"}:
                raise ValueError("segments must contain dev, selection and final")
        segments: dict[str, SegmentSpec] = {}
        for name in ("dev", "selection", "final"):
            segment = segments_raw[name]
            if not isinstance(segment, Mapping) or set(segment) != {"start", "end"}:
                raise ValueError(f"segment {name} must contain exactly start and end")
            start = _parse_timestamp(segment["start"], f"segments.{name}.start")
            end = _parse_timestamp(segment["end"], f"segments.{name}.end")
            if start >= end:
                raise ValueError(f"segment {name} start must precede end")
            segments[name] = SegmentSpec(name, start, end, str(segment["start"]), str(segment["end"]))
        if segments["dev"].end > segments["selection"].start or segments["selection"].end > segments["final"].start:
            raise ValueError("validation segments overlap")

        costs = data["costs"]
        if not isinstance(costs, Mapping) or not costs:
            raise ValueError("costs must be a non-empty object")
        for key, cost in costs.items():
            if not isinstance(key, str) or not _SAFE_KEY.fullmatch(key):
                raise ValueError("costs contain an unsafe key")
            _require_finite_number(cost, f"costs.{key}")
        if data["selection_rule"] != "max_expectancy":
            raise ValueError("selection_rule must be max_expectancy")
        if not isinstance(data["block_length"], int) or data["block_length"] < 1:
            raise ValueError("block_length must be a positive integer")
        if not isinstance(data["bootstrap_replications"], int) or data["bootstrap_replications"] < 100:
            raise ValueError("bootstrap_replications must be at least 100")
        if not isinstance(data["bootstrap_seed"], int):
            raise ValueError("bootstrap_seed must be an integer")

        canonical = _canonical_json(data)
        return cls(
            run_id=run_id,
            mode="paper",
            expert_name=expert_name,
            expert_sha256=expert_sha256.lower(),
            symbol=symbol,
            period=period,
            model=data["model"],
            deposit=deposit,
            currency=currency,
            leverage=data["leverage"],
            candidates=candidates,
            segments=segments,
            canonical_json=canonical,
            preregistration_hash=_sha256_text(canonical),
        )

    def to_record(self) -> dict[str, object]:
        record = json.loads(self.canonical_json)
        record["preregistration_hash"] = self.preregistration_hash
        return record


class RunState(str, Enum):
    PLANNED = "PLANNED"
    PREFLIGHT = "PREFLIGHT"
    DEV = "DEV"
    SELECTION = "SELECTION"
    FINAL_LOCKED = "FINAL_LOCKED"
    FINAL_CONSUMED = "FINAL_CONSUMED"
    PARSED = "PARSED"
    QUALIFIED = "QUALIFIED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


_NORMAL_TRANSITIONS = {
    RunState.PLANNED: {RunState.PREFLIGHT},
    RunState.PREFLIGHT: {RunState.DEV},
    RunState.DEV: {RunState.SELECTION},
    RunState.SELECTION: {RunState.FINAL_LOCKED},
    RunState.FINAL_LOCKED: {RunState.FINAL_CONSUMED},
    RunState.FINAL_CONSUMED: {RunState.PARSED},
    RunState.PARSED: {RunState.QUALIFIED, RunState.INSUFFICIENT_EVIDENCE},
}
_TERMINAL_STATES = {RunState.FAILED, RunState.TIMEOUT, RunState.CANCELLED}
_STATE_THREAD_LOCKS: dict[str, threading.Lock] = {}
_STATE_THREAD_LOCKS_GUARD = threading.Lock()


def _atomic_json_write(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


@contextmanager
def _exclusive_file_lock(path: Path) -> Iterator[None]:
    """Serialize a state transition across both threads and processes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    key = os.path.normcase(str(path.resolve(strict=False)))
    with _STATE_THREAD_LOCKS_GUARD:
        thread_lock = _STATE_THREAD_LOCKS.setdefault(key, threading.Lock())
    with thread_lock:
        with path.open("a+b") as handle:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
                os.fsync(handle.fileno())
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            else:  # pragma: no cover - exercised on non-Windows CI only
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                handle.seek(0)
                if os.name == "nt":
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:  # pragma: no cover - exercised on non-Windows CI only
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class RunStateStore:
    def __init__(self, path: Path | str):
        self.path = Path(path)

    def initialize(self) -> None:
        lock_path = self.path.with_name(f"{self.path.name}.lock")
        with _exclusive_file_lock(lock_path):
            if self.path.exists():
                raise FileExistsError(self.path)
            _atomic_json_write(
                self.path,
                {"state": RunState.PLANNED.value, "history": [RunState.PLANNED.value]},
            )

    def read(self) -> dict[str, object]:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def transition(self, expected: RunState, target: RunState) -> None:
        lock_path = self.path.with_name(f"{self.path.name}.lock")
        with _exclusive_file_lock(lock_path):
            current = self.read()
            current_state = RunState(str(current.get("state")))
            if current_state is not expected:
                raise RuntimeError(f"state is {current_state.value}; expected {expected.value}")
            allowed = set(_NORMAL_TRANSITIONS.get(expected, set())) | _TERMINAL_STATES
            if target not in allowed:
                raise RuntimeError(f"illegal transition {expected.value} -> {target.value}")
            history = list(current.get("history", []))
            history.append(target.value)
            _atomic_json_write(self.path, {"state": target.value, "history": history})


def prepare_run(manifest: ExperimentManifest, runs_root: Path | str) -> Path:
    root = Path(runs_root)
    root.mkdir(parents=True, exist_ok=True)
    run_dir = root / manifest.run_id
    run_dir.mkdir(exist_ok=False)
    try:
        _atomic_json_write(run_dir / "manifest.json", manifest.to_record())
        RunStateStore(run_dir / "state.json").initialize()
    except BaseException:
        for child in run_dir.iterdir():
            child.unlink()
        run_dir.rmdir()
        raise
    return run_dir


def _format_ini_value(value: object) -> str:
    _validate_parameter_value(value, "INI value")
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return format(value, ".15g")
    return str(value)


def render_ini(
    manifest: ExperimentManifest,
    candidate_name: str,
    segment_name: str,
    report_path: Path | str,
) -> str:
    if candidate_name not in manifest.candidates:
        raise ValueError(f"unknown candidate: {candidate_name}")
    if segment_name not in manifest.segments:
        raise ValueError(f"unknown segment: {segment_name}")
    report = Path(report_path)
    if not report.is_absolute():
        raise ValueError("report path must be absolute")
    segment = manifest.segments[segment_name]
    lines = [
        "[Tester]",
        f"Expert={manifest.expert_name}",
        f"Symbol={manifest.symbol}",
        f"Period={manifest.period}",
        f"FromDate={segment.start:%Y.%m.%d}",
        f"ToDate={segment.end:%Y.%m.%d}",
        f"Model={manifest.model}",
        f"Deposit={_format_ini_value(manifest.deposit)}",
        f"Currency={manifest.currency}",
        f"Leverage={manifest.leverage}",
        f"Report={report}",
        "ReplaceReport=0",
        "ShutdownTerminal=1",
        "UseCloud=0",
        "",
        "[TesterInputs]",
    ]
    for key in sorted(manifest.candidates[candidate_name]):
        lines.append(f"{key}={_format_ini_value(manifest.candidates[candidate_name][key])}")
    lines.append("")
    content = "\r\n".join(lines)
    lowered = content.lower()
    if any(f"{key}=" in lowered for key in ("login", "password", "server", "token", "secret")):
        raise ValueError("credential field would be written to INI")
    return content


def write_ini_utf16le(path: Path | str, content: str) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(content, encoding="utf-16", newline="")


class PreflightError(RuntimeError):
    pass


@dataclass(frozen=True)
class PreflightResult:
    ok: bool
    terminal_executable: Path
    terminal_data_dir: Path
    agent_count: int


def _same_path(left: object, right: object) -> bool:
    left_path = Path(os.fspath(left)).resolve(strict=False)
    right_path = Path(os.fspath(right)).resolve(strict=False)
    return os.path.normcase(str(left_path)) == os.path.normcase(str(right_path))


def preflight(health: Mapping[str, object]) -> PreflightResult:
    required = {
        "paper_only",
        "terminal_executable",
        "terminal_data_dir",
        "live_terminal_executable",
        "live_terminal_data_dir",
        "network_isolated",
        "cloud_disabled",
        "strong_password_configured",
        "opportunity_scan_active",
        "mt5_source_age_seconds",
        "mt5_max_age_seconds",
        "market_session",
        "agent_count",
    }
    missing = required - set(health)
    if missing:
        raise PreflightError(f"missing preflight evidence: {sorted(missing)}")
    if health["paper_only"] is not True:
        raise PreflightError("paper-only proof is required")
    if health["network_isolated"] is not True:
        raise PreflightError("network isolation proof is required")
    if health["cloud_disabled"] is not True:
        raise PreflightError("cloud network must be disabled")
    if health["strong_password_configured"] is not True:
        raise PreflightError("strong password configuration proof is required")
    if health["opportunity_scan_active"] is not False:
        raise PreflightError("opportunity scan must be inactive before launching jobs")
    age = _require_finite_number(health["mt5_source_age_seconds"], "mt5 source age")
    max_age = _require_finite_number(health["mt5_max_age_seconds"], "MT5 max age", positive=True)
    if age < 0 or age > max_age:
        raise PreflightError("MT5 source is stale")
    if not isinstance(health["market_session"], bool):
        raise PreflightError("market session must be a boolean")
    if not isinstance(health["agent_count"], int) or isinstance(health["agent_count"], bool):
        raise PreflightError("agent count must be an integer")
    agent_count = int(health["agent_count"])
    limit = 2 if health["market_session"] is True else 8
    if agent_count < 1 or agent_count > limit:
        raise PreflightError(f"agent count exceeds safe limit {limit}")

    terminal = Path(os.fspath(health["terminal_executable"]))
    data_dir = Path(os.fspath(health["terminal_data_dir"]))
    if not terminal.is_file():
        raise PreflightError("isolated terminal executable is unavailable")
    if not data_dir.is_dir():
        raise PreflightError("isolated data directory is unavailable")
    if _same_path(terminal, health["live_terminal_executable"]):
        raise PreflightError("isolated terminal must differ from the Titanium live terminal")
    if _same_path(data_dir, health["live_terminal_data_dir"]):
        raise PreflightError("isolated data directory must differ from the Titanium live data directory")
    terminal = terminal.resolve()
    data_dir = data_dir.resolve()
    if not _same_path(data_dir, terminal.parent):
        raise PreflightError("portable data directory must be the isolated terminal directory")
    return PreflightResult(True, terminal, data_dir, agent_count)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_tester_config(path: Path, manifest: ExperimentManifest) -> None:
    raw = path.read_bytes()
    if not raw.startswith(b"\xff\xfe"):
        raise PreflightError("tester config must be UTF-16LE with BOM")
    try:
        content = raw.decode("utf-16")
    except UnicodeError as exc:
        raise PreflightError("tester config encoding is invalid") from exc
    section = ""
    tester: dict[str, str] = {}
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith((";", "#")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip().lower()
            continue
        key, separator, value = line.partition("=")
        if not separator or not key.strip():
            raise PreflightError("tester config contains a malformed line")
        key = key.strip()
        normalized = key.lower().replace("-", "_")
        if normalized in _SECRET_KEYS or any(
            normalized.endswith(f"_{secret}") for secret in _SECRET_KEYS
        ):
            raise PreflightError("tester config contains a credential field")
        if section == "tester":
            config_key = key.casefold()
            if config_key in tester:
                raise PreflightError("tester config contains a duplicate key")
            tester[config_key] = value.strip()
    expected = {
        "expert": manifest.expert_name,
        "symbol": manifest.symbol,
        "period": manifest.period,
        "model": str(manifest.model),
        "usecloud": "0",
        "shutdownterminal": "1",
        "replacereport": "0",
    }
    for key, value in expected.items():
        if tester.get(key) != value:
            raise PreflightError(f"tester config has invalid {key}")
    report = Path(tester.get("report", ""))
    if not report.is_absolute():
        raise PreflightError("tester config report path must be absolute")


def launch_isolated_tester(
    approved: PreflightResult,
    manifest: ExperimentManifest,
    config_path: Path | str,
    timeout_seconds: float,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> subprocess.CompletedProcess[str]:
    if not isinstance(approved, PreflightResult) or approved.ok is not True:
        raise PreflightError("a successful preflight result is required")
    if not isinstance(manifest, ExperimentManifest):
        raise PreflightError("a validated experiment manifest is required")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
        raise ValueError("timeout_seconds must be positive")
    if not math.isfinite(float(timeout_seconds)) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    executable = approved.terminal_executable.resolve(strict=False)
    data_dir = approved.terminal_data_dir.resolve(strict=False)
    if not executable.is_file():
        raise PreflightError("approved isolated terminal is unavailable")
    if not data_dir.is_dir() or not _same_path(data_dir, executable.parent):
        raise PreflightError("approved portable data directory is unavailable or unbound")
    config = Path(config_path)
    if not config.is_absolute() or not config.is_file():
        raise PreflightError("tester config must be an existing absolute file")
    config = config.resolve()
    _validate_tester_config(config, manifest)
    expert_binary = data_dir / "MQL5" / "Experts" / f"{manifest.expert_name}.ex5"
    if not expert_binary.is_file():
        raise PreflightError("preregistered expert binary is unavailable")
    if _sha256_file(expert_binary) != manifest.expert_sha256:
        raise PreflightError("preregistered expert binary hash mismatch")
    command = [str(executable), "/portable", f"/config:{config}"]
    return runner(
        command,
        shell=False,
        timeout=float(timeout_seconds),
        capture_output=True,
        text=True,
        creationflags=BELOW_NORMAL_PRIORITY_CLASS,
        cwd=str(data_dir),
        check=False,
    )


class ReportValidationError(ValueError):
    pass


@dataclass(frozen=True)
class NativeDeal:
    timestamp: datetime
    profit: float
    commission: float
    swap: float

    @property
    def net(self) -> float:
        return self.profit + self.commission + self.swap


@dataclass(frozen=True)
class NativeReport:
    path: Path
    sha256: str
    metadata: Mapping[str, str]
    parameters: Mapping[str, str]
    metrics: Mapping[str, float]
    deals: tuple[NativeDeal, ...]


def _decode_report(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "utf-16-le", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ReportValidationError("native report encoding is unsupported")


def _normalized_label(value: str) -> str:
    normalized = value.strip().lower().rstrip(":")
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized)
    return normalized.strip("_")


def _parse_local_number(value: object, field: str) -> float:
    text = str(value).strip().replace("\u00a0", "").replace(" ", "")
    if text.endswith("%"):
        text = text[:-1]
    if not text:
        raise ReportValidationError(f"{field} is empty")
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        number = float(text)
    except ValueError as exc:
        raise ReportValidationError(f"{field} is not a locale-aware number") from exc
    if not math.isfinite(number):
        raise ReportValidationError(f"{field} is not finite")
    return number


def _parse_deal_timestamp(value: str) -> datetime:
    text = value.strip()
    for pattern in ("%Y.%m.%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y.%m.%d %H:%M"):
        try:
            return datetime.strptime(text, pattern)
        except ValueError:
            pass
    raise ReportValidationError(f"unsupported deal timestamp: {value}")


def _parse_parameters_text(value: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for entry in value.replace("\r", ";").replace("\n", ";").split(";"):
        entry = entry.strip()
        if not entry:
            continue
        if "=" not in entry:
            raise ReportValidationError("native input parameters are malformed")
        key, raw_value = entry.split("=", 1)
        key = key.strip()
        if not _SAFE_KEY.fullmatch(key):
            raise ReportValidationError("native input parameter name is unsafe")
        result[key] = raw_value.strip()
    return result


class _ReportHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        if lowered in {"script", "style"}:
            self._skip_depth += 1
        elif lowered == "tr":
            self._row = []
        elif lowered in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in {"script", "style"} and self._skip_depth:
            self._skip_depth -= 1
        elif lowered in {"td", "th"} and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif lowered == "tr" and self._row is not None:
            if any(cell for cell in self._row):
                self.rows.append(self._row)
            self._row = None


_META_ALIASES = {
    "symbol": "symbol",
    "symbole": "symbol",
    "period": "period",
    "periode": "period",
    "model": "model",
    "modele": "model",
    "expert": "expert",
    "advisor": "expert",
    "from": "from",
    "de": "from",
    "to": "to",
    "a": "to",
    "inputs": "inputs",
    "parametres": "inputs",
}
_DEAL_HEADER_ALIASES = {
    "time": "time",
    "heure": "time",
    "profit": "profit",
    "commission": "commission",
    "swap": "swap",
}


def _parse_xml_report(text: str) -> tuple[dict[str, str], dict[str, str], dict[str, float], tuple[NativeDeal, ...]]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ReportValidationError("native XML report is malformed") from exc
    meta_node = root.find(".//meta")
    if meta_node is None:
        raise ReportValidationError("native XML report has no meta element")
    metadata = {key: str(value) for key, value in meta_node.attrib.items()}
    parameters: dict[str, str] = {}
    for node in root.findall(".//parameters/parameter"):
        name = node.attrib.get("name")
        value = node.attrib.get("value")
        if not name or value is None or not _SAFE_KEY.fullmatch(name):
            raise ReportValidationError("native XML parameter is malformed")
        parameters[name] = value
    metrics: dict[str, float] = {}
    for node in root.findall(".//metrics/metric"):
        name = node.attrib.get("name")
        value = node.attrib.get("value")
        if not name or value is None:
            raise ReportValidationError("native XML metric is malformed")
        metrics[_normalized_label(name)] = _parse_local_number(value, name)
    deals: list[NativeDeal] = []
    for node in root.findall(".//deals/deal"):
        required = {"time", "profit", "commission", "swap"}
        if not required.issubset(node.attrib):
            raise ReportValidationError("native XML deal is incomplete")
        deals.append(
            NativeDeal(
                _parse_deal_timestamp(node.attrib["time"]),
                _parse_local_number(node.attrib["profit"], "deal.profit"),
                _parse_local_number(node.attrib["commission"], "deal.commission"),
                _parse_local_number(node.attrib["swap"], "deal.swap"),
            )
        )
    return metadata, parameters, metrics, tuple(deals)


def _parse_html_report(text: str) -> tuple[dict[str, str], dict[str, str], dict[str, float], tuple[NativeDeal, ...]]:
    parser = _ReportHTMLParser()
    parser.feed(text)
    metadata: dict[str, str] = {}
    parameters: dict[str, str] = {}
    metrics: dict[str, float] = {}
    deals: list[NativeDeal] = []
    deal_columns: dict[str, int] | None = None
    for row in parser.rows:
        normalized = [_normalized_label(cell) for cell in row]
        mapped_headers = [_DEAL_HEADER_ALIASES.get(cell) for cell in normalized]
        if {"time", "profit", "commission", "swap"}.issubset(item for item in mapped_headers if item):
            deal_columns = {name: mapped_headers.index(name) for name in ("time", "profit", "commission", "swap")}
            continue
        if deal_columns is not None and len(row) > max(deal_columns.values()):
            try:
                deals.append(
                    NativeDeal(
                        _parse_deal_timestamp(row[deal_columns["time"]]),
                        _parse_local_number(row[deal_columns["profit"]], "deal.profit"),
                        _parse_local_number(row[deal_columns["commission"]], "deal.commission"),
                        _parse_local_number(row[deal_columns["swap"]], "deal.swap"),
                    )
                )
                continue
            except ReportValidationError as exc:
                raise ReportValidationError("native HTML deal row is malformed") from exc
        if len(row) != 2:
            continue
        label = _normalized_label(row[0])
        meta_name = _META_ALIASES.get(label)
        if meta_name == "inputs":
            parameters.update(_parse_parameters_text(row[1]))
        elif meta_name:
            metadata[meta_name] = row[1].strip()
        else:
            try:
                metrics[label] = _parse_local_number(row[1], label)
            except ReportValidationError:
                continue
    return metadata, parameters, metrics, tuple(deals)


def _normalized_expected_parameter(value: object) -> str:
    return _format_ini_value(value).strip().lower()


def _validate_native_report(
    metadata: Mapping[str, str],
    parameters: Mapping[str, str],
    expected: Mapping[str, object],
) -> None:
    required = {"symbol", "period", "model", "expert", "from", "to", "parameters"}
    missing_expected = required - set(expected)
    if missing_expected:
        raise ReportValidationError(f"expected report contract is incomplete: {sorted(missing_expected)}")
    for field in ("symbol", "period", "model", "expert", "from", "to"):
        actual = metadata.get(field)
        if actual is None:
            raise ReportValidationError(f"native report is missing {field}")
        if str(actual).strip().lower() != str(expected[field]).strip().lower():
            raise ReportValidationError(f"native report {field} mismatch")
    expected_parameters = expected["parameters"]
    if not isinstance(expected_parameters, Mapping):
        raise ReportValidationError("expected parameters must be an object")
    if set(parameters) != set(expected_parameters):
        raise ReportValidationError("native report parameter set mismatch")
    for key, value in expected_parameters.items():
        if parameters[key].strip().lower() != _normalized_expected_parameter(value):
            raise ReportValidationError(f"native report parameter mismatch: {key}")


def parse_native_report(path: Path | str, expected: Mapping[str, object]) -> NativeReport:
    source = Path(path)
    raw = source.read_bytes()
    if not raw:
        raise ReportValidationError("native report is empty")
    text = _decode_report(raw)
    prefix = text.lstrip()[:100].lower()
    if "<html" in prefix or "<!doctype html" in prefix:
        metadata, parameters, metrics, deals = _parse_html_report(text)
    else:
        metadata, parameters, metrics, deals = _parse_xml_report(text)
    _validate_native_report(metadata, parameters, expected)
    return NativeReport(source.resolve(), hashlib.sha256(raw).hexdigest(), metadata, parameters, metrics, deals)


def daily_net_returns(deals: Sequence[NativeDeal], initial_deposit: float) -> dict[str, float]:
    deposit = _require_finite_number(initial_deposit, "initial_deposit", positive=True)
    totals: dict[str, float] = {}
    for deal in deals:
        day = deal.timestamp.date().isoformat()
        totals[day] = totals.get(day, 0.0) + deal.net
    return {day: totals[day] / deposit for day in sorted(totals)}


def align_daily_returns(series: Mapping[str, Mapping[str, float]]) -> dict[str, tuple[float, ...]]:
    if not series:
        return {}
    all_days = sorted({day for candidate in series.values() for day in candidate})
    return {
        name: tuple(float(candidate.get(day, 0.0)) for day in all_days)
        for name, candidate in series.items()
    }


def _report_expectation(manifest: ExperimentManifest, candidate: str, segment: str) -> dict[str, object]:
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


def evaluate_native_run(
    manifest: ExperimentManifest,
    reports: Mapping[str, Mapping[str, Path | str]],
) -> dict[str, object]:
    from validation.harness import Segment, ValidationPlan, run_validation

    parsed: dict[str, dict[str, NativeReport]] = {}
    for candidate in manifest.candidates:
        candidate_paths = reports.get(candidate, {})
        parsed[candidate] = {}
        for segment in ("dev", "selection"):
            path = candidate_paths.get(segment)
            if path is None:
                raise ReportValidationError(f"missing {segment} report for {candidate}")
            parsed[candidate][segment] = parse_native_report(
                path,
                _report_expectation(manifest, candidate, segment),
            )

    aligned: dict[str, dict[str, tuple[float, ...]]] = {}
    for segment in ("dev", "selection"):
        aligned[segment] = align_daily_returns(
            {
                candidate: daily_net_returns(parsed[candidate][segment].deals, manifest.deposit)
                for candidate in manifest.candidates
            }
        )

    validation_plan = ValidationPlan(
        dev=Segment("dev", manifest.segments["dev"].start, manifest.segments["dev"].end),
        selection=Segment(
            "selection", manifest.segments["selection"].start, manifest.segments["selection"].end
        ),
        final=Segment("final", manifest.segments["final"].start, manifest.segments["final"].end),
        experiment={"native_manifest_hash": manifest.preregistration_hash},
        block_length=int(json.loads(manifest.canonical_json)["block_length"]),
        bootstrap_replications=int(json.loads(manifest.canonical_json)["bootstrap_replications"]),
        bootstrap_seed=int(json.loads(manifest.canonical_json)["bootstrap_seed"]),
    )

    def evaluator(candidate: str, segment: Any) -> object:
        if segment.name in aligned:
            native = parsed[candidate][segment.name]
            trade_returns = tuple(deal.net / manifest.deposit for deal in native.deals)
            return {
                "returns": aligned[segment.name][candidate],
                "trade_returns": trade_returns,
                "trade_count": len(trade_returns),
            }
        final_path = reports.get(candidate, {}).get("final")
        if final_path is None:
            raise ReportValidationError(f"missing final report for selected candidate {candidate}")
        report = parse_native_report(
            final_path,
            _report_expectation(manifest, candidate, "final"),
        )
        parsed[candidate]["final"] = report
        final_series = daily_net_returns(report.deals, manifest.deposit)
        trade_returns = tuple(deal.net / manifest.deposit for deal in report.deals)
        return {
            "returns": tuple(final_series[day] for day in sorted(final_series)),
            "trade_returns": trade_returns,
            "trade_count": len(trade_returns),
        }

    report = run_validation(
        {candidate: candidate for candidate in manifest.candidates},
        validation_plan,
        evaluator,
    )
    result = report.to_dict()
    result["native_preregistration_hash"] = manifest.preregistration_hash
    result["native_reports"] = {
        candidate: {
            segment: {
                "sha256": native.sha256,
                "metrics": dict(native.metrics),
                "path": str(native.path),
            }
            for segment, native in candidate_reports.items()
        }
        for candidate, candidate_reports in parsed.items()
    }
    return result


def _load_json_object(path: Path | str) -> Mapping[str, object]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fail-closed native MT5 tester runner (paper only)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser("prepare", help="validate a manifest and create immutable run artifacts")
    prepare_parser.add_argument("manifest")
    prepare_parser.add_argument("--runs-root", default="validation/runs")

    status_parser = subparsers.add_parser("status", help="show an existing run state")
    status_parser.add_argument("run_dir")

    parse_parser = subparsers.add_parser("parse", help="parse and validate one native report")
    parse_parser.add_argument("report")
    parse_parser.add_argument("--expected", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_cli().parse_args(argv)
    if args.command == "prepare":
        manifest = ExperimentManifest.from_mapping(_load_json_object(args.manifest))
        run_dir = prepare_run(manifest, args.runs_root)
        print(_canonical_json({"run_dir": str(run_dir.resolve()), "state": RunState.PLANNED.value}))
        return 0
    if args.command == "status":
        print(_canonical_json(RunStateStore(Path(args.run_dir) / "state.json").read()))
        return 0
    if args.command == "parse":
        report = parse_native_report(args.report, _load_json_object(args.expected))
        print(
            _canonical_json(
                {
                    "sha256": report.sha256,
                    "metadata": report.metadata,
                    "parameters": report.parameters,
                    "metrics": report.metrics,
                    "deals": len(report.deals),
                }
            )
        )
        return 0
    raise AssertionError("unreachable CLI command")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
