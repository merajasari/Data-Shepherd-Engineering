"""
Train a baseline stock-direction prediction model.

The model predicts whether a stock will be higher five trading
days in the future.

This implementation uses only NumPy, Pandas, and Python's
standard library so it can run in lightweight environments
such as Termux.

Important:
- Training/test splitting is chronological.
- Feature scaling is fit only on training data.
- Future-return fields are never used as model inputs.
- The saved model artifact contains only portable parameters,
  not a pickled custom Python class.
"""

from pathlib import Path
import pickle

import numpy as np
import pandas as pd


FEATURE_FILE = Path(
    "data/features/stocks/AAPL/AAPL_features.parquet"
)

MODEL_PATH = Path(
    "models/aapl_direction_model.pkl"
)

PREDICTION_THRESHOLD = 0.50


FEATURE_COLUMNS = [
    "daily_return",
    "cumulative_return",
    "sma_7",
    "sma_20",
    "sma_50",
    "sma_200",
    "volume_sma_20",
    "daily_volatility",
    "return_5d",
    "return_10d",
    "return_20d",
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
    "rsi_14",
    "momentum_10d",
]


class LogisticRegression:
    """
    Lightweight binary logistic regression implemented with NumPy.
    """

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
        """Calculate numerically stable sigmoid probabilities."""

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
        """Train using gradient descent."""

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
        """Return probability that target equals 1."""

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
        """Return binary predictions."""

        probabilities = (
            self.predict_probability(X)
        )

        return (
            probabilities >= threshold
        ).astype(int)


def load_dataset():
    """
    Load and prepare the feature dataset for training.
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

    # Training rows must have a known future outcome.
    df = df.dropna(
        subset=[
            "forward_return_5d",
            "target_up_5d",
        ]
    )

    # All model input features must be available.
    df = df.dropna(
        subset=FEATURE_COLUMNS
    )

    return df


def standardize(
    X_train,
    X_test,
):
    """
    Standardize features using training statistics only.

    This prevents information from the future test period
    leaking into model preprocessing.
    """

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
    """Calculate binary classification metrics."""

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

    precision_denominator = (
        true_positive
        + false_positive
    )

    precision = (
        true_positive
        / precision_denominator
        if precision_denominator
        else 0.0
    )

    recall_denominator = (
        true_positive
        + false_negative
    )

    recall = (
        true_positive
        / recall_denominator
        if recall_denominator
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
        "accuracy": float(accuracy),
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(f1),

        "true_positive": int(
            true_positive
        ),

        "true_negative": int(
            true_negative
        ),

        "false_positive": int(
            false_positive
        ),

        "false_negative": int(
            false_negative
        ),
    }


def train_model(df):
    """
    Train and evaluate the baseline model.
    """

    X = df[
        FEATURE_COLUMNS
    ].to_numpy(
        dtype=float
    )

    y = df[
        "target_up_5d"
    ].to_numpy(
        dtype=int
    )

    split_index = int(
        len(df) * 0.80
    )

    if split_index <= 0:
        raise ValueError(
            "Not enough rows for training"
        )

    if split_index >= len(df):
        raise ValueError(
            "Not enough rows for testing"
        )

    X_train = X[
        :split_index
    ]

    X_test = X[
        split_index:
    ]

    y_train = y[
        :split_index
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

    print(
        f"Total usable rows: {len(df)}"
    )

    print(
        f"Training rows:     {len(X_train)}"
    )

    print(
        f"Test rows:         {len(X_test)}"
    )

    print()

    training_start = (
        df.iloc[0][
            "timestamp_utc"
        ]
    )

    training_end = (
        df.iloc[
            split_index - 1
        ][
            "timestamp_utc"
        ]
    )

    test_start = (
        df.iloc[
            split_index
        ][
            "timestamp_utc"
        ]
    )

    test_end = (
        df.iloc[-1][
            "timestamp_utc"
        ]
    )

    print(
        "Training period:",
        training_start,
        "to",
        training_end,
    )

    print(
        "Test period:",
        test_start,
        "to",
        test_end,
    )

    print()

    model = LogisticRegression(
        learning_rate=0.05,
        epochs=3000,
        l2=0.001,
    )

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

    print("Model Performance")
    print("=================")

    print(
        f"Accuracy:  "
        f"{metrics['accuracy']:.4f}"
    )

    print(
        f"Precision: "
        f"{metrics['precision']:.4f}"
    )

    print(
        f"Recall:    "
        f"{metrics['recall']:.4f}"
    )

    print(
        f"F1 Score:  "
        f"{metrics['f1']:.4f}"
    )

    print()

    print("Confusion Matrix")
    print("================")

    print(
        "                 Predicted"
    )

    print(
        "                 Down   Up"
    )

    print(
        "Actual Down      "
        f"{metrics['true_negative']:4d}   "
        f"{metrics['false_positive']:4d}"
    )

    print(
        "Actual Up        "
        f"{metrics['false_negative']:4d}   "
        f"{metrics['true_positive']:4d}"
    )

    print()

    actual_up_rate = (
        y_test.mean()
    )

    predicted_up_rate = (
        predictions.mean()
    )

    baseline_accuracy = max(
        actual_up_rate,
        1.0 - actual_up_rate,
    )

    print("Baseline Comparison")
    print("===================")

    print(
        f"Actual UP rate:     "
        f"{actual_up_rate:.4f}"
    )

    print(
        f"Predicted UP rate:  "
        f"{predicted_up_rate:.4f}"
    )

    print(
        f"Majority baseline:  "
        f"{baseline_accuracy:.4f}"
    )

    print(
        f"Model accuracy:     "
        f"{metrics['accuracy']:.4f}"
    )

    print()

    print("Sample Predictions")
    print("==================")

    results = pd.DataFrame(
        {
            "timestamp":
                df.iloc[
                    split_index:
                ][
                    "timestamp_utc"
                ].values,

            "actual":
                y_test,

            "predicted":
                predictions,

            "probability_up":
                probabilities,
        }
    )

    print(
        results.head(10).to_string(
            index=False
        )
    )

    # -----------------------------------------------------
    # IMPORTANT:
    #
    # Save only portable parameters.
    #
    # Do NOT pickle the LogisticRegression class instance.
    # This allows inference scripts to load the artifact
    # without importing the training class.
    # -----------------------------------------------------

    artifact = {
        "model_type":
            "numpy_logistic_regression",

        "version":
            1,

        "symbol":
            "AAPL",

        "target":
            "target_up_5d",

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

        "training_rows":
            int(
                len(X_train)
            ),

        "test_rows":
            int(
                len(X_test)
            ),

        "training_period":
            {
                "start":
                    str(training_start),

                "end":
                    str(training_end),
            },

        "test_period":
            {
                "start":
                    str(test_start),

                "end":
                    str(test_end),
            },
    }

    return artifact


def save_model(
    artifact,
):
    """Persist the portable model artifact."""

    MODEL_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with MODEL_PATH.open(
        "wb"
    ) as file:

        pickle.dump(
            artifact,
            file,
        )

    print()

    print(
        f"Model saved: {MODEL_PATH}"
    )


def main():
    """Training entry point."""

    print(
        "Loading feature dataset..."
    )

    df = load_dataset()

    artifact = train_model(
        df
    )

    save_model(
        artifact
    )


if __name__ == "__main__":
    main()
