"""
Train a baseline stock-direction prediction model.

This implementation intentionally uses only NumPy and Pandas so it
can run in lightweight environments such as Termux.

Target:
    Predict whether the stock price will increase over the next
    5 trading days.
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
    """Small NumPy-based binary logistic regression."""

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
    def sigmoid(z):
        z = np.clip(z, -500, 500)
        return 1.0 / (1.0 + np.exp(-z))

    def fit(self, X, y):
        n_rows, n_features = X.shape

        self.weights = np.zeros(n_features)
        self.bias = 0.0

        for _ in range(self.epochs):
            scores = X @ self.weights + self.bias
            probabilities = self.sigmoid(scores)

            error = probabilities - y

            gradient_w = (
                (X.T @ error) / n_rows
                + self.l2 * self.weights
            )

            gradient_b = np.mean(error)

            self.weights -= (
                self.learning_rate * gradient_w
            )

            self.bias -= (
                self.learning_rate * gradient_b
            )

    def predict_probability(self, X):
        scores = X @ self.weights + self.bias
        return self.sigmoid(scores)

    def predict(self, X):
        probabilities = self.predict_probability(X)
        return (probabilities >= 0.5).astype(int)


def load_dataset():
    """Load and prepare the feature dataset."""

    if not FEATURE_FILE.exists():
        raise FileNotFoundError(
            f"Feature dataset not found: {FEATURE_FILE}"
        )

    df = pd.read_parquet(FEATURE_FILE)

    df = df.sort_values(
        "timestamp"
    ).reset_index(drop=True)

    # Only rows with a known future outcome can be used
    # for supervised training.
    df = df.dropna(
        subset=[
            "forward_return_5d",
            "target_up_5d",
        ]
    )

    # Remove rows containing unavailable technical indicators.
    df = df.dropna(
        subset=FEATURE_COLUMNS
    )

    return df


def standardize(X_train, X_test):
    """Standardize features using training data only."""

    mean = X_train.mean(axis=0)
    std = X_train.std(axis=0)

    # Prevent division by zero for constant columns.
    std[std == 0] = 1.0

    X_train_scaled = (
        (X_train - mean) / std
    )

    X_test_scaled = (
        (X_test - mean) / std
    )

    return (
        X_train_scaled,
        X_test_scaled,
        mean,
        std,
    )


def calculate_metrics(y_true, predictions):
    """Calculate basic binary classification metrics."""

    y_true = np.asarray(y_true)
    predictions = np.asarray(predictions)

    tp = np.sum(
        (y_true == 1) & (predictions == 1)
    )

    tn = np.sum(
        (y_true == 0) & (predictions == 0)
    )

    fp = np.sum(
        (y_true == 0) & (predictions == 1)
    )

    fn = np.sum(
        (y_true == 1) & (predictions == 0)
    )

    accuracy = (
        (tp + tn) / len(y_true)
        if len(y_true)
        else 0.0
    )

    precision = (
        tp / (tp + fp)
        if (tp + fp)
        else 0.0
    )

    recall = (
        tp / (tp + fn)
        if (tp + fn)
        else 0.0
    )

    f1 = (
        2 * precision * recall
        / (precision + recall)
        if (precision + recall)
        else 0.0
    )

    return {
        "accuracy": accuracy,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "tp": tp,
        "tn": tn,
        "fp": fp,
        "fn": fn,
    }


def train_model(df):
    """Train using a chronological 80/20 split."""

    X = df[FEATURE_COLUMNS].to_numpy(
        dtype=float
    )

    y = df["target_up_5d"].to_numpy(
        dtype=int
    )

    split_index = int(len(df) * 0.80)

    X_train = X[:split_index]
    X_test = X[split_index:]

    y_train = y[:split_index]
    y_test = y[split_index:]

    (
        X_train,
        X_test,
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

    print(
        "Training period:",
        df.iloc[0]["timestamp_utc"],
        "to",
        df.iloc[split_index - 1]["timestamp_utc"],
    )

    print(
        "Test period:",
        df.iloc[split_index]["timestamp_utc"],
        "to",
        df.iloc[-1]["timestamp_utc"],
    )

    print()

    model = LogisticRegression(
        learning_rate=0.05,
        epochs=3000,
        l2=0.001,
    )

    model.fit(
        X_train,
        y_train,
    )

    predictions = model.predict(
        X_test
    )

    probabilities = model.predict_probability(
        X_test
    )

    metrics = calculate_metrics(
        y_test,
        predictions,
    )

    print("Model Performance")
    print("=================")

    print(
        f"Accuracy:  {metrics['accuracy']:.4f}"
    )

    print(
        f"Precision: {metrics['precision']:.4f}"
    )

    print(
        f"Recall:    {metrics['recall']:.4f}"
    )

    print(
        f"F1 Score:  {metrics['f1']:.4f}"
    )

    print()

    print("Confusion Matrix")
    print("================")

    print(
        f"                 Predicted"
    )

    print(
        f"                 Down   Up"
    )

    print(
        f"Actual Down      "
        f"{metrics['tn']:4d}   "
        f"{metrics['fp']:4d}"
    )

    print(
        f"Actual Up        "
        f"{metrics['fn']:4d}   "
        f"{metrics['tp']:4d}"
    )

    print()

    print("Sample Predictions")
    print("==================")

    results = pd.DataFrame(
        {
            "timestamp": df.iloc[
                split_index:
            ]["timestamp_utc"].values,
            "actual": y_test,
            "predicted": predictions,
            "probability_up": probabilities,
        }
    )

    print(
        results.head(10).to_string(
            index=False
        )
    )

    model_artifact = {
        "model": model,
        "features": FEATURE_COLUMNS,
        "feature_mean": feature_mean,
        "feature_std": feature_std,
    }

    return model_artifact


def main():
    print("Loading feature dataset...")

    df = load_dataset()

    artifact = train_model(df)

    MODEL_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with MODEL_PATH.open("wb") as file:
        pickle.dump(
            artifact,
            file,
        )

    print()
    print(
        f"Model saved: {MODEL_PATH}"
    )


if __name__ == "__main__":
    main()
