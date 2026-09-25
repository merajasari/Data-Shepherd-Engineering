import unittest

import pandas as pd

from ml.shared_crypto_v19_relative_sleeve_router import phase1


def v15_manifest():
    return {
        "research_version": "shared_crypto_v15_cross_sectional_rank",
        "predictive_gate_status": "ALLOW_POLICY_SIMULATION",
        "passed_predictive_gate_count": 4,
    }


def v15_adjudication():
    return {
        "research_version": "shared_crypto_v15_cross_sectional_rank",
        "status": "REJECT_CURRENT_V15_POLICY_FAMILY",
    }


def v16_contract():
    return {
        "research_version": "shared_crypto_v16_risk_gated_rank",
        "risk_feature_columns": [
            f"risk_feature_{index}"
            for index in range(18)
        ],
    }


def v18_adjudication():
    return {
        "research_version": "shared_crypto_v18_ranker_meta_gate",
        "status": "REJECT_CURRENT_V18_RANKER_META_GATE_HYPOTHESIS",
        "portfolio_simulation_allowed": False,
    }


def predictions():
    products = [
        "BTC-USD",
        "ETH-USD",
        "SOL-USD",
        "XRP-USD",
    ]
    scores = {
        "BTC-USD": 0.65,
        "ETH-USD": 0.90,
        "SOL-USD": 0.80,
        "XRP-USD": 0.70,
    }
    days = [
        (
            pd.Timestamp("2026-01-01T00:00:00Z"),
            {
                "BTC-USD": 0.10,
                "ETH-USD": 0.05,
                "SOL-USD": 0.02,
                "XRP-USD": -0.01,
            },
        ),
        (
            pd.Timestamp("2026-01-02T00:00:00Z"),
            {
                "BTC-USD": 0.02,
                "ETH-USD": 0.10,
                "SOL-USD": 0.08,
                "XRP-USD": 0.06,
            },
        ),
    ]

    rows = []
    for timestamp, terminals in days:
        for product in products:
            rows.append({
                "timestamp_utc": timestamp,
                "product_id": product,
                "fold_id": "fold_01",
                phase1.PREDICTED_SCORE: scores[product],
                phase1.NET_TERMINAL: terminals[product],
                "target_endpoint_utc_7d": (
                    timestamp
                    + pd.to_timedelta(7, unit="D")
                ),
                "eligible_asset_count": 4,
            })

    return pd.DataFrame(rows)


def market_context():
    rows = []
    for day_index, timestamp in enumerate(
        pd.to_datetime([
            "2026-01-01T00:00:00Z",
            "2026-01-02T00:00:00Z",
        ])
    ):
        row = {"timestamp_utc": timestamp}
        for feature_index in range(18):
            row[
                f"risk_feature_{feature_index}"
            ] = (
                0.01 * feature_index
                + 0.001 * day_index
            )
        rows.append(row)
    return pd.DataFrame(rows)


