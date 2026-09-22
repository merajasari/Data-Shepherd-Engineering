import json
import unittest

import numpy as np
import pandas as pd

from ml.stock_eagle_250.phase2 import (
    ENDPOINT_COLUMN,
    FUTURE_HOLDOUT_START_UTC,
    RANK_FEATURE_COLUMNS,
    TARGET_COLUMN,
)
from ml.stock_eagle_250.phase3 import (
    BASELINE_IDS,
    CANDIDATE_IDS,
    PHASE3_CONTRACT_PATH,
    POSITIONS_PER_COHORT,
    build_model_frame,
    cohort_table,
    load_contracts,
    model_templates,
    signal_metrics,
    simulate_overlapping_cohorts,
    summarize_and_gate,
    validate_development_panel,
)


class StockEagle250Phase3Test(unittest.TestCase):
    def test_contract_keeps_exactly_two_fixed_candidates_and_no_trading(self):
        phase2, phase3 = load_contracts()
        self.assertEqual(
            tuple(
                row["candidate_id"]
                for row in phase2["development"]["model_candidates"]
            ),
            CANDIDATE_IDS,
        )
        self.assertEqual(
            tuple(row["candidate_id"] for row in phase3["fixed_candidates"]),
            CANDIDATE_IDS,
        )
        self.assertEqual(
            phase3["input"]["future_holdout_start_utc"],
            "2026-09-23T00:00:00+00:00",
        )
        self.assertFalse(phase3["authority"]["model_freezing_enabled"])
        self.assertFalse(phase3["authority"]["paper_trading_enabled"])
        self.assertFalse(phase3["authority"]["brokerage_orders"])
        self.assertEqual(
            tuple(row["baseline_id"] for row in phase3["matched_baselines"]),
            BASELINE_IDS,
        )

    def test_model_templates_match_preregistered_parameters(self):
        contract = json.loads(
            PHASE3_CONTRACT_PATH.read_text(encoding="utf-8")
        )
        models = model_templates(contract)

        self.assertEqual(tuple(models), CANDIDATE_IDS)
        ridge = models["ridge_fixed_v1"]
        hgb = models["hgb_fixed_v1"]
        self.assertEqual(ridge.alpha, 1.0)
        self.assertTrue(ridge.fit_intercept)
        self.assertEqual(hgb.learning_rate, 0.05)
        self.assertEqual(hgb.max_iter, 300)
        self.assertEqual(hgb.max_leaf_nodes, 31)
        self.assertEqual(hgb.min_samples_leaf, 100)
        self.assertEqual(hgb.l2_regularization, 1.0)
        self.assertFalse(hgb.early_stopping)
        self.assertEqual(hgb.random_state, 1729)

    def test_future_holdout_decision_or_endpoint_is_rejected(self):
        safe = pd.Timestamp("2026-09-22", tz="UTC")
        frame = pd.DataFrame({
            "timestamp_utc": [safe],
            ENDPOINT_COLUMN: [safe],
            "symbol": ["AAA"],
            "model_eligible": [True],
        })
        validate_development_panel(frame)

        bad_decision = frame.copy()
        bad_decision["timestamp_utc"] = FUTURE_HOLDOUT_START_UTC
        with self.assertRaisesRegex(RuntimeError, "future holdout"):
            validate_development_panel(bad_decision)

        bad_endpoint = frame.copy()
        bad_endpoint[ENDPOINT_COLUMN] = FUTURE_HOLDOUT_START_UTC
        with self.assertRaisesRegex(RuntimeError, "future holdout"):
            validate_development_panel(bad_endpoint)

    def test_model_frame_uses_ranks_and_static_sector_one_hot(self):
        timestamps = pd.to_datetime(
            ["2026-09-14", "2026-09-14"],
            utc=True,
        )
        data = {
            "timestamp_utc": timestamps,
            ENDPOINT_COLUMN: pd.to_datetime(
                ["2026-09-21", "2026-09-21"],
                utc=True,
            ),
            "symbol": ["AAA", "BBB"],
            "sector": ["Tech", "Energy"],
            TARGET_COLUMN: [0.01, -0.02],
            "model_eligible": [True, True],
        }
        for column in RANK_FEATURE_COLUMNS:
            data[column] = [0.5, 1.0]
        frame, columns = build_model_frame(pd.DataFrame(data))

        self.assertEqual(
            columns[:len(RANK_FEATURE_COLUMNS)],
            list(RANK_FEATURE_COLUMNS),
        )
        self.assertEqual(
            columns[len(RANK_FEATURE_COLUMNS):],
            ["sector_Energy", "sector_Tech"],
        )
        self.assertEqual(len(frame), 2)
        self.assertTrue(np.isfinite(frame[columns].to_numpy(float)).all())

    def test_top10_cohort_uses_highest_scores(self):
        timestamp = pd.Timestamp("2026-01-02", tz="UTC")
        endpoint = pd.Timestamp("2026-01-09", tz="UTC")
        frame = pd.DataFrame({
            "timestamp_utc": [timestamp] * 12,
            "entry_timestamp_utc_5d": [
                pd.Timestamp("2026-01-05", tz="UTC")
            ] * 12,
            ENDPOINT_COLUMN: [endpoint] * 12,
            "symbol": [f"S{i:02d}" for i in range(12)],
            "forward_stock_return": np.arange(12) / 100.0,
            "score": np.arange(12),
        })

        cohorts = cohort_table(
            frame,
            "ridge_fixed_v1",
            score_column="score",
            top_n=POSITIONS_PER_COHORT,
        )

        self.assertEqual(int(cohorts.loc[0, "selected_count"]), 10)
        self.assertNotIn("S00", cohorts.loc[0, "selected_symbols"])
        self.assertNotIn("S01", cohorts.loc[0, "selected_symbols"])
        self.assertAlmostEqual(
            cohorts.loc[0, "gross_return"],
            np.arange(2, 12).mean() / 100.0,
        )

    def test_five_sleeves_apply_two_sided_costs(self):
        timestamps = pd.date_range(
            "2026-01-02",
            periods=5,
            freq="B",
            tz="UTC",
        )
        cohorts = pd.DataFrame({
            "timestamp_utc": timestamps,
            "entry_timestamp_utc_5d": timestamps,
            ENDPOINT_COLUMN: timestamps,
            "gross_return": [0.01] * 5,
            "selected_count": [10] * 5,
            "selected_symbols": ["A,B"] * 5,
        })
        periods, summary = simulate_overlapping_cohorts(
            cohorts,
            portfolio_id="ridge_fixed_v1",
            fold_id="dev_01",
            cost_bps_per_side=10.0,
        )
        expected_cohort_net = 1.01 * 0.999 * 0.999 - 1.0
        expected_total = 100_000 * (1.0 + expected_cohort_net)

        self.assertEqual(periods["sleeve_id"].tolist(), [0, 1, 2, 3, 4])
        self.assertAlmostEqual(periods.loc[0, "net_return"], expected_cohort_net)
        self.assertAlmostEqual(summary["ending_equity"], expected_total)
        self.assertAlmostEqual(summary["net_return"], expected_cohort_net)

    def test_signal_metrics_reward_correct_cross_sectional_order(self):
        rows = []
        for day in pd.date_range("2026-01-02", periods=2, freq="B", tz="UTC"):
            for index in range(12):
                rows.append({
                    "timestamp_utc": day,
                    "symbol": f"S{index:02d}",
                    TARGET_COLUMN: index / 100.0,
                    "prediction": index / 100.0,
                })
        metrics = signal_metrics(pd.DataFrame(rows), "prediction")

        self.assertAlmostEqual(metrics["mae"], 0.0)
        self.assertAlmostEqual(metrics["rmse"], 0.0)
        self.assertAlmostEqual(metrics["pearson_correlation"], 1.0)
        self.assertAlmostEqual(
            metrics["mean_daily_spearman_rank_ic"],
            1.0,
        )
        self.assertAlmostEqual(
            metrics["positive_daily_rank_ic_fraction"],
            1.0,
        )

    def test_every_gate_is_required_for_qualification(self):
        contract = json.loads(
            PHASE3_CONTRACT_PATH.read_text(encoding="utf-8")
        )
        rows = []
        for candidate_id in CANDIDATE_IDS:
            for index in range(10):
                rows.append({
                    "fold_id": f"dev_{index:02d}",
                    "candidate_id": candidate_id,
                    "net_return": 0.05,
                    "excess_vs_spy": 0.02,
                    "excess_vs_equal_weight": 0.01,
                    "excess_vs_return_20d_rank": 0.01,
                    "mean_daily_spearman_rank_ic": 0.02,
                    "mae": 0.03,
                    "rmse": 0.04,
                    "maximum_drawdown": -0.10,
                })
        metrics = pd.DataFrame(rows)
        summary, gates, qualification = summarize_and_gate(metrics, contract)

        self.assertEqual(len(summary), 2)
        self.assertTrue(gates["qualified_for_human_review"].all())
        self.assertTrue((gates["passed_gate_count"] == 8).all())
        self.assertEqual(
            qualification["status"],
            "QUALIFIES_FOR_HUMAN_REVIEW",
        )
        self.assertFalse(qualification["candidate_frozen"])
        self.assertFalse(qualification["paper_trading_enabled"])

        metrics.loc[
            metrics["candidate_id"] == "hgb_fixed_v1",
            "maximum_drawdown",
        ] = -0.50
        _, gates, qualification = summarize_and_gate(metrics, contract)
        hgb = gates[gates["candidate_id"] == "hgb_fixed_v1"].iloc[0]
        self.assertFalse(
            hgb[
                "gate_worst_fold_maximum_drawdown_gte_minus_35pct"
            ]
        )
        self.assertFalse(hgb["qualified_for_human_review"])
        self.assertEqual(qualification["qualified_candidate_count"], 1)


if __name__ == "__main__":
    unittest.main()
