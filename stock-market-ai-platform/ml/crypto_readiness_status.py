"""Publish the crypto forward-evaluation readiness audit as an atomic JSON snapshot.

This module reuses the validated ``ml.crypto_pre_holdout_readiness`` audit and
only serializes its result for dashboard presentation. It never fits a model,
changes policy state, writes evaluation observations, or places brokerage orders.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import pandas as pd

from ml.crypto_pre_holdout_readiness import HOLDOUT, run_audit

OUTPUT = Path("data/live/crypto_readiness/readiness_status.json")


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def publish() -> dict:
    audit = run_audit()
    now = pd.Timestamp(datetime.now(timezone.utc))
    failed = [row for row in audit.rows if not row["passed"]]
    payload = {
        "generated_at_utc": now.isoformat(),
        "status": "READY_FOR_FORWARD_EVALUATION" if audit.passed else "NOT_READY_FOR_FORWARD_EVALUATION",
        "ready": bool(audit.passed),
        "holdout_start_utc": HOLDOUT.isoformat(),
        "pre_holdout": bool(now < HOLDOUT),
        "total_checks": len(audit.rows),
        "passed_checks": sum(1 for row in audit.rows if row["passed"]),
        "failed_checks": len(failed),
        "failures": failed,
        "brokerage_orders": False,
        "note": "Read-only readiness snapshot generated from the canonical pre-holdout audit.",
    }
    _atomic_json(OUTPUT, payload)
    return payload


def main() -> None:
    payload = publish()
    print("CRYPTO FORWARD EVALUATION READINESS STATUS")
    print("=" * 88)
    print(f"Status:     {payload['status']}")
    print(f"Checks:     {payload['passed_checks']}/{payload['total_checks']} passed")
    print(f"Boundary:   {payload['holdout_start_utc']}")
    print(f"Real orders: {'YES' if payload['brokerage_orders'] else 'NO'}")
    if payload["failures"]:
        for row in payload["failures"]:
            print(f"FAIL: {row['name']} — {row['detail']}")
    raise SystemExit(0 if payload["ready"] else 1)


if __name__ == "__main__":
    main()
