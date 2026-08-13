"""Run one frozen V5 forward/paper evaluation cycle.

Before the future holdout starts, the runner may score the latest snapshot for
plumbing verification but will not append a holdout observation. At/after
2026-09-01, it appends one immutable signal record per decision timestamp.
No brokerage orders are placed and no V4 paper-trading state is touched.
"""

from webapp.services.v5_forward_service import append_forward_signal, score_latest_snapshot


def main():
    scored = score_latest_snapshot()
    decision = scored["decision_timestamp"]

    print()
    print("V5 FORWARD / PAPER EVALUATION")
    print("=" * 56)
    print(f"Decision timestamp: {decision}")
    print("Frozen allocation: 60% SPY + 40% Top-5 (8% each)")
    print()
    print("Top 5:")
    for item in scored["top_five"]:
        print(
            f"  {item['rank']}. {item['symbol']:<6} "
            f"pred_rel_5d={item['predicted_relative_return_5d']:+.6f} "
            f"weight={item['target_weight']:.2%}"
        )

    result = append_forward_signal(scored)
    print()
    if result["written"]:
        print("Forward signal appended to isolated V5 journal.")
        print("Status: signal_recorded_unsettled")
    else:
        print(f"No journal write: {result['reason']}")
        if result["reason"] == "future_holdout_not_started":
            print("This is expected before 2026-09-01; the future holdout remains untouched.")


if __name__ == "__main__":
    main()
