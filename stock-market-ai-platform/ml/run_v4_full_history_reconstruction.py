"""Build the full available V4 walk-forward equity history for dashboard display.

Research/display only. This does not place orders or modify paper journals.
The reconstruction delegates to the existing V4 walk-forward backtest so its
training, purge gap, ranking, execution and cost rules remain centralized.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ml.backtest_portfolio_v4 import run_backtest

OUTPUT_PATH = Path("data/model/v4/full_history_equity.json")


def _iso(value) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def main() -> None:
    result = run_backtest()
    curve = result.get("equity_curve", [])
    if not curve:
        raise RuntimeError("V4 walk-forward backtest returned no equity history")

    rows = [
        {
            "timestamp": _iso(timestamp),
            "equity": float(equity),
            "reconstructed": True,
            "history_type": "full_walk_forward_reconstruction",
            "source": "V4 causal walk-forward reconstruction",
        }
        for timestamp, equity in curve
    ]

    payload = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "starting_cash": float(result["starting_cash"]),
        "start_timestamp": rows[0]["timestamp"],
        "end_timestamp": rows[-1]["timestamp"],
        "observation_count": len(rows),
        "final_equity": float(result["final_equity"]),
        "total_return": float(result["total_return"]),
        "cagr": float(result["cagr"]),
        "max_drawdown": float(result["max_drawdown"]),
        "trade_count": int(result["trade_count"]),
        "history": rows,
        "methodology": {
            "model": "V4 cross-sectional ranking model",
            "validation": "expanding-window walk-forward with existing V4 purge gap",
            "execution": "existing V4 portfolio backtest execution rules",
            "costs": "existing V4 entry and exit cost assumptions",
            "paper_journal_modified": False,
            "brokerage_orders": False,
        },
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print("V4 FULL-HISTORY RECONSTRUCTION")
    print("=" * 72)
    print(f"Output:       {OUTPUT_PATH}")
    print(f"Start:        {payload['start_timestamp']}")
    print(f"End:          {payload['end_timestamp']}")
    print(f"Observations: {payload['observation_count']:,}")
    print(f"Final equity: ${payload['final_equity']:,.2f}")
    print("Research/display only; paper journal unchanged; no brokerage orders.")


if __name__ == "__main__":
    main()
