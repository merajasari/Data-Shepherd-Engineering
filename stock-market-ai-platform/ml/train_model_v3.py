"""
Train a baseline stock-direction prediction model for any configured symbol.

Usage:
    python ml/train_model.py AAPL
    python ml/train_model.py MSFT
    python ml/train_model.py NVDA

The model predicts whether the stock will be higher five trading
days in the future.

This implementation uses NumPy, Pandas, and the Python standard library.
"""

from pathlib import Path
import pickle
import sys

import numpy as np
import pandas as pd

from feature_source import require_feature_dataset


PREDICTION_THRESHOLD = 0.50


FEATURE_COLUMNS = [
    "daily_return",
    "cumulative_return",
    "return_2d",
    "return_3d",
    "sma_7",
    "sma_20",
    "sma_50",
    "sma_200",
    "volume_sma_20",
    "daily_volatility",
    "return_5d",
    "return_10d",
    "return_20d",
    "return_60d",
    "price_vs_sma_7",
    "price_vs_sma_20",
    "price_vs_sma_50",
    "price_vs_sma_200",
    "sma_7_vs_sma_20",
    "sma_20_vs_sma_50",
    "sma_50_vs_sma_200",
    "intraday_range",
    "open_close_range",
    "volume_ratio",
    "volume_change_5d",
    "volatility_5d",
    "volatility_20d",
    "volatility_ratio_5_20",
    "trend_20_50",
    "trend_50_200",
    "distance_from_20d_high",
    "distance_from_20d_low",
    "rsi_14",
    "rsi_centered",
    "momentum_10d",
]


class LogisticRegression:
    """Lightweight NumPy binary logistic regression."""

    def __init__(
        self,
        learning_rate=0.05,
        epochs=3000,
        l2=0.001,
    ):
        self.learning_rate = learning_rate
        self.epochs = epochs
        self.l2 = l2
        self.weights = None
        self.bias = 0.0

    @staticmethod
    def sigmoid(values):
        values = np.clip(
            values,
            -500,
            500,
        )

        return 1.0 / (
            1.0 + np.exp(-values)
        )

    def fit(
        self,
        X,
        y,
    ):
        row_count, feature_count = X.shape

        self.weights = np.zeros(
            feature_count,
            dtype=float,
        )

        self.bias = 0.0

        for _ in range(self.epochs):

            scores = (
                X @ self.weights
                + self.bias
            )

            probabilities = self.sigmoid(
                scores
            )

            error = probabilities - y

            weight_gradient = (
                (X.T @ error) / row_count
                + self.l2 * self.weights
            )

            bias_gradient = np.mean(
                error
            )

            self.weights -= (
                self.learning_rate
                * weight_gradient
            )

            self.bias -= (
                self.learning_rate
                * bias_gradient
            )

    def predict_probability(
        self,
        X,
    ):
        scores = (
            X @ self.weights
            + self.bias
        )

        return self.sigmoid(
            scores
        )

    def predict(
        self,
        X,
        threshold=PREDICTION_THRESHOLD,
    ):
        probabilities = (
            self.predict_probability(X)
        )

        return (
            probabilities >= threshold
        ).astype(int)


def get_paths(symbol: str):
    """Return the feature and model paths for a symbol."""

    feature_file = require_feature_dataset(symbol)

    model_path = Path(
        f"models/{symbol.lower()}_trade_model_v3.pkl"
    )

    return (
        feature_file,
        model_path,
    )


def load_dataset(
    feature_file: Path,
):
    """Load and prepare the feature dataset."""

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

    df = df.dropna(
        subset=[
            "forward_return_5d",
            "target_trade_5d",
        ]
    )

    df = df.dropna(
        subset=FEATURE_COLUMNS
    )

    return df


def standardize(
    X_train,
    X_test,
):
    """Standardize using training statistics only."""

    feature_mean = X_train.mean(
        axis=0
    )

    feature_std = X_train.std(
        axis=0
    )

    feature_std[
        feature_std == 0
    ] = 1.0

    X_train_scaled = (
        X_train - feature_mean
    ) / feature_std

    X_test_scaled = (
        X_test - feature_mean
    ) / feature_std

    return (
        X_train_scaled,
        X_test_scaled,
        feature_mean,
        feature_std,
    )


