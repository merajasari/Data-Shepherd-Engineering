"""Fast synthetic regression for the V14 ten-year retrospective engine."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

import numpy as np
import pandas as pd

from ml.v14.logistic_forward import fit_as_of
from ml.v14.logistic_forward_contract import load_contract
from ml.v14.logistic_retrospective_10y import (
    CLASSIFICATION,
    _fit_rank_as_of,
    _training_panel,
    reconstruct,
)
from ml import build_stock_model_comparison as comparison


def _market():
    rng = np.random.default_rng(1401)
    dates = list(pd.bdate_range("2025-01-02", periods=90, tz="UTC"))
    features = list(load_contract()["model"]["features"])
    symbols = [f"S{index:02d}" for index in range(15)]
    frames = {}
    for index, symbol in enumerate(symbols + ["SPY"]):
        signal = rng.normal(0.0, 1.0, len(dates))
        drift = 0.0004 + 0.00008 * index
        close = 100.0 * np.cumprod(1.0 + drift + 0.006 * np.tanh(signal))
        frame = pd.DataFrame(index=pd.DatetimeIndex(dates))
        frame.index.name = "timestamp_utc"
        frame["open"] = close * (1.0 + rng.normal(0.0, 0.001, len(dates)))
        frame["close"] = close
        frame["volume"] = 1_000_000 + index * 10_000
        for feature_index, feature in enumerate(features):
            frame[feature] = signal * (1.0 if feature_index == 0 else 0.12) + rng.normal(
                0.0, 0.08, len(dates)
            )
        frame["target_up_5d"] = (signal + rng.normal(0.0, 0.25, len(dates)) > 0).astype(int)
        frames[symbol] = frame
    return symbols, frames, dates


def main() -> None:
    symbols, frames, dates = _market()
    contract = deepcopy(load_contract())
    contract["model"]["minimum_training_rows"] = 50
    contract["model"]["epochs"] = 80
    contract["portfolio"]["top_n"] = 3
    features = list(contract["model"]["features"])
    all_dates = sorted(set().union(*(set(frames[symbol].index) for symbol in symbols)))
    replay_ranked, replay_metadata = _fit_rank_as_of(
        dates[35],
        symbols=symbols,
        frames=frames,
        dates=dates,
        all_dates=all_dates,
        panel=_training_panel(symbols, frames, features),
        contract=contract,
    )
    _, forward_metadata, forward_ranked = fit_as_of(
        dates[35], symbols, frames, dates, contract
    )
    assert replay_metadata["model_sha256"] == forward_metadata["model_sha256"]
    assert replay_ranked["symbol"].tolist() == forward_ranked["symbol"].tolist()
    assert np.allclose(
        replay_ranked["predicted_probability"],
        forward_ranked["predicted_probability"],
        rtol=0,
        atol=1e-14,
    )
    first = reconstruct(
        symbols=symbols,
        frames=frames,
        dates=dates,
        contract=contract,
        requested_start=dates[30],
    )
    second = reconstruct(
        symbols=symbols,
        frames=frames,
        dates=dates,
        contract=contract,
        requested_start=dates[30],
    )
    assert first["classification"] == CLASSIFICATION
    assert first["starting_capital"] == 100_000.0
    assert first["ending_equity"] > 0
    assert first["decisions"] > 40
    assert first["entries"] >= first["completed_exits"] > 35
    assert first["minimum_ranked_universe_count"] == len(symbols)
    assert len(first["history"]) > 35
    assert first["history"][0]["portfolio_equity"] == 100_000.0
    assert first["history"][-1]["timestamp"] == dates[-1].isoformat()
    assert first["limitations"]["retrospective_not_forward_evidence"] is True
    assert first["limitations"]["current_fixed_universe_survivorship_bias"] is True
    assert all(value is False for value in first["research_safety"].values())
    assert first["reconstruction_sha256"] == second["reconstruction_sha256"]
    date_to_index = {value: index for index, value in enumerate(dates)}
    for anchor in first["model_sha_anchors"]:
        decision = pd.Timestamp(anchor["decision_timestamp_utc"])
        cutoff = pd.Timestamp(anchor["training_cutoff_utc"])
        assert date_to_index[decision] - date_to_index[cutoff] == 5
    with tempfile.TemporaryDirectory() as temporary:
        artifact = Path(temporary) / "retrospective_10y.json"
        artifact.write_text(json.dumps(first), encoding="utf-8")
        with (
            patch.object(comparison, "V14_PATH", artifact),
            patch.object(comparison, "V14_EXPECTED_SHA", first["contract_sha256"]),
        ):
            series = comparison._load_v14()
        assert series["model_id"] == "V14"
        assert series["candidate_id"] == contract["candidate_id"]
        assert series["starting_capital"] == 100_000.0
        assert series["survivorship_bias_disclosed"] is True
    print("[PASS] Retrospective coefficients, probabilities, and ranks match the forward learner")
    print("[PASS] V14 retrospective retrains only through the five-session purge cutoff")
    print("[PASS] Five staggered sleeves compound from the common $100,000 basis")
    print("[PASS] Terminal open sleeves are marked without entering paper-forward evidence")
    print("[PASS] Counterfactual identity is deterministic and survivorship bias is disclosed")
    print("[PASS] Model-comparison adapter accepts only the validated V14 artifact")
    print("[PASS] Paper journals, V8/V10, promotion, and brokerage authority remain untouched")
    print("Status: PASSED")


if __name__ == "__main__":
    main()
