"""Five-minute scheduler entrypoint for accelerated V10 paper evidence."""
from __future__ import annotations

from ml.v10.cycle3_accelerated_forward_runner import run_once


def main() -> None:
    result = run_once()
    print("V10 CYCLE 3 ACCELERATED SCHEDULED ENTRYPOINT")
    print("=" * 88)
    print(f"Status: {result['status']}")
    print(f"Journal events: {result['journal_events']}")
    print(f"Appended this run: {result['appended_this_run']}")
    print(
        "Completed five-sleeve blocks: "
        f"{result['promotion']['complete_five_sleeve_blocks']}"
    )
    print("Automatic promotion: NO | human review required: YES")
    print("Original January confirmation: UNCHANGED")
    print("V8 modified: NO | brokerage orders: OFF")
    if not result["promotion"]["operational_integrity"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
