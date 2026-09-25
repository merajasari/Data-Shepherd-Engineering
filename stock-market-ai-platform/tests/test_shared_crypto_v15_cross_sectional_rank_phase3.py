import unittest

import pandas as pd

from ml.shared_crypto_v15_cross_sectional_rank import phase3


class SharedCryptoV15Phase3Test(unittest.TestCase):
    def _policy(self):
        return {
            "evaluation_clock": (
                "non-overlapping exact 7-day blocks"
            ),
            "selection_rule": (
                "rank eligible assets by predicted cross-sectional percentile; "
                "select exactly the top 3 eligible assets when at least three "
                "assets are available; no prediction threshold is applied"
            ),
            "asset_weight": 0.20,
            "selected_asset_count": 3,
            "cash_weight": 0.40,
            "maximum_gross_crypto_exposure": 0.60,
            "primary_round_trip_cost_bps": 25.0,
            "stress_round_trip_cost_bps": 50.0,
            "maximum_turnover_per_7d_decision": 0.60,
            "leverage": False,
            "shorting": False,
            "derivatives": False,
        }

    def _selection_gates(self):
        return {
            "median_fold_net_return_gt": 0.0,
            "positive_fold_fraction_gte": 0.80,
            "median_excess_vs_always_btc_gt": 0.0,
            "median_excess_vs_shared_crypto_v3_gt": 0.0,
            "positive_excess_vs_shared_crypto_v3_fraction_gte": 0.80,
            "worst_maximum_drawdown_gte": -0.20,
            "single_fold_profit_concentration_lte": 0.40,
            "survives_stress_cost_bps": 50.0,
        }

    def test_nonoverlapping_blocks_are_fold_local(self):
        rows = []
        for fold_id, start in (
            ("fold_01", "2026-01-01T00:00:00Z"),
            ("fold_02", "2026-02-01T00:00:00Z"),
        ):
            for timestamp in pd.date_range(
                start,
                periods=15,
                freq="24h",
            ):
                rows.append({
                    "fold_id": fold_id,
                    "timestamp_utc": timestamp,
                })

        predictions = pd.DataFrame(
            rows
        )
        shared = pd.DataFrame({
            "timestamp_utc": (
                predictions[
                    "timestamp_utc"
                ]
                .drop_duplicates()
                .sort_values()
            ),
            "predicted_label": "BTC",
        })

        blocks = (
            phase3.select_non_overlapping_blocks(
                predictions,
                shared,
            )
        )

        for _, fold in blocks.groupby(
            "fold_id"
        ):
            gaps = (
                fold[
                    "timestamp_utc"
                ]
                .sort_values()
                .diff()
                .dropna()
            )
            self.assertTrue(
                (
                    gaps
                    >= phase3.HORIZON
                ).all()
            )

    def test_target_weights_are_exact_top3_20pct_plus_40pct_cash(self):
        weights = (
            phase3.build_target_weights(
                [
                    "BTC-USD",
                    "ETH-USD",
                    "SOL-USD",
                ],
                self._policy(),
            )
        )

        self.assertAlmostEqual(
            weights[
                "BTC-USD"
            ],
            0.20,
        )
        self.assertAlmostEqual(
            weights[
                "ETH-USD"
            ],
            0.20,
        )
        self.assertAlmostEqual(
            weights[
                "SOL-USD"
            ],
            0.20,
        )
        self.assertAlmostEqual(
            weights[
                phase3.CASH
            ],
            0.40,
        )
        self.assertAlmostEqual(
            sum(
                weights.values()
            ),
            1.0,
        )

    def test_initial_candidate_turnover_is_60pct(self):
        timestamp = pd.Timestamp(
            "2026-01-01T00:00:00Z"
        )
        blocks = pd.DataFrame({
            "fold_id": [
                "fold_01"
            ],
            "timestamp_utc": [
                timestamp
            ],
        })
        assets = pd.DataFrame({
            "fold_id": [
                "fold_01"
            ] * 4,
            "timestamp_utc": [
                timestamp
            ] * 4,
            "product_id": [
                "BTC-USD",
                "ETH-USD",
                "SOL-USD",
                "XRP-USD",
            ],
            phase3.PREDICTED_SCORE: [
                0.9,
                0.8,
                0.7,
                0.1,
            ],
            phase3.TERMINAL_NET25: [
                0.0975,
                0.0475,
                0.0175,
                -0.0225,
            ],
        })

        periods, folds = (
            phase3.simulate_candidate(
                blocks,
                assets,
                self._policy(),
                25.0,
            )
        )

        row = periods.iloc[
            0
        ]

        self.assertEqual(
            row[
                "selected_assets"
            ],
            "BTC-USD|ETH-USD|SOL-USD",
        )
        self.assertAlmostEqual(
            float(
                row[
                    "turnover"
                ]
            ),
            0.60,
        )
        self.assertAlmostEqual(
            float(
                row[
                    "cash_weight"
                ]
            ),
            0.40,
        )

        expected_gross = (
            0.20 * 0.10
            + 0.20 * 0.05
            + 0.20 * 0.02
        )
        expected_cost = (
            0.60
            * 25.0
            / 10000.0
        )

        self.assertAlmostEqual(
            float(
                row[
                    "gross_return"
                ]
            ),
            expected_gross,
        )
        self.assertAlmostEqual(
            float(
                row[
                    "net_return"
                ]
            ),
            expected_gross
            - expected_cost,
        )
        self.assertEqual(
            len(
                folds
            ),
            1,
        )

    def test_shared_v3_confirm2_and_xrp_exclusion(self):
        timestamps = pd.to_datetime([
            "2026-01-01T00:00:00Z",
            "2026-01-08T00:00:00Z",
        ])

        blocks = pd.DataFrame({
            "fold_id": [
                "fold_01",
                "fold_01",
            ],
            "timestamp_utc": timestamps,
        })

        rows = []
        for timestamp in timestamps:
            for product, gross in (
                ("BTC-USD", 0.10),
                ("ETH-USD", 0.20),
                ("SOL-USD", 0.00),
                ("XRP-USD", 1.00),
            ):
                rows.append({
                    "fold_id": "fold_01",
                    "timestamp_utc": timestamp,
                    "product_id": product,
                    phase3.TERMINAL_NET25: (
                        gross
                        - 0.0025
                    ),
                })

        assets = pd.DataFrame(
            rows
        )

        shared = pd.DataFrame({
            "timestamp_utc": timestamps,
            "predicted_label": [
                "ALT",
                "ALT",
            ],
        })

        controls = (
            phase3.simulate_controls(
                blocks,
                assets,
                shared,
                25.0,
            )
        )

        row = controls.iloc[
            0
        ]

        first_btc = 0.10
        second_alt = (
            0.20
            + 0.00
        ) / 2.0
        second_alt_after_switch_cost = (
            second_alt
            - 0.0025
        )

        expected_v3 = (
            (
                1.0
                + first_btc
            )
            * (
                1.0
                + second_alt_after_switch_cost
            )
            - 1.0
        )

        self.assertAlmostEqual(
            float(
                row[
                    "shared_v3_net_return"
                ]
            ),
            expected_v3,
        )

        self.assertLess(
            float(
                row[
                    "shared_v3_net_return"
                ]
            ),
            (
                1.10
                * 1.9975
                - 1.0
            ),
        )

    def test_all_eight_portfolio_gates_can_pass(self):
        fold_ids = [
            f"fold_{index:02d}"
            for index in range(
                1,
                9,
            )
        ]

        primary = pd.DataFrame({
            "cost_bps": 25.0,
            "fold_id": fold_ids,
            "net_return": [
                0.05,
                0.04,
                0.06,
                0.03,
                0.05,
                0.04,
                0.03,
                0.02,
            ],
            "maximum_drawdown": [
                -0.05
            ] * 8,
            "total_turnover": [
                2.0
            ] * 8,
            "total_transaction_cost": [
                0.005
            ] * 8,
            "mean_cash_weight": [
                0.40
            ] * 8,
            "mean_crypto_weight": [
                0.60
            ] * 8,
        })

        stress = primary.copy()
        stress[
            "cost_bps"
        ] = 50.0
        stress[
            "net_return"
        ] = stress[
            "net_return"
        ] - 0.005

        folds = pd.concat(
            [
                primary,
                stress,
            ],
            ignore_index=True,
        )

        controls = pd.DataFrame({
            "cost_bps": (
                [25.0] * 8
                + [50.0] * 8
            ),
            "fold_id": (
                fold_ids
                + fold_ids
            ),
            "shared_v3_net_return": (
                [0.00] * 16
            ),
            "shared_v3_maximum_drawdown": (
                [-0.10] * 16
            ),
            "btc_return": (
                [-0.01] * 16
            ),
            "btc_maximum_drawdown": (
                [-0.12] * 16
            ),
        })

        _, _, result = (
            phase3.summarize_and_gate(
                folds,
                controls,
                self._selection_gates(),
                25.0,
                50.0,
            )
        )

        self.assertEqual(
            result[
                "passed_gate_count"
            ],
            8,
        )
        self.assertEqual(
            result[
                "total_gate_count"
            ],
            8,
        )
        self.assertEqual(
            result[
                "status"
            ],
            "QUALIFIES_FOR_HUMAN_REVIEW",
        )

    def test_single_failed_gate_blocks_advancement(self):
        fold_ids = [
            f"fold_{index:02d}"
            for index in range(
                1,
                9,
            )
        ]

        primary = pd.DataFrame({
            "cost_bps": 25.0,
            "fold_id": fold_ids,
            "net_return": [
                -0.01,
                -0.01,
                -0.01,
                -0.01,
                0.05,
                0.05,
                0.05,
                0.05,
            ],
            "maximum_drawdown": [
                -0.05
            ] * 8,
            "total_turnover": [
                2.0
            ] * 8,
            "total_transaction_cost": [
                0.005
            ] * 8,
            "mean_cash_weight": [
                0.40
            ] * 8,
            "mean_crypto_weight": [
                0.60
            ] * 8,
        })

        stress = primary.copy()
        stress[
            "cost_bps"
        ] = 50.0
        stress[
            "net_return"
        ] = 0.01

        folds = pd.concat(
            [
                primary,
                stress,
            ],
            ignore_index=True,
        )

        controls = pd.DataFrame({
            "cost_bps": (
                [25.0] * 8
                + [50.0] * 8
            ),
            "fold_id": (
                fold_ids
                + fold_ids
            ),
            "shared_v3_net_return": (
                [-0.10] * 16
            ),
            "shared_v3_maximum_drawdown": (
                [-0.10] * 16
            ),
            "btc_return": (
                [-0.10] * 16
            ),
            "btc_maximum_drawdown": (
                [-0.10] * 16
            ),
        })

        _, _, result = (
            phase3.summarize_and_gate(
                folds,
                controls,
                self._selection_gates(),
                25.0,
                50.0,
            )
        )

        self.assertFalse(
            result[
                "gate_positive_fold_fraction_gte_80pct"
            ]
        )
        self.assertNotEqual(
            result[
                "status"
            ],
            "QUALIFIES_FOR_HUMAN_REVIEW",
        )

    def test_phase2_permission_is_required(self):
        contract = {
            "research_version": (
                phase3.RESEARCH_VERSION
            ),
            "future_holdout_start_utc": (
                phase3.HOLDOUT.isoformat()
            ),
            "frozen_policy_for_later_simulation": (
                self._policy()
            ),
            "selection_gates": (
                self._selection_gates()
            ),
        }

        gate_result = {
            "passed_predictive_gate_count": 3,
            "total_predictive_gate_count": 4,
            "all_predictive_gates_pass": False,
            "status": (
                "STOP_BEFORE_PORTFOLIO_SIMULATION"
            ),
        }

        manifest = {
            "research_version": (
                phase3.RESEARCH_VERSION
            ),
            "predictive_gate_status": (
                "STOP_BEFORE_PORTFOLIO_SIMULATION"
            ),
            "safety": {
                "future_holdout_scored": False,
                "portfolio_simulated": False,
                "model_family_searched": False,
                "secondary_model_fit": False,
                "hyperparameters_tuned": False,
                "predictive_gate_lowered": False,
                "threshold_search_performed": False,
                "model_frozen": False,
                "paper_state_modified": False,
                "brokerage_orders": False,
                "automatic_promotion": False,
            },
        }

        with self.assertRaisesRegex(
            RuntimeError,
            "did not authorize",
        ):
            phase3._validate_contract_and_permission(
                contract,
                gate_result,
                manifest,
            )


if __name__ == "__main__":
    unittest.main()
