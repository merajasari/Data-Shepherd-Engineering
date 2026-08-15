"""Validate that the dashboard V5 view matches the production ranking artifact.

Read-only integrity check.  It does not fit models, modify artifacts, place
orders, or write holdout observations.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RANKINGS_PATH = PROJECT_ROOT / "data/live/v5_latest_rankings.json"


def main() -> None:
    if not RANKINGS_PATH.exists():
        raise SystemExit(f"Missing ranking artifact: {RANKINGS_PATH}")

    payload = json.loads(RANKINGS_PATH.read_text())
    rankings = payload.get("rankings", [])

    if len(rankings) != 100:
        raise SystemExit(f"Expected 100 rankings, found {len(rankings)}")

    ranks = [int(row["rank"]) for row in rankings]
    if ranks != list(range(1, 101)):
        raise SystemExit("Ranks are not exactly 1 through 100 in order")

    top5 = [row for row in rankings if row.get("selected_top5")]
    if len(top5) != 5 or [row["rank"] for row in top5] != [1, 2, 3, 4, 5]:
        raise SystemExit("Top-5 selection does not match ranks 1-5")

    scores = [float(row["predicted_relative_return_5d"]) for row in rankings]
    if scores != sorted(scores, reverse=True):
        raise SystemExit("Ranking scores are not sorted descending")

    decision_date = pd.Timestamp(payload["decision_date_utc"])
    if decision_date.tzinfo is None:
        decision_date = decision_date.tz_localize("UTC")
    else:
        decision_date = decision_date.tz_convert("UTC")

    mismatches = []
    for row in rankings:
        symbol = row["symbol"]
        path = PROJECT_ROOT / f"data/features/stocks/{symbol}/{symbol}_features.parquet"
        if not path.exists():
            mismatches.append(f"{symbol}: feature file missing")
            continue

        frame = pd.read_parquet(path, columns=["timestamp_utc", "close"])
        timestamps = pd.to_datetime(frame["timestamp_utc"], utc=True, errors="coerce")
        match = frame.loc[timestamps == decision_date]
        if match.empty:
            mismatches.append(f"{symbol}: decision date missing from features")
            continue

        feature_close = float(match.iloc[-1]["close"])
        artifact_close = float(row["close"])
        if abs(feature_close - artifact_close) > 1e-9:
            mismatches.append(
                f"{symbol}: artifact close={artifact_close} feature close={feature_close}"
            )

    if mismatches:
        raise SystemExit("Feature/artifact mismatches:\n" + "\n".join(mismatches))

    print("V5 DASHBOARD INTEGRITY: PASS")
    print(f"Decision date: {payload['decision_date_utc']}")
    print(f"Candidates: {len(rankings)}")
    print(f"Feature count: {payload.get('feature_count')}")
    print(f"Model: {payload.get('model_id')}")
    print("Top 5: " + ", ".join(row["symbol"] for row in rankings[:5]))
    print("Ranking order, Top-5 flags, and artifact closes match production features.")


if __name__ == "__main__":
    main()
