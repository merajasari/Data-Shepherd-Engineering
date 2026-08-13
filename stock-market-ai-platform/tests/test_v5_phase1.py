import unittest

import pandas as pd

from ml.v5.phase1 import generate_folds


class V5Phase1Tests(unittest.TestCase):
    def make_panel(self):
        dates = pd.date_range("2020-01-01", "2022-12-30", freq="B", tz="UTC")
        rows = []
        for symbol in ("AAA", "BBB", "CCC"):
            for i, ts in enumerate(dates):
                endpoint = dates[i + 5] if i + 5 < len(dates) else pd.NaT
                labeled = pd.notna(endpoint)
                rows.append(
                    {
                        "symbol": symbol,
                        "timestamp_utc": ts,
                        "feature_complete": True,
                        "is_labeled_5d": labeled,
                        "target_endpoint_utc_5d": endpoint,
                        "forward_relative_return_5d": 0.01 if labeled else float("nan"),
                    }
                )
        return pd.DataFrame(rows)

    def test_purge_requires_endpoint_before_validation_start(self):
        panel = self.make_panel()
        folds = generate_folds(
            panel,
            development_start="2021-07-01",
            holdout_start="2023-01-01",
            validation_months=6,
        )
        first = folds[0]
        self.assertEqual(first["fold_id"], "dev_01")
        self.assertLess(
            pd.Timestamp(first["max_train_target_endpoint_utc"]),
            pd.Timestamp(first["validation_start_utc"]),
        )

    def test_validation_windows_are_chronological_and_nonoverlapping(self):
        panel = self.make_panel()
        folds = generate_folds(
            panel,
            development_start="2021-07-01",
            holdout_start="2023-01-01",
            validation_months=6,
        )
        self.assertGreaterEqual(len(folds), 2)
        previous_end = None
        for fold in folds:
            start = pd.Timestamp(fold["validation_start_utc"])
            end = pd.Timestamp(fold["validation_end_exclusive_utc"])
            self.assertLess(start, end)
            if previous_end is not None:
                self.assertEqual(start, previous_end)
            previous_end = end

    def test_holdout_boundary_is_never_crossed(self):
        panel = self.make_panel()
        folds = generate_folds(
            panel,
            development_start="2021-07-01",
            holdout_start="2022-09-01",
            validation_months=6,
        )
        holdout = pd.Timestamp("2022-09-01", tz="UTC")
        self.assertEqual(
            pd.Timestamp(folds[-1]["validation_end_exclusive_utc"]),
            holdout,
        )
        self.assertLess(
            pd.Timestamp(folds[-1]["actual_validation_end_utc"]),
            holdout,
        )

    def test_incomplete_features_are_excluded(self):
        panel = self.make_panel()
        bad_date = pd.Timestamp("2021-08-02", tz="UTC")
        panel.loc[
            (panel["symbol"] == "AAA") & (panel["timestamp_utc"] == bad_date),
            "feature_complete",
        ] = False
        folds = generate_folds(
            panel,
            development_start="2021-07-01",
            holdout_start="2022-01-01",
            validation_months=6,
        )
        expected_full_rows = int(
            (
                (panel["timestamp_utc"] >= pd.Timestamp("2021-07-01", tz="UTC"))
                & (panel["timestamp_utc"] < pd.Timestamp("2022-01-01", tz="UTC"))
                & panel["is_labeled_5d"]
                & (panel["target_endpoint_utc_5d"] < pd.Timestamp("2022-01-01", tz="UTC"))
            ).sum()
        )
        self.assertEqual(folds[0]["validation_rows"], expected_full_rows - 1)

    def test_duplicate_keys_are_rejected(self):
        panel = self.make_panel()
        panel = pd.concat([panel, panel.iloc[[0]]], ignore_index=True)
        with self.assertRaisesRegex(ValueError, "unique timestamp_utc/symbol"):
            generate_folds(
                panel,
                development_start="2021-07-01",
                holdout_start="2022-01-01",
            )


if __name__ == "__main__":
    unittest.main()
