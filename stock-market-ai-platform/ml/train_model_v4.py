"""
Train the V4 cross-sectional ranking model.

One universe-level model is trained across all 26 stocks.

Target:
    target_top5_5d = 1 if a stock is among the top 5
    forward 5-day returns for that trading date.

Validation:
    expanding-window walk-forward by trading date
    with a 5-date purge gap.
"""

from pathlib import Path
import pickle

import numpy as np
import pyarrow.parquet as pq


DATA_PATH = Path(
    "data/model/v4_cross_section.parquet"
)

MODEL_PATH = Path(
    "models/cross_section_model_v4.pkl"
)

PURGE_GAP = 5
INITIAL_TRAIN_FRACTION = 0.60
FOLD_FRACTION = 0.10

TOP_COUNT = 5


FEATURE_COLUMNS = [
    "xs_daily_return",
    "xs_return_2d",
    "xs_return_3d",
    "xs_return_5d",
    "xs_return_10d",
    "xs_return_20d",
    "xs_return_60d",
    "xs_price_vs_sma_7",
    "xs_price_vs_sma_20",
    "xs_price_vs_sma_50",
    "xs_price_vs_sma_200",
    "xs_sma_7_vs_sma_20",
    "xs_sma_20_vs_sma_50",
    "xs_sma_50_vs_sma_200",
    "xs_intraday_range",
    "xs_open_close_range",
    "xs_volume_ratio",
    "xs_volume_change_5d",
    "xs_volatility_5d",
    "xs_volatility_20d",
    "xs_volatility_ratio_5_20",
    "xs_trend_20_50",
    "xs_trend_50_200",
    "xs_distance_from_20d_high",
    "xs_distance_from_20d_low",
    "xs_rsi_centered",
]


