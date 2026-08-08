"""
Run inference using the trained AAPL direction model.

This script:
- Loads the saved portable model artifact.
- Loads the latest engineered AAPL feature data.
- Applies the exact training-time standardization.
- Calculates probability of an UP move over the next 5 trading days.
- Prints a human-readable prediction.
"""

from pathlib import Path
import pickle

import numpy as np
import pandas as pd


MODEL_PATH = Path(
    "models/aapl_direction_model.pkl"
)

FEATURE_FILE = Path(
    "data/features/stocks/AAPL/AAPL_features.parquet"
)


def sigmoid(value):
    """Calculate a numerically stable sigmoid probability."""

    value = np.clip(
        value,
        -500,
        500,
    )

    return 1.0 / (
        1.0 + np.exp(-value)
    )


def load_model():
    """Load the portable model artifact."""

    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            f"Model artifact not found: {MODEL_PATH}"
        )

    with MODEL_PATH.open("rb") as file:
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


def load_latest_features(feature_columns):
    """
    Load the latest row with all required inference features.
    """

    if not FEATURE_FILE.exists():
        raise FileNotFoundError(
            f"Feature dataset not found: {FEATURE_FILE}"
        )

    df = pd.read_parquet(
        FEATURE_FILE
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


def predict():
    """Generate the latest stock-direction prediction."""

    artifact = load_model()

    feature_columns = artifact[
        "feature_columns"
    ]

    latest = load_latest_features(
        feature_columns
    )

    X = latest[
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

    X_scaled = (
        X - feature_mean
    ) / feature_std

    score = (
        X_scaled @ weights
        + bias
    )

    probability_up = float(
        sigmoid(score)
    )

    probability_down = (
        1.0 - probability_up
    )

    predicted_up = (
        probability_up >= threshold
    )

    prediction = (
        "UP"
        if predicted_up
        else "DOWN"
    )

    confidence = max(
        probability_up,
        probability_down,
    )

    print()
    print(
        f"{artifact['symbol']} 5-Day Direction Prediction"
    )
    print(
        "=" * 38
    )

    print(
        f"As of: {latest['timestamp_utc']}"
    )

    print(
        f"Close: ${latest['close']:.2f}"
    )

    print()

    print(
        f"Prediction: {prediction}"
    )

    print(
        f"Probability UP:   "
        f"{probability_up:.2%}"
    )

    print(
        f"Probability DOWN: "
        f"{probability_down:.2%}"
    )

    print(
        f"Model confidence: "
        f"{confidence:.2%}"
    )

    print()

    print(
        "Model:",
        artifact["model_type"],
    )

    print(
        "Prediction horizon:",
        "5 trading days",
    )

    if "metrics" in artifact:

        accuracy = artifact[
            "metrics"
        ].get(
            "accuracy"
        )

        if accuracy is not None:
            print(
                "Holdout accuracy:",
                f"{accuracy:.2%}",
            )

    print()
    print(
        "Note: This is an experimental model output,"
    )
    print(
        "not financial advice or a validated trading signal."
    )


if __name__ == "__main__":
    predict()
