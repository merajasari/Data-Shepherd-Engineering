"""Integrity regression for the V11 Phase 2 development reconstruction."""
from __future__ import annotations

import math
from pathlib import Path

from ml.v11.intraday_phase2_reconstruction import (
    OUTPUT_PATH,
    run,
)


def require(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def main() -> None:
    first = run(write=False)
    second = run(write=False)
    require(
        first["reconstruction_sha256"]
        == second["reconstruction_sha256"],
        "Reconstruction is deterministic",
    )
    require(
        first["status"] == "POST_HOC_DEVELOPMENT_RECONSTRUCTION",
        "Post-hoc development classification is explicit",
    )
    require(
        first["configuration"] == "MOMENTUM_BALANCED_6",
        "Locked Phase 2 configuration is reconstructed",
    )
    require(
        first["eligible_sessions"] >= 20,
        "Multiple historical development sessions are reconstructed",
    )
    history = first["history"]
    require(
        math.isclose(
            float(history[0]["equity"]),
            100_000.0,
            rel_tol=0,
            abs_tol=0.01,
        ),
        "Reconstruction starts at $100,000",
    )
    timestamps = [str(row["timestamp"]) for row in history]
    require(
        timestamps == sorted(timestamps),
        "Reconstruction history is chronological",
    )
    require(
        all(
            math.isfinite(float(row["equity"]))
            and float(row["equity"]) > 0
            for row in history
        ),
        "Every reconstructed equity value is finite and positive",
    )
    require(
        first["post_hoc_origin_disclosed"] is True
        and first["model_frozen"] is False,
        "Development evidence is not mislabeled frozen",
    )
    require(
        first["fresh_evidence_included"] is False
        and first["fresh_journal_read"] is False
        and first["holdout_outcomes_read"] is False,
        "Fresh evidence and holdout outcomes remain excluded",
    )
    require(
        first["paper_trading_only"] is True
        and first["live_trading_enabled"] is False
        and first["brokerage_orders"] is False,
        "Reconstruction has no live-trading authority",
    )
    require(
        first["v8_modified"] is False
        and first["v10_modified"] is False,
        "V8 and V10 remain isolated",
    )

    published = run(output_path=OUTPUT_PATH, write=True)
    require(
        Path(OUTPUT_PATH).exists()
        and published["reconstruction_sha256"]
        == first["reconstruction_sha256"],
        "SHA-identified reconstruction publishes atomically",
    )
    print("Status: PASSED")
    print("V11 Phase 2 development reconstruction: VERIFIED")
    print("Fresh evidence included: NO")
    print("Model frozen: NO")
    print("Brokerage orders: OFF")
    print("V8/V10 production evidence modified: NO")


if __name__ == "__main__":
    main()
