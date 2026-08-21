"""
Run inference for any configured stock symbol.

Usage:
    python ml/predict.py AAPL
    python ml/predict.py NVDA
    python ml/predict.py TSLA
"""

from pathlib import Path
import pickle
import sys

import numpy as np
import pandas as pd

from feature_source import require_feature_dataset


def sigmoid(value):
    """Calculate numerically stable sigmoid probability."""

    value = np.clip(
        value,
        -500,
        500,
    )

    return 1.0 / (
        1.0 + np.exp(-value)
    )


def get_paths(symbol: str):
    """Return feature and model paths for a symbol."""

    feature_file = require_feature_dataset(symbol)

    model_file = Path(
        f"models/{symbol.lower()}_direction_model.pkl"
    )

    return (
        feature_file,
        model_file,
    )


def load_model(model_file: Path):
    """Load the portable model artifact."""

    if not model_file.exists():
        raise FileNotFoundError(
            f"Model artifact not found: {model_file}"
        )

    with model_file.open("rb") as file:
        artifact = pickle.load(file)

    required_keys = [
        "model_type",
        "symbol",
        "feature_columns",
        "weights",
        "bias",
        "feature_mean",
        "feature_std",
        "prediction_threshold",
    ]

    missing = [
        key
        for key in required_keys
        if key not in artifact
    ]

    if missing:
        raise ValueError(
            f"Model artifact missing keys: {missing}"
        )

    return artifact


def load_latest_features(
    feature_file: Path,
    feature_columns,
):
    """Load latest row containing all required model features."""

    if not feature_file.exists():
        raise FileNotFoundError(
            f"Feature dataset not found: {feature_file}"
        )

    df = pd.read_parquet(
        feature_file
    )

    df = df.sort_values(
        "timestamp"
    ).reset_index(drop=True)

    missing_columns = [
        column
        for column in feature_columns
        if column not in df.columns
    ]

    if missing_columns:
        raise ValueError(
            f"Feature dataset missing columns: {missing_columns}"
        )

    valid_rows = df.dropna(
        subset=feature_columns
    )

    if valid_rows.empty:
        raise ValueError(
            "No rows contain all required inference features"
        )

    return valid_rows.iloc[-1]


def run_prediction(symbol: str):
    """Generate latest prediction for one stock."""

    (
        feature_file,
        model_file,
    ) = get_paths(
        symbol
    )

    artifact = load_model(
        model_file
    )

    feature_columns = artifact[
        "feature_columns"
    ]

    latest = load_latest_features(
        feature_file,
        feature_columns,
    )

    features = latest[
        feature_columns
    ].to_numpy(
        dtype=float
    )

    feature_mean = np.asarray(
        artifact["feature_mean"],
        dtype=float,
    )

    feature_std = np.asarray(
        artifact["feature_std"],
        dtype=float,
    )

    weights = np.asarray(
        artifact["weights"],
        dtype=float,
    )

    bias = float(
        artifact["bias"]
    )

    threshold = float(
        artifact["prediction_threshold"]
    )

    feature_std = feature_std.copy()

    feature_std[
        feature_std == 0
    ] = 1.0

    scaled = (
        features - feature_mean
    ) / feature_std

    score = (
        scaled @ weights
        + bias
    )

    probability_up = float(
        sigmoid(score)
    )

    probability_down = (
        1.0 - probability_up
    )

    prediction = (
        "UP"
        if probability_up >= threshold
        else "DOWN"
    )

    output_probability = max(
        probability_up,
        probability_down,
    )

    metrics = artifact.get(
        "metrics",
        {}
    )

    result = {
        "symbol":
            symbol,

        "timestamp":
            str(
                latest["timestamp_utc"]
            ),

        "close":
            float(
                latest["close"]
            ),

        "prediction":
            prediction,

        "probability_up":
            probability_up,

        "probability_down":
            probability_down,

        "output_probability":
            output_probability,

        "accuracy":
            metrics.get(
                "accuracy"
            ),

        "majority_baseline":
            artifact.get(
                "majority_baseline"
            ),

        "precision":
            metrics.get(
                "precision"
            ),

        "recall":
            metrics.get(
                "recall"
            ),

        "f1":
            metrics.get(
                "f1"
            ),

        "model_type":
            artifact.get(
                "model_type"
            ),

        "horizon_days":
            artifact.get(
                "target_horizon_days",
                5,
            ),
    }

    return result


def print_prediction(result):
    """Print human-readable prediction output."""

    print()
    print(
        f"{result['symbol']} 5-Day Direction Prediction"
    )

    print(
        "=" * 42
    )

    print(
        f"As of: {result['timestamp']}"
    )

    print(
        f"Close: ${result['close']:.2f}"
    )

    print()

    print(
        f"Prediction: "
        f"{result['prediction']}"
    )

    print(
        f"Probability UP:   "
        f"{result['probability_up']:.2%}"
    )

    print(
        f"Probability DOWN: "
        f"{result['probability_down']:.2%}"
    )

    print(
        f"Model output probability: "
        f"{result['output_probability']:.2%}"
    )

    print()

    if result["accuracy"] is not None:
        print(
            f"Holdout accuracy: "
            f"{result['accuracy']:.2%}"
        )

    if result["majority_baseline"] is not None:
        print(
            f"Majority baseline: "
            f"{result['majority_baseline']:.2%}"
        )

    print()

    print(
        f"Model: {result['model_type']}"
    )

    print(
        f"Horizon: "
        f"{result['horizon_days']} trading days"
    )

    print()
    print(
        "Experimental research output. "
        "Not financial advice."
    )


def main():

    symbol = (
        sys.argv[1].upper()
        if len(sys.argv) > 1
        else "AAPL"
    )

    result = run_prediction(
        symbol
    )

    print_prediction(
        result
    )


if __name__ == "__main__":
    main()
