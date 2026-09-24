import unittest

import numpy as np
import pandas as pd
from sklearn.dummy import DummyClassifier, DummyRegressor

from ml.stock_eagle_250_autonomous_ml_v2.phase1 import (
    load_contract,
)
from ml.stock_eagle_250_autonomous_ml_v2.phase2 import (
    META_FEATURES,
    evaluate_gates,
    inner_meta_training_rows,
    learned_position_weights,
    session_meta_row,
)


def scored_session():
    rows = []
    for i in range(25):
        rows.append({
            "timestamp_utc":
                pd.Timestamp(
                    "2026-01-02",
                    tz="UTC",
                ),
            "symbol": f"S{i:03d}",
            "alpha_prediction":
                0.05 - i * 0.001,
            "downside_probability":
                0.10 + i * 0.01,
            "tail10_prediction":
                -0.01 - i * 0.001,
            "forward_stock_return":
                0.03 - i * 0.001,
        })
    return pd.DataFrame(rows)


def passing_metrics():
    rows = []
    for i in range(10):
        rows.append({
            "fold_id": f"dev_{i:02d}",
            "net_return": 0.10,
            "maximum_drawdown": -0.20,
            "stress_20bps_net_return": 0.08,
            "spy_net_return": 0.03,
            "equal_weight_net_return": 0.04,
            "excess_vs_spy": 0.07,
            "excess_vs_equal_weight": 0.06,
            "mean_rank_ic": 0.05,
            "mean_gross_exposure": 0.70,
            "mean_tail10_top10": -0.03,
        })
    return pd.DataFrame(rows)


class StockEagle250AutonomousMLV2Phase2Test(
    unittest.TestCase
):
    def test_tail_aware_weights_reward_better_tail_prediction(self):
        alpha = np.array([1.0, 1.0, 1.0])
        downside = np.array([0.3, 0.3, 0.3])
        tail10 = np.array([-0.01, -0.05, -0.10])

        weights = learned_position_weights(
            alpha,
            downside,
            tail10,
        )

        self.assertAlmostEqual(
            float(weights.sum()),
            1.0,
        )
        self.assertGreater(
            weights[0],
            weights[1],
        )
        self.assertGreater(
            weights[1],
            weights[2],
        )

    def test_tail_aware_weights_still_penalize_downside(self):
        alpha = np.array([1.0, 1.0, 1.0])
        downside = np.array([0.1, 0.5, 0.9])
        tail10 = np.array([-0.05, -0.05, -0.05])

        weights = learned_position_weights(
            alpha,
            downside,
            tail10,
        )

        self.assertGreater(
            weights[0],
            weights[1],
        )
        self.assertGreater(
            weights[1],
            weights[2],
        )

    def test_meta_row_contains_tail_features_and_target(self):
        row = session_meta_row(
            scored_session(),
            include_target=True,
        )

        for feature in META_FEATURES:
            self.assertIn(feature, row)

        self.assertIn(
            "tail10_top10_mean",
            row,
        )
        self.assertIn(
            "tail10_top10_min",
            row,
        )
        self.assertIn(
            "tail10_cross_sectional_min",
            row,
        )
        self.assertIn(
            "meta_target_positive",
            row,
        )
        self.assertEqual(
            len(row["selected_weight_vector"]),
            10,
        )

    def test_inner_meta_rows_are_strictly_oos_with_tail_model(self):
        feature_columns = ["f1", "f2"]
        sessions = pd.date_range(
            "2024-01-02",
            periods=325,
            freq="B",
            tz="UTC",
        )
        rows = []
        for sidx, timestamp in enumerate(sessions):
            endpoint = (
                timestamp
                + pd.offsets.BDay(5)
            )
            for i in range(20):
                rows.append({
                    "timestamp_utc":
                        timestamp,
                    "target_endpoint_utc_5d":
                        endpoint,
                    "symbol": f"S{i:03d}",
                    "f1":
                        float(i) / 20.0,
                    "f2":
                        float(
                            (sidx + i) % 17
                        ) / 17.0,
                    "forward_relative_return_5d":
                        (
                            0.01
                            if i < 10
                            else -0.01
                        ),
                    "forward_stock_return":
                        (
                            0.02
                            if (sidx + i) % 2 == 0
                            else -0.02
                        ),
                })

        frame = pd.DataFrame(rows)
        templates = {
            "alpha_model":
                DummyRegressor(
                    strategy="mean"
                ),
            "downside_model":
                DummyClassifier(
                    strategy="prior"
                ),
            "tail_model":
                DummyRegressor(
                    strategy="quantile",
                    quantile=0.1,
                ),
        }

        contract = load_contract()
        contract = {**contract}
        contract["nested_walk_forward"] = {
            **contract[
                "nested_walk_forward"
            ],
            "inner_meta_training": {
                **contract[
                    "nested_walk_forward"
                ][
                    "inner_meta_training"
                ],
                "minimum_base_training_sessions":
                    252,
                "test_block_sessions":
                    63,
                "purge_sessions":
                    5,
            },
        }

        result = inner_meta_training_rows(
            frame,
            feature_columns,
            templates,
            contract,
        )

        self.assertFalse(result.empty)
        self.assertTrue(
            set(META_FEATURES).issubset(
                result.columns
            )
        )

        train_endpoints = pd.to_datetime(
            result[
                "inner_training_max_target_endpoint_utc"
            ],
            utc=True,
        )
        tests = pd.to_datetime(
            result[
                "inner_test_timestamp_utc"
            ],
            utc=True,
        )
        self.assertTrue(
            (
                train_endpoints
                < tests
            ).all()
        )

    def test_same_nine_gates_only_qualify_for_paper_build(self):
        gates, _summary, decision = evaluate_gates(
            passing_metrics(),
            load_contract(),
        )

        self.assertEqual(
            len(gates),
            9,
        )
        self.assertTrue(
            gates["passed"].all()
        )
        self.assertEqual(
            decision["status"],
            "QUALIFIES_FOR_AUTONOMOUS_PAPER_BUILD",
        )
        self.assertFalse(
            decision[
                "autonomous_paper_runtime_enabled"
            ]
        )
        self.assertFalse(
            decision["model_frozen"]
        )

    def test_failed_drawdown_gate_rejects_v2(self):
        metrics = passing_metrics()
        metrics.loc[
            0,
            "maximum_drawdown",
        ] = -0.31

        gates, _summary, decision = evaluate_gates(
            metrics,
            load_contract(),
        )

        row = gates.set_index("gate").loc[
            "worst_fold_maximum_drawdown_gte"
        ]
        self.assertFalse(
            bool(row["passed"])
        )
        self.assertEqual(
            decision["status"],
            "REJECT_DEVELOPMENT_CANDIDATE",
        )


if __name__ == "__main__":
    unittest.main()
