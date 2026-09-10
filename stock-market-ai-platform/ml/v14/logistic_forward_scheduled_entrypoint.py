"""Safe scheduled entrypoint for the isolated V14 paper candidate."""
from __future__ import annotations

from ml.v14.logistic_forward import run_once


def main() -> None:
    result = run_once()
    print("V14 LOGISTIC PAPER-FORWARD SCHEDULED ENTRYPOINT")
    print("=" * 72)
    print(f"Status: {result['status']}")
    print(f"Decisions / entries / exits: {result['decisions']} / {result['entries']} / {result['completed_exits']}")
    print(f"Appended this run: {result.get('appended_this_run', 0)}")
    print("Paper trading only: YES")
    print("Brokerage orders: OFF")
    print("V8/V10 modified: NO")


if __name__ == "__main__":
    main()
