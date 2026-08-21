"""Read-only readiness rehearsal for the frozen V8 forward holdout.

This module deliberately writes no holdout journal evidence and places no
brokerage orders. It validates the frozen contract, confirms the 100-stock
universe plus SPY feature inputs exist, checks cross-sectional feature-date
alignment, and proves the latest common completed session can be ranked by the
same frozen V8 logic used by the holdout runner.

Gold may advance symbol-by-symbol while the Tiingo EOD refresh is still catching
up. That partial Gold progress must not make the frozen V8 universe look stale as
long as the complete, aligned feature universe is current through the latest
Gold date shared by all required symbols. V8 decisions are universe-level, so
readiness is evaluated against common-session coverage rather than the newest
individual Gold file.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import pandas as pd

from ml.v8.holdout_runner import (
    EXPECTED_SHA,
    HOLDOUT_START,
    _feature_files,
    _load_market,
    _rank_for_date,
    _universe,
    _verify_freeze,
)

READINESS_ROOT = Path("data/model/v8/readiness")
STATUS_PATH = READINESS_ROOT / "status.json"
GOLD_ROOT = Path("data/gold/stocks")


def _latest_timestamp(path: Path, candidates=("timestamp_utc", "timestamp")):
    if not path.exists() or path.stat().st_size == 0:
        return None
    df = pd.read_parquet(path)
    col = next((c for c in candidates if c in df.columns), None)
    if col is None or df.empty:
        return None
    values = pd.to_datetime(df[col], utc=True, errors="coerce").dropna()
    return values.max() if not values.empty else None


def _write_status(payload):
    READINESS_ROOT.mkdir(parents=True, exist_ok=True)
    out = dict(payload)
    out["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    out["frozen_sha256"] = EXPECTED_SHA
    out["holdout_start_utc"] = HOLDOUT_START.isoformat()
    out["journal_written"] = False
    out["brokerage_orders"] = False
    temp = STATUS_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    temp.replace(STATUS_PATH)
    return out


def run_readiness_check():
    failures = []
    warnings = []

    _verify_freeze()
    symbols = _universe()
    required = symbols + ["SPY"]

    files = _feature_files()
    missing_features = sorted(set(required) - set(files))
    if missing_features:
        failures.append("missing_feature_files")

    feature_latest = {}
    for symbol in required:
        path = files.get(symbol)
        if path is None:
            continue
        feature_latest[symbol] = _latest_timestamp(path)

    unusable_features = sorted(s for s in required if feature_latest.get(s) is None)
    if unusable_features:
        failures.append("empty_or_unreadable_feature_files")

    valid_feature_dates = [ts for ts in feature_latest.values() if ts is not None]
    feature_common_latest = min(valid_feature_dates) if valid_feature_dates else None
    feature_max_latest = max(valid_feature_dates) if valid_feature_dates else None
    feature_lagging = sorted(
        s for s, ts in feature_latest.items()
        if feature_max_latest is not None and ts is not None and ts < feature_max_latest
    )
    if feature_lagging:
        failures.append("feature_dates_not_aligned")

    gold_latest = {}
    for symbol in required:
        p = GOLD_ROOT / symbol / f"{symbol}_prices.parquet"
        gold_latest[symbol] = _latest_timestamp(p)

    valid_gold_dates = [ts for ts in gold_latest.values() if ts is not None]
    gold_common_latest = min(valid_gold_dates) if valid_gold_dates else None
    gold_max_latest = max(valid_gold_dates) if valid_gold_dates else None
    missing_gold = sorted(s for s in required if gold_latest.get(s) is None)
    if missing_gold:
        warnings.append("missing_gold_files")

    # Gold is intentionally propagated symbol-by-symbol during an incremental
    # Tiingo catch-up, while feature generation waits for the whole 101-symbol
    # universe. Therefore individual Gold files may be one session ahead of the
    # aligned feature universe for a short period. That is expected and must not
    # fail V8 readiness. Fail only when the complete feature universe is behind
    # the latest session that *all* required Gold symbols share.
    feature_behind_gold = sorted(
        s for s in required
        if feature_latest.get(s) is not None
        and gold_latest.get(s) is not None
        and feature_latest[s] < gold_latest[s]
    )
    gold_ahead_partial = bool(feature_behind_gold)
    if (
        feature_common_latest is not None
        and gold_common_latest is not None
        and feature_common_latest < gold_common_latest
    ):
        failures.append("features_behind_common_gold")
    elif gold_ahead_partial:
        warnings.append("partial_gold_ahead_of_features")

    ranking = None
    eligible_count = 0
    top10 = []
    top10_details = []
    ranking_timestamp = None

    if not failures:
        loaded_symbols, frames, trading_dates, _ = _load_market()
        if len(loaded_symbols) != 100:
            failures.append("unexpected_universe_size")
        elif not trading_dates:
            failures.append("missing_spy_trading_calendar")
        else:
            # Rank on the latest session available across the complete feature
            # universe. This is the only safe timestamp for a cross-sectional
            # decision while an EOD refresh is partially propagated in Gold.
            ranking_timestamp = min(
                frame.index[frame["close"].notna()].max()
                for frame in frames.values()
            )
            ranking = _rank_for_date(ranking_timestamp, loaded_symbols, frames)
            eligible_count = len(ranking)
            top = ranking.head(10)
            top10 = top["symbol"].tolist()
            top10_details = [
                {
                    "rank": i + 1,
                    "symbol": str(row.symbol),
                    "score": float(row.orthogonal_signal),
                    "selected_top10": True,
                    "target_weight": 0.10,
                }
                for i, row in enumerate(top.itertuples(index=False))
            ]
            if eligible_count < 80:
                failures.append("insufficient_rankable_universe")

    status = "READY" if not failures else "NOT_READY"
    payload = {
        "status": status,
        "checks": {
            "frozen_contract_verified": True,
            "expected_universe_size": 100,
            "universe_size": len(symbols),
            "required_feature_files": len(required),
            "feature_files_found": len(files),
            "missing_feature_symbols": missing_features,
            "unusable_feature_symbols": unusable_features,
            "feature_common_latest_utc": feature_common_latest.isoformat() if feature_common_latest is not None else None,
            "feature_max_latest_utc": feature_max_latest.isoformat() if feature_max_latest is not None else None,
            "feature_lagging_symbols": feature_lagging,
            "gold_common_latest_utc": gold_common_latest.isoformat() if gold_common_latest is not None else None,
            "gold_max_latest_utc": gold_max_latest.isoformat() if gold_max_latest is not None else None,
            "missing_gold_symbols": missing_gold,
            "feature_symbols_behind_gold": feature_behind_gold,
            "partial_gold_ahead_of_features": gold_ahead_partial,
            "ranking_timestamp_utc": ranking_timestamp.isoformat() if ranking_timestamp is not None else None,
            "ranking_eligible_count": eligible_count,
            "ranking_top10": top10,
            "ranking_top10_details": top10_details,
        },
        "failures": sorted(set(failures)),
        "warnings": sorted(set(warnings)),
    }
    return _write_status(payload)


def main():
    print("V8 FORWARD READINESS REHEARSAL")
    print("=" * 88)
    try:
        result = run_readiness_check()
    except Exception as exc:
        result = _write_status({
            "status": "NOT_READY",
            "checks": {},
            "failures": [f"{type(exc).__name__}: {exc}"],
            "warnings": [],
        })

    print(f"Status: {result['status']}")
    print(f"Frozen SHA: {result['frozen_sha256']}")
    checks = result.get("checks", {})
    if checks:
        print(f"Universe: {checks.get('universe_size')}/100 stocks + SPY")
        print(f"Feature common latest: {checks.get('feature_common_latest_utc')}")
        print(f"Gold common latest:    {checks.get('gold_common_latest_utc')}")
        print(f"Gold max latest:       {checks.get('gold_max_latest_utc')}")
        print(f"Ranking timestamp:     {checks.get('ranking_timestamp_utc')}")
        print(f"Eligible names:        {checks.get('ranking_eligible_count')}")
        if checks.get("ranking_top10"):
            print("Top 10 rehearsal:      " + ", ".join(checks["ranking_top10"]))
    if result.get("failures"):
        print("Failures:")
        for item in result["failures"]:
            print(f"  - {item}")
    if result.get("warnings"):
        print("Warnings:")
        for item in result["warnings"]:
            print(f"  - {item}")
    print("No holdout journal evidence written. No brokerage orders.")

    raise SystemExit(0 if result["status"] == "READY" else 2)


if __name__ == "__main__":
    main()
