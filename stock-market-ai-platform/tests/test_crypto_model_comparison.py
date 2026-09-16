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


def test_v5_parquet_contract_filters_selected_ridge_candidate(tmp_path):
    path = tmp_path / "v5_periods.parquet"
    pd.DataFrame({
        "timestamp_utc": ["2023-01-01T00:00:00Z", "2023-01-04T00:00:00Z",
                          "2023-01-01T00:00:00Z", "2023-01-04T00:00:00Z"],
        "model_id": ["ridge", "ridge", "hist_gradient_boosting", "hist_gradient_boosting"],
        "horizon_days": [3, 3, 3, 3], "top_n": [3, 3, 3, 3],
        "cost_bps_round_trip": [25.0] * 4,
        "ending_equity": [1.0, 1.1, 1.0, 1.5],
    }).to_parquet(path, index=False)
    spec = StrategySpec("CRYPTO_V5", "Crypto V5", path, "", "timestamp_utc",
                        "ending_equity", model_filter="ridge", horizon_days=3,
                        top_n=3, observation_interval_days=3.0)
    payload = build_payload((spec,))
    assert [row["model_id"] for row in payload["series"]] == ["CRYPTO_V5"]
    assert payload["series"][0]["ending_equity"] == 110000.0
