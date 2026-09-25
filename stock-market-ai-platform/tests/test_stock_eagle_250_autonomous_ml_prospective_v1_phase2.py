import unittest

import pandas as pd

from ml.stock_eagle_250_autonomous_ml_prospective_v1.phase1 import (
    EXPECTED_CANDIDATE_ORDER,
    load_contract,
)
from ml.stock_eagle_250_autonomous_ml_prospective_v1.phase2 import (
    DEVELOPMENT_END,
    GUARD_START,
    MAX_ENDPOINT,
    PROSPECTIVE_START,
    _candidate_modules,
    validate_training_frame,
)


def training_frame():
    rows = []
    for date in pd.date_range(
        "2026-09-01",
        "2026-09-15",
        freq="B",
        tz="UTC",
    ):
        for index in range(2):
            rows.append({
                "timestamp_utc": date,
                "symbol": f"S{index}",
                "target_endpoint_utc_5d":
                    min(
                        date + pd.Timedelta(days=7),
                        MAX_ENDPOINT,
                    ),
            })
    return pd.DataFrame(rows)


class StockEagle250AutonomousMLProspectiveV1Phase2Test(
    unittest.TestCase
):
    def test_training_frame_stays_before_guard_and_prospective_boundary(self):
        summary = validate_training_frame(
            training_frame()
        )
        self.assertEqual(
            summary["guard_band_rows_read"],
            0,
        )
        self.assertEqual(
            summary["prospective_rows_read"],
            0,
        )
        self.assertLessEqual(
            pd.Timestamp(
                summary[
                    "training_decision_end_utc"
                ]
            ),
            DEVELOPMENT_END,
        )
        self.assertLessEqual(
            pd.Timestamp(
                summary[
                    "training_target_endpoint_max_utc"
                ]
            ),
            MAX_ENDPOINT,
        )

    def test_guard_band_or_future_row_fails_closed(self):
        frame = training_frame()
        guard = frame.iloc[[0]].copy()
        guard["timestamp_utc"] = GUARD_START
        bad = pd.concat(
            [frame, guard],
            ignore_index=True,
        )
        with self.assertRaisesRegex(
            RuntimeError,
            "guard_band_decision_row|decision_after_development_end",
        ):
            validate_training_frame(bad)

        future = frame.iloc[[0]].copy()
        future["timestamp_utc"] = PROSPECTIVE_START
        bad = pd.concat(
            [frame, future],
            ignore_index=True,
        )
        with self.assertRaisesRegex(
            RuntimeError,
            "decision_after_development_end|prospective_decision_row",
        ):
            validate_training_frame(bad)

    def test_all_three_candidate_training_implementations_are_fixed(self):
        contract = load_contract()
        ids = tuple(
            row["candidate_id"]
            for row in contract["candidate_snapshots"]
        )
        self.assertEqual(
            ids,
            EXPECTED_CANDIDATE_ORDER,
        )

        expected_components = {
            "autonomous_ml_v1": 3,
            "autonomous_ml_v2": 4,
            "autonomous_ml_v3": 4,
        }
        for candidate_id in ids:
            phase1_module, phase2_module, count = (
                _candidate_modules(candidate_id)
            )
            self.assertEqual(
                count,
                expected_components[candidate_id],
            )
            self.assertTrue(
                callable(
                    phase2_module.inner_meta_training_rows
                )
            )
            self.assertTrue(
                callable(
                    phase2_module.fit_meta_allocator
                )
            )
            self.assertTrue(
                callable(
                    phase2_module.fit_base_models
                )
            )
            self.assertIsInstance(
                phase1_module.load_contract(),
                dict,
            )

    def test_contract_forbids_retraining_and_automatic_selection(self):
        contract = load_contract()
        self.assertFalse(
            contract["snapshot_build"][
                "post_snapshot_retraining_during_evaluation"
            ]
        )
        protocol = contract["prospective_protocol"]
        self.assertFalse(
            protocol["automatic_winner_selection"]
        )
        self.assertFalse(
            protocol["automatic_model_promotion"]
        )
        self.assertFalse(
            protocol[
                "new_architecture_from_results_before_formal_review"
            ]
        )


if __name__ == "__main__":
    unittest.main()
