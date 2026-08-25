"""Fail-closed regression for the scheduled stock refresh health contract.

Run after the refresh scheduler has completed. This check is read-only: it does
not refresh data, mutate holdout evidence, or invoke any brokerage interface.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HEALTH_PATH = PROJECT_ROOT / "webapp/static/generated/stock_operations_health.json"
CONVERGENCE_PATH = PROJECT_ROOT / "webapp/static/generated/stock_data_convergence.json"
ACTIVE_ERROR_LOGS = (
    PROJECT_ROOT / "logs/v8_refresh.err.log",
    PROJECT_ROOT / "logs/v5_refresh.err.log",
)
EXPECTED_SYMBOLS = 101
EXPECTED_BACKEND = "spark"
EXPECTED_VERIFICATION = "END_TO_END_READY_VERIFIED"

_SECRET_QUERY_PATTERN = re.compile(
    r"(?i)(?:[?&]|\b)(?:token|api[_-]?key|apikey|access[_-]?token)="
    r"[^\s&\"'<>]+"
)


def require(value: bool, label: str) -> None:
    if not value:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def load_json(path: Path) -> dict:
    if not path.exists():
        raise AssertionError(f"Required artifact is absent: {path.relative_to(PROJECT_ROOT)}")
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise AssertionError(
            f"Required artifact is unreadable: {path.relative_to(PROJECT_ROOT)}"
        ) from exc
    if not isinstance(payload, dict):
        raise AssertionError(
            f"Required artifact is not a JSON object: {path.relative_to(PROJECT_ROOT)}"
        )
    return payload


def active_logs_are_secret_free() -> bool:
    configured_secret = os.environ.get("TIINGO_API_KEY", "").strip()
    for path in ACTIVE_ERROR_LOGS:
        if not path.exists():
            continue
        try:
            text = path.read_text(errors="replace")
        except OSError:
            return False
        if _SECRET_QUERY_PATTERN.search(text):
            return False
        if configured_secret and configured_secret in text:
            return False
    return True


def main() -> None:
    health = load_json(HEALTH_PATH)
    convergence = load_json(CONVERGENCE_PATH)

    scheduler = health.get("scheduler") or {}
    features = health.get("features") or {}
    health_convergence = health.get("convergence") or {}
    v8 = health.get("v8") or {}
    safety = health.get("safety") or {}
    layers = convergence.get("layers") or {}
    feature_layer = layers.get("features") or {}

    require(
        scheduler.get("status") == "HEALTHY"
        and scheduler.get("last_exit_code") == 0,
        "Scheduler is healthy with exit code 0",
    )
    require(
        features.get("backend") == EXPECTED_BACKEND
        and convergence.get("feature_backend") == EXPECTED_BACKEND
        and feature_layer.get("backend") == EXPECTED_BACKEND,
        "Runtime, convergence and feature layer all use Spark",
    )
    require(
        features.get("files_found") == EXPECTED_SYMBOLS
        and features.get("expected_files") == EXPECTED_SYMBOLS
        and feature_layer.get("symbols_at_target") == EXPECTED_SYMBOLS
        and feature_layer.get("symbols_expected") == EXPECTED_SYMBOLS,
        "Spark feature coverage is 101/101 at the target session",
    )
    require(
        convergence.get("status") == "DATA_CONVERGED"
        and convergence.get("data_converged") is True
        and health_convergence.get("status") == "DATA_CONVERGED"
        and health_convergence.get("data_converged") is True,
        "Published convergence state is DATA_CONVERGED",
    )
    require(
        convergence.get("verification") == EXPECTED_VERIFICATION
        and health_convergence.get("verification") == EXPECTED_VERIFICATION,
        "End-to-end readiness is verified",
    )
    require(
        convergence.get("safety_violation") is False
        and health_convergence.get("safety_violation") is False,
        "No convergence safety violation is active",
    )
    require(
        convergence.get("v8_decision_gate_open") is True
        and convergence.get("v8_ranking_matches_target") is True
        and v8.get("guard_status") == "READY"
        and v8.get("decision_gate_open") is True
        and v8.get("ranking_timestamp_utc")
        == convergence.get("target_session_utc"),
        "V8 gate and ranking timestamp match the converged target",
    )
    require(
        scheduler.get("real_orders") is False
        and safety.get("brokerage_orders") is False,
        "Brokerage orders remain off",
    )
    require(
        active_logs_are_secret_free(),
        "Active refresh error logs contain no credential-bearing query strings",
    )

    print("\nStatus: PASSED")
    print("Scheduled refresh contract: VERIFIED")
    print("Feature backend: SPARK")
    print("Coverage: 101/101")
    print("Credential logging: NOT DETECTED")
    print("Production evidence modified: NO")
    print("Brokerage orders: OFF")


if __name__ == "__main__":
    main()
