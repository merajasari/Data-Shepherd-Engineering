import json
from datetime import datetime, timezone

import pandas as pd

from ml.build_crypto_model_comparison import STARTING_CAPITAL, StrategySpec, build_payload


def test_rebases_and_calculates_metrics(tmp_path):
    path = tmp_path / "curve.csv"
    pd.DataFrame({
        "timestamp_utc": ["2016-09-15T00:00:00Z", "2017-09-15T00:00:00Z", "2018-09-15T00:00:00Z"],
        "variant": ["model"] * 3,
        "cost_bps_round_trip": [25.0] * 3,
        "equity": [1.0, 1.5, 1.2],
        "turnover": [1.0, 0.5, 0.5],
        "transaction_cost": [0.0025, 0.001, 0.001],
    }).to_csv(path, index=False)
    spec = StrategySpec("TEST", "Test", path, "model", "timestamp_utc", "equity")
    payload = build_payload((spec,), datetime(2026, 9, 15, tzinfo=timezone.utc))
    row = payload["series"][0]
    assert row["history"][0]["equity"] == STARTING_CAPITAL
    assert row["ending_equity"] == 120000.0
    assert abs(row["total_return_pct"] - 20.0) < 1e-9
    assert abs(row["max_drawdown_pct"] + 20.0) < 1e-9
    assert row["total_turnover"] == 2.0
    json.dumps(payload, allow_nan=False)


def test_missing_models_are_explicitly_unavailable(tmp_path):
    spec = StrategySpec("MISSING", "Missing", tmp_path / "no.csv", "model", "timestamp_utc", "equity")
    payload = build_payload((spec,))
    assert payload["series"] == []
    assert payload["unavailable_series"][0]["model_id"] == "MISSING"
    assert payload["research_safety"]["brokerage_orders"] is False
