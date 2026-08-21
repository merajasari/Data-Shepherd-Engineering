"""Fail-closed V8 EOD orchestration guard.

This module does not download market data and does not place orders. It is the
final gate after the existing EOD refresh pipeline has propagated Bronze ->
Silver -> Gold -> Features. It verifies that the frozen V8 universe has one
common feature session, runs the canonical V8 readiness check, publishes a
small dashboard status artifact, and returns a non-zero exit code whenever a
production V8 decision must not proceed.

The guard deliberately tolerates partial Gold files being one session ahead of
the common feature session; that is the normal incremental catch-up state. It
fails closed if the common Gold session is ahead of the common feature session,
if feature dates are misaligned, if the rankable universe is incomplete, or if
any frozen-contract readiness check fails.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from ml.v8.readiness_check import run_readiness_check

STATUS_PATH = Path("data/model/v8/eod_guard/status.json")
WEB_STATUS_PATH = Path("webapp/static/generated/v8_eod_guard.json")


def _write(payload):
    out = dict(payload)
    out["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    WEB_STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(out, indent=2, sort_keys=True) + "\n"
    tmp = STATUS_PATH.with_suffix(".tmp")
    tmp.write_text(text)
    tmp.replace(STATUS_PATH)
    web_tmp = WEB_STATUS_PATH.with_suffix(".tmp")
    web_tmp.write_text(text)
    web_tmp.replace(WEB_STATUS_PATH)
    return out


def run_guard():
    readiness = run_readiness_check()
    checks = readiness.get("checks") or {}
    failures = list(readiness.get("failures") or [])
    warnings = list(readiness.get("warnings") or [])

    feature_common = checks.get("feature_common_latest_utc")
    gold_common = checks.get("gold_common_latest_utc")
    feature_max = checks.get("feature_max_latest_utc")
    gold_max = checks.get("gold_max_latest_utc")
    eligible = int(checks.get("ranking_eligible_count") or 0)
    universe = int(checks.get("universe_size") or 0)

    guard_failures = []
    if readiness.get("status") != "READY":
        guard_failures.append("canonical_readiness_not_ready")
    if universe != 100:
        guard_failures.append("universe_not_100")
    if eligible != 100:
        guard_failures.append("rankable_universe_not_100")
    if not feature_common:
        guard_failures.append("missing_common_feature_session")
    if not gold_common:
        guard_failures.append("missing_common_gold_session")
    if feature_common and gold_common and feature_common < gold_common:
        guard_failures.append("common_features_behind_common_gold")
    if feature_common and feature_max and feature_common != feature_max:
        guard_failures.append("feature_sessions_not_aligned")

    status = "READY" if not guard_failures else "WAITING"
    return _write({
        "status": status,
        "decision_gate_open": status == "READY",
        "feature_common_latest_utc": feature_common,
        "feature_max_latest_utc": feature_max,
        "gold_common_latest_utc": gold_common,
        "gold_max_latest_utc": gold_max,
        "ranking_timestamp_utc": checks.get("ranking_timestamp_utc"),
        "ranking_eligible_count": eligible,
        "universe_size": universe,
        "top10": checks.get("ranking_top10") or [],
        "readiness_status": readiness.get("status"),
        "readiness_failures": failures,
        "readiness_warnings": warnings,
        "guard_failures": guard_failures,
        "partial_gold_ahead_of_features": bool(checks.get("partial_gold_ahead_of_features")),
        "brokerage_orders": False,
        "strategy_modified": False,
    })


def main():
    result = run_guard()
    print("V8 EOD ORCHESTRATION GUARD")
    print("=" * 88)
    print(f"Status: {result['status']}")
    print(f"Decision gate open: {result['decision_gate_open']}")
    print(f"Feature common: {result.get('feature_common_latest_utc')}")
    print(f"Gold common:    {result.get('gold_common_latest_utc')}")
    print(f"Gold max:       {result.get('gold_max_latest_utc')}")
    print(f"Eligible:       {result.get('ranking_eligible_count')}/100")
    if result.get("readiness_warnings"):
        print("Warnings:")
        for item in result["readiness_warnings"]:
            print(f"  - {item}")
    if result.get("guard_failures"):
        print("Gate closed:")
        for item in result["guard_failures"]:
            print(f"  - {item}")
    print("No brokerage orders. Frozen V8 strategy unchanged.")
    raise SystemExit(0 if result["status"] == "READY" else 2)


if __name__ == "__main__":
    main()