def calculate_metrics(
    y_true,
    predictions,
):
    """Calculate basic binary classification metrics."""

    y_true = np.asarray(
        y_true
    )

    predictions = np.asarray(
        predictions
    )

    true_positive = np.sum(
        (y_true == 1)
        & (predictions == 1)
    )

    true_negative = np.sum(
        (y_true == 0)
        & (predictions == 0)
    )

    false_positive = np.sum(
        (y_true == 0)
        & (predictions == 1)
    )

    false_negative = np.sum(
        (y_true == 1)
        & (predictions == 0)
    )

    accuracy = (
        (true_positive + true_negative)
        / len(y_true)
    )

    precision = (
        true_positive
        / (true_positive + false_positive)
        if (true_positive + false_positive)
        else 0.0
    )

    recall = (
        true_positive
        / (true_positive + false_negative)
        if (true_positive + false_negative)
        else 0.0
    )

    f1 = (
        2
        * precision
        * recall
        / (precision + recall)
        if (precision + recall)
        else 0.0
    )

    return {
        "accuracy":
            float(accuracy),

        "precision":
            float(precision),

        "recall":
            float(recall),

        "f1":
            float(f1),

        "true_positive":
            int(true_positive),

        "true_negative":
            int(true_negative),

        "false_positive":
            int(false_positive),

        "false_negative":
            int(false_negative),
    }



def walk_forward_validate(
    X,
    y,
    initial_train_fraction=0.60,
    fold_fraction=0.10,
    purge_gap=5,
):
    """
    Expanding-window walk-forward validation.

    Each fold:
      - trains on all prior data
      - leaves a 5-row purge gap
      - tests on the next chronological block
    """

    row_count = len(X)

    initial_train_end = int(
        row_count * initial_train_fraction
    )

    fold_size = max(
        20,
        int(row_count * fold_fraction),
    )

    fold_results = []

    train_end = initial_train_end

    while True:
        test_start = (
            train_end
            + purge_gap
        )

        test_end = min(
            row_count,
            test_start + fold_size,
        )

        if (
            test_start >= row_count
            or test_end - test_start < 10
        ):
            break

        X_train = X[:train_end]
        y_train = y[:train_end]

        X_test = X[
            test_start:test_end
        ]

        y_test = y[
            test_start:test_end
        ]

        (
            X_train_scaled,
            X_test_scaled,
            _,
            _,
        ) = standardize(
            X_train,
            X_test,
        )

        model = LogisticRegression()

        model.fit(
            X_train_scaled,
            y_train,
        )

        predictions = model.predict(
            X_test_scaled,
            threshold=PREDICTION_THRESHOLD,
        )

        metrics = calculate_metrics(
            y_test,
            predictions,
        )

        actual_up_rate = float(
            y_test.mean()
        )

        majority_baseline = max(
            actual_up_rate,
            1.0 - actual_up_rate,
        )

        fold_results.append(
            {
                "train_rows":
                    int(len(X_train)),

                "test_rows":
                    int(len(X_test)),

                "accuracy":
                    float(
                        metrics["accuracy"]
                    ),

                "majority_baseline":
                    float(
                        majority_baseline
                    ),

                "edge":
                    float(
                        metrics["accuracy"]
                        - majority_baseline
                    ),
            }
        )

        train_end = test_end

    if not fold_results:
        return {
            "fold_count": 0,
            "mean_accuracy": None,
            "mean_baseline": None,
            "mean_edge": None,
            "positive_edge_folds": 0,
            "folds": [],
        }

    mean_accuracy = float(
        np.mean(
            [
                fold["accuracy"]
                for fold in fold_results
            ]
        )
    )

    mean_baseline = float(
        np.mean(
            [
                fold["majority_baseline"]
                for fold in fold_results
            ]
        )
    )

    mean_edge = float(
        np.mean(
            [
                fold["edge"]
                for fold in fold_results
            ]
        )
    )

    positive_edge_folds = sum(
        1
        for fold in fold_results
        if fold["edge"] > 0
    )

    return {
        "fold_count":
            len(fold_results),

        "mean_accuracy":
            mean_accuracy,

        "mean_baseline":
            mean_baseline,

        "mean_edge":
            mean_edge,

        "positive_edge_folds":
            positive_edge_folds,

        "folds":
            fold_results,
    }


