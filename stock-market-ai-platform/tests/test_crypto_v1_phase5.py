"""Focused tests for Crypto V1 Phase 5 diagnostics."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from ml.crypto_v1.phase5 import (
    ATTRIBUTION_COLUMNS,
    DRAWDOWN_COLUMNS,
    REGIME_COLUMNS,
    RELATIVE_COLUMNS,
    SPREAD_COLUMNS,
    asset_attribution,
    drawdown_episodes,
    regime_performance,
    relative_performance,
    run_phase5,
    spread_diagnostics,
)


PRODUCTS = [
    "BTC-USD", "ETH-USD", "SOL-USD",
    "XRP-USD", "ADA-USD", "LTC-USD",
]
MODELS = [
    "momentum", "hist_gradient_boosting",
    "random", "equal_score",
]


def synthetic_predictions():
    dates = pd.date_range(
        "2025-01-01", periods=20, tz="UTC"
    )
    rows = []

    for split, subset in (
        ("development", dates[:12]),
        ("holdout", dates[12:]),
    ):
        fold_id = (
            "dev_01" if split == "development" else "holdout"
        )

        for model_id in MODELS:
            for day_number, timestamp in enumerate(subset):
                regime = (
                    "bull" if day_number % 2 == 0 else "bear"
                )

                for asset_number, product in enumerate(PRODUCTS):
                    if model_id == "momentum":
                        score = len(PRODUCTS) - asset_number
                    elif model_id == "hist_gradient_boosting":
                        score = asset_number
                    elif model_id == "random":
                        score = (
                            (day_number * 7 + asset_number * 3) % 17
                        ) / 17
                    else:
                        score = 0.0

                    rows.append({
                        "timestamp_utc": timestamp,
                        "product_id": product,
                        "actual_btc_relative_forward_return": (
                            0.01 * (3 - asset_number)
                        ),
                        "predicted_score": score,
                        "fold_id": fold_id,
                        "split": split,
                        "model_id": model_id,
                        "horizon_days": 7,
                        "btc_regime": regime,
                    })

    return pd.DataFrame(rows)


def synthetic_panel():
    dates = pd.date_range(
        "2025-01-01", periods=20, tz="UTC"
    )
    rows = []

    for day_number, timestamp in enumerate(dates):
        for asset_number, product in enumerate(PRODUCTS):
            rows.append({
                "timestamp_utc": timestamp,
                "product_id": product,
                "return_1d": (
                    0.01 if day_number % 2 == 0 else -0.008
                ) + asset_number * 0.0001,
            })

    return pd.DataFrame(rows)


def synthetic_daily():
    dates = pd.date_range(
        "2025-01-01", periods=20, tz="UTC"
    )
    rows = []

    for split, subset in (
        ("development", dates[:12]),
        ("holdout", dates[12:]),
    ):
        for model_id in MODELS:
            variants = [
                ("top_3_equal_weight", 3),
                ("top_5_equal_weight", 5),
            ]

            if model_id == "momentum":
                variants += [
                    ("btc_benchmark", None),
                    ("cash", None),
                ]

            for variant, top_n in variants:
                for cost in (0.0, 10.0):
                    equity = 1.0

                    for i, timestamp in enumerate(subset):
                        net = (
                            0.0
                            if i == 0
                            else (
                                0.006 if i % 2 == 0 else -0.005
                            )
                        )

                        if cost > 0 and i in (0, 7):
                            net -= 0.0005

                        equity *= 1.0 + net

                        rows.append({
                            "timestamp_utc": timestamp,
                            "split": split,
                            "model_id": model_id,
                            "strategy_id": (
                                f"{model_id}:{variant}:"
                                f"top{top_n or 0}"
                            ),
                            "variant": variant,
                            "top_n": top_n,
                            "cost_bps_round_trip": cost,
                            "is_rebalance": i in (0, 7),
                            "turnover": (
                                0.5
                                if i in (0, 7)
                                and variant != "cash"
                                else 0.0
                            ),
                            "transaction_cost": (
                                0.0005
                                if cost > 0 and i in (0, 7)
                                else 0.0
                            ),
                            "gross_return": net,
                            "net_return": net,
                            "gross_exposure": (
                                0.0 if variant == "cash" else 1.0
                            ),
                            "net_exposure": (
                                0.0 if variant == "cash" else 1.0
                            ),
                            "cash_weight": (
                                1.0 if variant == "cash" else 0.0
                            ),
                            "equity": equity,
                        })

    return pd.DataFrame(rows)


def synthetic_metrics(daily):
    keys = [
        "split", "model_id", "strategy_id",
        "variant", "top_n", "cost_bps_round_trip",
    ]
    rows = []

    for values, group in daily.groupby(
        keys, sort=True, dropna=False
    ):
        rows.append(dict(zip(keys, values)) | {
            "ending_equity": group["equity"].iloc[-1],
            "cumulative_return": (
                group["equity"].iloc[-1] - 1.0
            ),
            "maximum_drawdown": -0.10,
            "total_turnover": group["turnover"].sum(),
            "number_of_rebalances": int(
                group["is_rebalance"].sum()
            ),
        })

    return pd.DataFrame(rows)


class Phase5UnitTests(unittest.TestCase):
    def setUp(self):
        self.predictions = synthetic_predictions()
        self.panel = synthetic_panel()
        self.daily = synthetic_daily()

    def test_regime_schema_and_split_separation(self):
        frame = regime_performance(
            self.daily, self.predictions
        )

        self.assertEqual(
            list(frame.columns), REGIME_COLUMNS
        )
        self.assertEqual(
            set(frame["split"]),
            {"development", "holdout"},
        )
        self.assertTrue(
            {"bull", "bear"}.issubset(
                set(frame["btc_regime"])
            )
        )

    def test_relative_schema(self):
        frame = relative_performance(
            self.daily, self.panel
        )

        self.assertEqual(
            list(frame.columns), RELATIVE_COLUMNS
        )
        self.assertTrue(
            (frame["observation_count"] > 0).all()
        )

    def test_no_future_btc_return_usage(self):
        cutoff = pd.Timestamp(
            "2025-01-10", tz="UTC"
        )

        daily = self.daily[
            self.daily["timestamp_utc"] <= cutoff
        ]
        panel = self.panel.copy()
        mutated = panel.copy()

        mutated.loc[
            mutated["timestamp_utc"] > cutoff,
            "return_1d",
        ] *= 1000

        left = relative_performance(
            daily,
            panel[panel["timestamp_utc"] <= cutoff],
        )
        right = relative_performance(
            daily,
            mutated[mutated["timestamp_utc"] <= cutoff],
        )

        pd.testing.assert_frame_equal(left, right)

    def test_momentum_spread_is_positive(self):
        frame = spread_diagnostics(
            self.predictions
        )
        momentum = frame[
            frame["model_id"] == "momentum"
        ]

        self.assertEqual(
            list(frame.columns), SPREAD_COLUMNS
        )
        self.assertTrue(
            (
                momentum[
                    "mean_top_minus_bottom_spread"
                ] > 0
            ).all()
        )

    def test_asset_attribution_schema(self):
        frame = asset_attribution(
            self.predictions
        )

        self.assertEqual(
            list(frame.columns), ATTRIBUTION_COLUMNS
        )
        self.assertTrue(
            (
                frame["selection_rate"].dropna()
                >= 0
            ).all()
        )
        self.assertTrue(
            (
                frame["selection_rate"].dropna()
                <= 1
            ).all()
        )

    def test_drawdown_schema(self):
        frame = drawdown_episodes(
            self.daily
        )

        self.assertEqual(
            list(frame.columns), DRAWDOWN_COLUMNS
        )
        self.assertTrue(
            (frame["drawdown"] <= 0).all()
        )

    def test_outputs_are_deterministic(self):
        functions = [
            lambda: regime_performance(
                self.daily, self.predictions
            ),
            lambda: relative_performance(
                self.daily, self.panel
            ),
            lambda: drawdown_episodes(
                self.daily
            ),
            lambda: asset_attribution(
                self.predictions
            ),
            lambda: spread_diagnostics(
                self.predictions
            ),
        ]

        for function in functions:
            first = function()
            second = function()
            pd.testing.assert_frame_equal(
                first, second
            )


class Phase5IntegrationTests(unittest.TestCase):
    def test_run_phase5_preserves_inputs_and_writes_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            phase3 = root / "phase3"
            phase4 = root / "phase4"
            output = root / "phase5"
            phase3.mkdir()
            phase4.mkdir()

            predictions = synthetic_predictions()
            panel = synthetic_panel()
            daily = synthetic_daily()
            metrics = synthetic_metrics(daily)

            prediction_path = (
                phase3 / "predictions.parquet"
            )
            panel_path = (
                root / "research_panel_7d.parquet"
            )
            phase3_manifest = (
                phase3 / "manifest.json"
            )
            phase4_manifest = (
                phase4 / "manifest.json"
            )
            daily_path = (
                phase4 / "portfolio_daily.csv"
            )
            metrics_path = (
                phase4 / "portfolio_metrics.csv"
            )

            prediction_path.write_bytes(
                b"immutable phase3 predictions"
            )
            panel_path.write_bytes(
                b"immutable 7d panel"
            )
            phase3_manifest.write_text(
                json.dumps({"phase": 3}) + "\n",
                encoding="utf-8",
            )
            phase4_manifest.write_text(
                json.dumps({"phase": 4}) + "\n",
                encoding="utf-8",
            )
            daily.to_csv(
                daily_path, index=False
            )
            metrics.to_csv(
                metrics_path, index=False
            )

            tracked = [
                prediction_path,
                panel_path,
                phase3_manifest,
                phase4_manifest,
                daily_path,
                metrics_path,
            ]
            before = {
                path: path.read_bytes()
                for path in tracked
            }

            real_read_parquet = pd.read_parquet

            def fake_read_parquet(
                path, *args, **kwargs
            ):
                path = Path(path)

                if path == prediction_path:
                    return predictions.copy()

                if path == panel_path:
                    return panel.copy()

                return real_read_parquet(
                    path, *args, **kwargs
                )

            with patch(
                "ml.crypto_v1.phase5.pd.read_parquet",
                side_effect=fake_read_parquet,
            ):
                manifest, frames = run_phase5(
                    phase3_root=phase3,
                    phase4_root=phase4,
                    model_root=root,
                    output_root=output,
                )

            after = {
                path: path.read_bytes()
                for path in tracked
            }

            self.assertEqual(before, after)
            self.assertIn(
                "no fitting",
                manifest["policy"],
            )
            self.assertIn(
                "descriptive only",
                manifest["holdout_policy"],
            )
            self.assertEqual(
                set(frames),
                {
                    "regime_performance",
                    "relative_performance",
                    "drawdown_episodes",
                    "asset_attribution",
                    "spread_diagnostics",
                },
            )

            for name in [
                "manifest.json",
                "regime_performance.csv",
                "relative_performance.csv",
                "drawdown_episodes.csv",
                "asset_attribution.csv",
                "spread_diagnostics.csv",
            ]:
                self.assertTrue(
                    (output / name).exists(),
                    name,
                )


if __name__ == "__main__":
    unittest.main()