class LogisticRegression:
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

        for _ in range(
            self.epochs
        ):
            scores = (
                X @ self.weights
                + self.bias
            )

            probabilities = (
                self.sigmoid(
                    scores
                )
            )

            error = (
                probabilities
                - y
            )

            weight_gradient = (
                (X.T @ error)
                / row_count
                + self.l2
                * self.weights
            )

            bias_gradient = (
                np.mean(
                    error
                )
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
        return self.sigmoid(
            X @ self.weights
            + self.bias
        )


def load_dataset():
    if not DATA_PATH.exists():
        raise FileNotFoundError(
            f"Missing V4 dataset: "
            f"{DATA_PATH}"
        )

    columns = [
        "symbol",
        "timestamp_utc",
        "target_top5_5d",
        "forward_return_5d",
        *FEATURE_COLUMNS,
    ]

    table = pq.read_table(
        DATA_PATH,
        columns=columns,
    )

    data = {
        name:
            table.column(
                name
            ).to_pylist()
        for name in columns
    }

    symbols = np.asarray(
        data["symbol"],
        dtype=object,
    )

    timestamps = np.asarray(
        data["timestamp_utc"],
        dtype=object,
    )

    y = np.asarray(
        data[
            "target_top5_5d"
        ],
        dtype=int,
    )

    forward_returns = np.asarray(
        data[
            "forward_return_5d"
        ],
        dtype=float,
    )

    X = np.column_stack(
        [
            np.asarray(
                data[column],
                dtype=float,
            )
            for column
            in FEATURE_COLUMNS
        ]
    )

    return (
        X,
        y,
        symbols,
        timestamps,
        forward_returns,
    )


def standardize(
    X_train,
    X_test,
):
    mean = X_train.mean(
        axis=0
    )

    std = X_train.std(
        axis=0
    )

    std[
        std == 0
    ] = 1.0

    return (
        (X_train - mean) / std,
        (X_test - mean) / std,
        mean,
        std,
    )


def evaluate_fold(
    probabilities,
    y_test,
    symbols,
    timestamps,
    forward_returns,
):
    unique_dates = sorted(
        set(
            timestamps.tolist()
        )
    )

    selected_count = 0
    true_top5_count = 0

    selected_returns = []

    daily_precision = []

    for timestamp in unique_dates:

        mask = (
            timestamps
            == timestamp
        )

        indices = np.where(
            mask
        )[0]

        ranked = sorted(
            indices,
            key=lambda index:
                probabilities[index],
            reverse=True,
        )

        selected = ranked[
            :TOP_COUNT
        ]

        hits = sum(
            int(
                y_test[index]
            )
            for index
            in selected
        )

        selected_count += len(
            selected
        )

        true_top5_count += hits

        daily_precision.append(
            hits / TOP_COUNT
        )

        for index in selected:
            selected_returns.append(
                float(
                    forward_returns[
                        index
                    ]
                )
            )

    precision_at_5 = (
        true_top5_count
        / selected_count
        if selected_count
        else 0.0
    )

    avg_forward_return = (
        float(
            np.mean(
                selected_returns
            )
        )
        if selected_returns
        else 0.0
    )

    mean_daily_precision = (
        float(
            np.mean(
                daily_precision
            )
        )
        if daily_precision
        else 0.0
    )

    return {
        "precision_at_5":
            precision_at_5,

        "mean_daily_precision":
            mean_daily_precision,

        "average_forward_return":
            avg_forward_return,

        "selected_count":
            selected_count,
    }


def walk_forward_validate(
    X,
    y,
    symbols,
    timestamps,
    forward_returns,
):
    unique_dates = sorted(
        set(
            timestamps.tolist()
        )
    )

    date_count = len(
        unique_dates
    )

    initial_train_end = int(
        date_count
        * INITIAL_TRAIN_FRACTION
    )

    fold_size = max(
        20,
        int(
            date_count
            * FOLD_FRACTION
        ),
    )

    folds = []

    train_end = (
        initial_train_end
    )

    fold_number = 0

    while True:

        test_start = (
            train_end
            + PURGE_GAP
        )

        test_end = min(
            date_count,
            test_start
            + fold_size,
        )

        if (
            test_start >= date_count
            or test_end
            - test_start
            < 10
        ):
            break

        fold_number += 1

        train_dates = set(
            unique_dates[
                :train_end
            ]
        )

        test_dates = set(
            unique_dates[
                test_start:test_end
            ]
        )

        train_mask = np.asarray(
            [
                timestamp
                in train_dates
                for timestamp
                in timestamps
            ],
            dtype=bool,
        )

        test_mask = np.asarray(
            [
                timestamp
                in test_dates
                for timestamp
                in timestamps
            ],
            dtype=bool,
        )

        X_train = X[
            train_mask
        ]

        y_train = y[
            train_mask
        ]

        X_test = X[
            test_mask
        ]

        y_test = y[
            test_mask
        ]

        symbols_test = symbols[
            test_mask
        ]

        timestamps_test = timestamps[
            test_mask
        ]

        returns_test = (
            forward_returns[
                test_mask
            ]
        )

        (
            X_train_scaled,
            X_test_scaled,
            _,
            _,
        ) = standardize(
            X_train,
            X_test,
        )

        model = (
            LogisticRegression()
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

        metrics = evaluate_fold(
            probabilities,
            y_test,
            symbols_test,
            timestamps_test,
            returns_test,
        )

        metrics[
            "fold"
        ] = fold_number

        metrics[
            "train_dates"
        ] = len(
            train_dates
        )

        metrics[
            "test_dates"
        ] = len(
            test_dates
        )

        folds.append(
            metrics
        )

        train_end = test_end

    return folds


def train_final_model(
    X,
    y,
):
    scaled, _, mean, std = (
        standardize(
            X,
            X,
        )
    )

    model = (
        LogisticRegression()
    )

    model.fit(
        scaled,
        y,
    )

    return (
        model,
        mean,
        std,
    )


def main():
    (
        X,
        y,
        symbols,
        timestamps,
        forward_returns,
    ) = load_dataset()

    print(
        "V4 CROSS-SECTIONAL MODEL"
    )
    print(
        "=" * 52
    )

    print(
        f"Rows:          "
        f"{len(X):,}"
    )

    print(
        f"Features:      "
        f"{X.shape[1]}"
    )

    print(
        f"Trading dates: "
        f"{len(set(timestamps.tolist())):,}"
    )

    print(
        f"Positive rate: "
        f"{y.mean():.2%}"
    )

    folds = (
        walk_forward_validate(
            X,
            y,
            symbols,
            timestamps,
            forward_returns,
        )
    )

    print()
    print(
        "Walk-forward results"
    )
    print(
        "-" * 52
    )

    for fold in folds:
        print(
            f"Fold {fold['fold']}: "
            f"P@5="
            f"{fold['precision_at_5']:.2%} "
            f"AvgRet="
            f"{fold['average_forward_return']:.2%} "
            f"TestDates="
            f"{fold['test_dates']}"
        )

    if folds:
        mean_precision = float(
            np.mean(
                [
                    fold[
                        "precision_at_5"
                    ]
                    for fold
                    in folds
                ]
            )
        )

        mean_return = float(
            np.mean(
                [
                    fold[
                        "average_forward_return"
                    ]
                    for fold
                    in folds
                ]
            )
        )

    else:
        mean_precision = 0.0
        mean_return = 0.0

    print()
    print(
        f"Mean precision@5: "
        f"{mean_precision:.2%}"
    )

    print(
        f"Random precision: "
        f"{TOP_COUNT / 26:.2%}"
    )

    print(
        f"Mean selected "
        f"5-day return: "
        f"{mean_return:.2%}"
    )

    (
        model,
        feature_mean,
        feature_std,
    ) = train_final_model(
        X,
        y,
    )

    MODEL_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    artifact = {
        "model_type":
            "cross_section_logistic_v4",

        "version":
            4,

        "feature_columns":
            FEATURE_COLUMNS,

        "top_count":
            TOP_COUNT,

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

        "walk_forward":
            folds,

        "mean_precision_at_5":
            mean_precision,

        "mean_selected_return":
            mean_return,
    }

    with MODEL_PATH.open(
        "wb"
    ) as file:
        pickle.dump(
            artifact,
            file,
        )

    print()
    print(
        f"Model saved: "
        f"{MODEL_PATH}"
    )


if __name__ == "__main__":
    main()