def train_model(
    df,
    symbol,
):
    """Train and evaluate one symbol model."""

    X = df[
        FEATURE_COLUMNS
    ].to_numpy(
        dtype=float
    )

    y = df[
        "target_trade_5d"
    ].to_numpy(
        dtype=int
    )

    split_index = int(
        len(df) * 0.80
    )

    purge_gap = 5

    train_end = max(
        0,
        split_index - purge_gap,
    )

    X_train = X[
        :train_end
    ]

    X_test = X[
        split_index:
    ]

    y_train = y[
        :train_end
    ]

    y_test = y[
        split_index:
    ]

    (
        X_train_scaled,
        X_test_scaled,
        feature_mean,
        feature_std,
    ) = standardize(
        X_train,
        X_test,
    )

    print()
    print(
        f"{symbol} MODEL TRAINING"
    )
    print(
        "=" * 48
    )

    print(
        f"Total usable rows: {len(df)}"
    )

    print(
        f"Training rows:     {len(X_train)}"
    )

    print(
        f"Test rows:         {len(X_test)}"
    )

    model = LogisticRegression()

    model.fit(
        X_train_scaled,
        y_train,
    )

    probabilities = (
        model.predict_probability(
            X_test_scaled
        )
    )

    predictions = model.predict(
        X_test_scaled,
        threshold=PREDICTION_THRESHOLD,
    )

    metrics = calculate_metrics(
        y_test,
        predictions,
    )

    actual_up_rate = float(
        y_test.mean()
    )

    majority_baseline = max(
        actual_up_rate,
        1.0 - actual_up_rate,
    )

    walk_forward = walk_forward_validate(
        X,
        y,
    )

    print()
    print("Model Performance")
    print("-----------------")

    print(
        f"Accuracy:          "
        f"{metrics['accuracy']:.4f}"
    )

    print(
        f"Majority baseline: "
        f"{majority_baseline:.4f}"
    )

    print(
        f"Precision:         "
        f"{metrics['precision']:.4f}"
    )

    print(
        f"Recall:            "
        f"{metrics['recall']:.4f}"
    )

    print(
        f"F1 Score:          "
        f"{metrics['f1']:.4f}"
    )

    artifact = {
        "model_type":
            "numpy_logistic_regression_v3_trade_target",

        "version":
            3,

        "symbol":
            symbol,

        "target":
            "target_trade_5d",

        "target_horizon_days":
            5,

        "prediction_threshold":
            PREDICTION_THRESHOLD,

        "feature_columns":
            FEATURE_COLUMNS,

        "weights":
            np.asarray(
                model.weights,
                dtype=float,
            ),

        "bias":
            float(
                model.bias
            ),

        "feature_mean":
            np.asarray(
                feature_mean,
                dtype=float,
            ),

        "feature_std":
            np.asarray(
                feature_std,
                dtype=float,
            ),

        "metrics":
            metrics,

        "majority_baseline":
            float(
                majority_baseline
            ),

        "walk_forward":
            walk_forward,

        "training_rows":
            int(
                len(X_train)
            ),

        "test_rows":
            int(
                len(X_test)
            ),
    }

    return artifact


def save_model(
    artifact,
    model_path,
):
    """Save the portable model artifact."""

    model_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with model_path.open(
        "wb"
    ) as file:

        pickle.dump(
            artifact,
            file,
        )

    print()
    print(
        f"Model saved: {model_path}"
    )


def main():

    symbol = (
        sys.argv[1].upper()
        if len(sys.argv) > 1
        else "AAPL"
    )

    (
        feature_file,
        model_path,
    ) = get_paths(
        symbol
    )

    print(
        f"Loading feature dataset: "
        f"{feature_file}"
    )

    df = load_dataset(
        feature_file
    )

    artifact = train_model(
        df,
        symbol,
    )

    save_model(
        artifact,
        model_path,
    )


if __name__ == "__main__":
    main()
