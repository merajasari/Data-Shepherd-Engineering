import unittest

import numpy as np
import pandas as pd
from sklearn.dummy import DummyClassifier, DummyRegressor

from ml.stock_eagle_250_autonomous_ml_v1.phase1 import load_contract
from ml.stock_eagle_250_autonomous_ml_v1.phase2 import (
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
            "timestamp_utc": pd.Timestamp("2026-01-02", tz="UTC"),
            "symbol": f"S{i:03d}",
            "alpha_prediction": 0.05 - i * 0.001,
            "downside_probability": 0.10 + i * 0.01,
            "forward_stock_return": 0.03 - i * 0.001,
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
        })
    return pd.DataFrame(rows)


class StockEagle250AutonomousMLV1Phase2Test(unittest.TestCase):
    def test_learned_weights_are_normalized_and_downside_sensitive(self):
        alpha = np.array([1.0, 1.0, 1.0])
        downside = np.array([0.1, 0.5, 0.9])
        weights = learned_position_weights(alpha, downside)

        self.assertAlmostEqual(float(weights.sum()), 1.0)
        self.assertGreater(weights[0], weights[1])
        self.assertGreater(weights[1], weights[2])

    def test_meta_row_contains_fixed_learned_features_and_target(self):
        row = session_meta_row(scored_session(), include_target=True)

        for feature in META_FEATURES:
            self.assertIn(feature, row)
        self.assertIn("meta_target_positive", row)
        self.assertIn("meta_target_net_return", row)
        self.assertEqual(len(row["selected_weight_vector"]), 10)

    def test_inner_meta_rows_are_strictly_oos(self):
        feature_columns = ["f1", "f2"]
        sessions = pd.date_range(
            "2024-01-02",
            periods=325,
            freq="B",
            tz="UTC",
        )
        rows = []
        for sidx, timestamp in enumerate(sessions):
            endpoint = timestamp + pd.offsets.BDay(5)
            for i in range(20):
                rows.append({
                    "timestamp_utc": timestamp,
                    "target_endpoint_utc_5d": endpoint,
                    "symbol": f"S{i:03d}",
                    "f1": float(i) / 20.0,
                    "f2": float((sidx + i) % 17) / 17.0,
                    "forward_relative_return_5d":
                        0.01 if i < 10 else -0.01,
                    "forward_stock_return":
                        0.02 if (sidx + i) % 2 == 0 else -0.02,
                })
        frame = pd.DataFrame(rows)
        templates = {
            "alpha_model": DummyRegressor(strategy="mean"),
            "downside_model": DummyClassifier(strategy="prior"),
        }
        contract = load_contract()
        contract = {**contract}
        contract["nested_walk_forward"] = {
            **contract["nested_walk_forward"],
            "inner_meta_training": {
                **contract["nested_walk_forward"]["inner_meta_training"],
                "minimum_base_training_sessions": 252,
                "test_block_sessions": 63,
                "purge_sessions": 5,
            },
        }

        result = inner_meta_training_rows(
            frame,
            feature_columns,
            templates,
            contract,
        )

        self.assertFalse(result.empty)
        train_endpoints = pd.to_datetime(
            result["inner_training_max_target_endpoint_utc"],
            utc=True,
        )
        tests = pd.to_datetime(
            result["inner_test_timestamp_utc"],
            utc=True,
        )
        self.assertTrue((train_endpoints < tests).all())

    def test_all_development_gates_only_qualify_for_paper_build(self):
        gates, _summary, decision = evaluate_gates(
            passing_metrics(),
            load_contract(),
        )

        self.assertTrue(gates["passed"].all())
        self.assertEqual(
            decision["status"],
            "QUALIFIES_FOR_AUTONOMOUS_PAPER_BUILD",
        )
        self.assertFalse(decision["autonomous_paper_runtime_enabled"])
        self.assertFalse(decision["model_frozen"])

    def test_failed_gate_rejects_candidate(self):
        metrics = passing_metrics()
        metrics.loc[0, "maximum_drawdown"] = -0.31

        gates, _summary, decision = evaluate_gates(
            metrics,
            load_contract(),
        )

        row = gates.set_index("gate").loc[
            "worst_fold_maximum_drawdown_gte"
        ]
        self.assertFalse(bool(row["passed"]))
        self.assertEqual(
            decision["status"],
            "REJECT_DEVELOPMENT_CANDIDATE",
        )


if __name__ == "__main__":
    unittest.main()
