"""
Run the daily V4 paper-trading pipeline.

Workflow:
  1. Refresh Tiingo market data
  2. Rebuild Silver layer
  3. Rebuild Gold layer
  4. Rebuild feature layer
  5. Run one V4 paper-trading cycle

Important:
  - Does NOT retrain V4
  - Does NOT rebuild the V4 training dataset
  - Simulation only
"""

from pathlib import Path
import subprocess
import sys
import time


PROJECT_ROOT = Path(__file__).resolve().parents[1]


STAGES = [
    (
        "Tiingo ingestion",
        [
            sys.executable,
            "data-ingestion/tiingo_multi_ingest.py",
        ],
    ),
    (
        "SPY core ingestion",
        [
            sys.executable,
            "data-ingestion/tiingo_core_ingest.py",
        ],
    ),
    (
        "Silver pipeline",
        [
            sys.executable,
            "data-ingestion/silver_pipeline.py",
        ],
    ),
    (
        "Gold pipeline",
        [
            sys.executable,
            "data-ingestion/gold_pipeline.py",
        ],
    ),
    (
        "Feature pipeline",
        [
            sys.executable,
            "data-ingestion/feature_pipeline.py",
        ],
    ),
    (
        "V4 paper cycle",
        [
            sys.executable,
            "ml/run_paper_cycle_v4.py",
        ],
    ),
]


def run_stage(
    name,
    command,
):
    print()
    print("=" * 64)
    print(name.upper())
    print("=" * 64)

    started = time.time()

    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
    )

    elapsed = (
        time.time()
        - started
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"{name} failed "
            f"with exit code "
            f"{result.returncode}"
        )

    print()
    print(
        f"[SUCCESS] {name} "
        f"({elapsed:.1f}s)"
    )


def main():
    print()
    print("DAILY V4 PAPER-TRADING PIPELINE")
    print("=" * 64)

    started = time.time()

    for name, command in STAGES:
        run_stage(
            name,
            command,
        )

    elapsed = (
        time.time()
        - started
    )

    print()
    print("=" * 64)
    print("DAILY PIPELINE COMPLETE")
    print("=" * 64)

    print(
        f"Total runtime: "
        f"{elapsed:.1f}s"
    )

    print()
    print(
        "V4 model remains frozen."
    )

    print(
        "Paper-trading state updated "
        "only if rankings required a rebalance."
    )


if __name__ == "__main__":
    main()
