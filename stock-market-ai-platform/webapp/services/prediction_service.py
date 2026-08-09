"""
Prediction service for the Stock Market AI presentation layer.
"""

from pathlib import Path
import pickle

import numpy as np
import pandas as pd


def sigmoid(value):
    value = np.clip(
        value,
        -500,
        500,
    )

    return 1.0 / (
        1.0 + np.exp(-value)
    )


def get_model_file(symbol: str) -> Path:
    return Path(
        f"models/{symbol.lower()}_direction_model.pkl"
    )


def get_feature_file(symbol: str) -> Path:
    return Path(
        f"data/features/stocks/{symbol}/{symbol}_features.parquet"
    )


def load_model(symbol: str) -> dict:
    """Load model artifact for one symbol."""

    model_file = get_model_file(symbol)

    if not model_file.exists():
        raise FileNotFoundError(
            f"Model not found: {model_file}"
        )

    with model_file.open("rb") as file:
        return pickle.load(file)


def get_latest_prediction(symbol: str) -> dict:
    """Generate latest prediction for one symbol."""

    artifact = load_model(symbol)

    feature_file = get_feature_file(symbol)

    if not feature_file.exists():
        raise FileNotFoundError(
            f"Feature file not found: {feature_file}"
        )

    df = pd.read_parquet(
        feature_file
    )

    df = df.sort_values(
        "timestamp"
    ).reset_index(drop=True)

    feature_columns = artifact[
        "feature_columns"
    ]

    valid_rows = df.dropna(
        subset=feature_columns
    )

    if valid_rows.empty:
        raise ValueError(
            f"No valid feature rows for {symbol}"
        )

    latest = valid_rows.iloc[-1]

    features = latest[
        feature_columns
    ].to_numpy(
        dtype=float
    )

    mean = np.asarray(
        artifact["feature_mean"],
        dtype=float,
    )

    std = np.asarray(
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
        artifact[
            "prediction_threshold"
        ]
    )

    std = std.copy()

    std[
        std == 0
    ] = 1.0

    scaled = (
        features - mean
    ) / std

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

    return {
        "symbol":
            symbol,

        "prediction":
            prediction,

        "probability_up":
            probability_up,

        "probability_down":
            probability_down,

        "confidence":
            output_probability,

        "threshold":
            threshold,

        "horizon_days":
            artifact.get(
                "target_horizon_days",
                5,
            ),

        "model_type":
            artifact.get(
                "model_type",
                "unknown",
            ),

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

        "timestamp":
            str(
                latest["timestamp_utc"]
            ),

        "close":
            float(
                latest["close"]
            ),
    }