class SharedCryptoV19Phase1Test(
    unittest.TestCase
):
    def build(self):
        return phase1.build_router_dataset(
            predictions(),
            market_context(),
            v15_manifest(),
            v15_adjudication(),
            v16_contract(),
            v18_adjudication(),
        )

    def test_relative_target_is_top3_mean_minus_btc(self):
        dataset, _ = self.build()

        first = dataset.iloc[0]
        expected_top3 = (
            0.05 + 0.02 - 0.01
        ) / 3.0
        expected_excess = (
            expected_top3 - 0.10
        )

        self.assertAlmostEqual(
            float(
                first[
                    phase1.RELATIVE_CONTINUOUS_TARGET
                ]
            ),
            expected_excess,
        )
        self.assertEqual(
            int(
                first[
                    phase1.RELATIVE_BINARY_TARGET
                ]
            ),
            0,
        )
        self.assertEqual(
            int(
                dataset.iloc[1][
                    phase1.RELATIVE_BINARY_TARGET
                ]
            ),
            1,
        )

    def test_btc_relative_diagnostics_are_exact(self):
        dataset, _ = self.build()
        row = dataset.iloc[0]

        self.assertAlmostEqual(
            float(
                row[
                    "router_btc_predicted_rank_score"
                ]
            ),
            0.65,
        )
        self.assertAlmostEqual(
            float(
                row[
                    "router_btc_predicted_rank_fraction"
                ]
            ),
            1.0,
        )
        self.assertAlmostEqual(
            float(
                row[
                    "router_top3_mean_minus_btc_score"
                ]
            ),
            0.15,
        )
        self.assertEqual(
            float(
                row[
                    "router_btc_in_top3"
                ]
            ),
            0.0,
        )

    def test_feature_count_is_34(self):
        _, contract = self.build()

        self.assertEqual(
            len(
                contract[
                    "v18_rank_diagnostic_feature_columns"
                ]
            ),
            11,
        )
        self.assertEqual(
            len(
                contract[
                    "btc_relative_feature_columns"
                ]
            ),
            5,
        )
        self.assertEqual(
            len(
                contract[
                    "market_context_feature_columns"
                ]
            ),
            18,
        )
        self.assertEqual(
            len(
                contract[
                    "model_feature_columns"
                ]
            ),
            34,
        )

    def test_model_and_predictive_gates_are_frozen(self):
        _, contract = self.build()

        model = contract[
            "router_model"
        ]

        self.assertEqual(
            model["primary"],
            "hist_gradient_boosting_classifier",
        )
        self.assertEqual(
            model["class_weight_method"],
            "balanced_sample_weight",
        )
        self.assertEqual(
            contract[
                "predictive_quality_gates"
            ],
            phase1.EXPECTED_PREDICTIVE_GATES,
        )

    def test_no_target_or_future_columns_are_model_features(self):
        _, contract = self.build()

        forbidden = (
            "target",
            "terminal_return",
            "path_utility",
            "future",
            "endpoint",
            "selected_assets",
            "correct",
        )

        self.assertFalse(
            any(
                any(
                    token in feature.lower()
                    for token in forbidden
                )
                for feature in contract[
                    "model_feature_columns"
                ]
            )
        )

    def test_offline_research_safeguards_are_frozen(self):
        _, contract = self.build()

        constraints = contract[
            "research_constraints"
        ]

        self.assertTrue(
            constraints[
                "offline_research_only"
            ]
        )
        self.assertFalse(
            constraints[
                "v15_ranker_refit"
            ]
        )
        self.assertFalse(
            constraints[
                "market_timing_or_cash_gate"
            ]
        )
        self.assertFalse(
            constraints[
                "brokerage_orders"
            ]
        )

    def test_v18_rejection_is_required(self):
        adjudication = v18_adjudication()
        adjudication[
            "status"
        ] = "QUALIFIED_FOR_POLICY_SIMULATION"

        with self.assertRaisesRegex(
            RuntimeError,
            "V18",
        ):
            phase1.build_router_dataset(
                predictions(),
                market_context(),
                v15_manifest(),
                v15_adjudication(),
                v16_contract(),
                adjudication,
            )

    def test_future_holdout_is_rejected(self):
        source = predictions()
        source.loc[
            0,
            "timestamp_utc",
        ] = phase1.HOLDOUT

        with self.assertRaisesRegex(
            RuntimeError,
            "future-holdout",
        ):
            phase1.build_router_dataset(
                source,
                market_context(),
                v15_manifest(),
                v15_adjudication(),
                v16_contract(),
                v18_adjudication(),
            )

    def test_missing_market_context_feature_fails_closed(self):
        context = market_context().drop(
            columns=[
                "risk_feature_17"
            ]
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "market context missing",
        ):
            phase1.build_router_dataset(
                predictions(),
                context,
                v15_manifest(),
                v15_adjudication(),
                v16_contract(),
                v18_adjudication(),
            )


if __name__ == "__main__":
    unittest.main()
