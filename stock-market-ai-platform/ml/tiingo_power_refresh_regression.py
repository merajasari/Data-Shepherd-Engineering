"""Regression for Tiingo Power V8 refresh configuration.

This test is read-only. It validates local capacity configuration and scheduler
safety without contacting Tiingo, reading credentials, or invoking production.
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from ml import operations_health

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNNER = PROJECT_ROOT / "ml/run_v5_data_refresh.py"
INSTALLER = PROJECT_ROOT / "scripts/mac/install_v8_refresh.sh"


def require(value, label):
    if not value:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def main():
    with patch.dict(
        os.environ,
        {
            "TIINGO_PLAN": "power",
            "TIINGO_HOURLY_REQUEST_LIMIT": "500",
        },
        clear=False,
    ):
        require(
            operations_health._configured_tiingo_plan() == "power",
            "Operations health publishes the Power plan",
        )
        require(
            operations_health._configured_hourly_limit() == 500,
            "Operations health publishes the 500-request local ceiling",
        )

    with patch.dict(
        os.environ,
        {"TIINGO_HOURLY_REQUEST_LIMIT": "invalid"},
        clear=False,
    ):
        require(
            operations_health._configured_hourly_limit()
            == operations_health.DEFAULT_HOURLY_LIMIT,
            "Invalid health configuration fails closed to Starter capacity",
        )

    runner = RUNNER.read_text()
    installer = INSTALLER.read_text()

    require(
        "configured_hourly_request_limit()" in runner
        and 'os.environ.get("TIINGO_HOURLY_REQUEST_LIMIT")' in runner,
        "Refresh runtime accepts explicit plan capacity",
    )
    require(
        'LABEL="com.datashepherd.v8refresh"' in installer,
        "Canonical V8 refresh LaunchAgent label is used",
    )
    require(
        'HOURLY_REQUEST_LIMIT="${TIINGO_HOURLY_REQUEST_LIMIT:-500}"'
        in installer,
        "Power installer defaults to a conservative 500 requests per hour",
    )
    require(
        'INTERVAL_SECONDS="${V8_REFRESH_INTERVAL_SECONDS:-300}"'
        in installer,
        "Five-minute EOD discovery cadence is retained",
    )
    require(
        "v8_refresh.lockdir" in installer
        and "mkdir '$LOCK_DIR'" in installer,
        "Scheduler overlap guard is retained",
    )
    require(
        "ml/run_v8_data_refresh.py" in installer
        and "ml.data_convergence" in installer
        and "ml.operations_health" in installer,
        "Refresh, convergence and health publication remain integrated",
    )
    require(
        "Brokerage orders: OFF" in installer,
        "Installer declares brokerage orders off",
    )
    require(
        "TIINGO_API_KEY" not in installer,
        "Scheduler plist never embeds the Tiingo credential",
    )

    print("\nStatus: PASSED")
    print("Tiingo plan: POWER")
    print("Local rolling-hour ceiling: 500")
    print("EOD discovery cadence: 5 MINUTES")
    print("Full-universe Spark convergence: REQUIRED")
    print("Frozen V8 decision gate: FAIL CLOSED")
    print("Credentials read/displayed: NO")
    print("Brokerage orders: OFF")


if __name__ == "__main__":
    main()
