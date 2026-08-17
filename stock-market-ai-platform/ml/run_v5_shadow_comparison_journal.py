"""Append one read-only V4 vs V5 vs SPY comparison observation."""

import json
from webapp.services.v5_shadow_comparison_journal_service import append_comparison_observation


def main():
    result = append_comparison_observation(skip_duplicate_quotes=True)
    print("V4 / V5 / SPY SHADOW COMPARISON JOURNAL")
    print("=" * 72)
    print(json.dumps(result, indent=2, sort_keys=True))
    print("Diagnostic only. Official Sep 1+ V5 holdout remains untouched.")
    print("No V4 state changes and no brokerage orders.")


if __name__ == "__main__":
    main()
