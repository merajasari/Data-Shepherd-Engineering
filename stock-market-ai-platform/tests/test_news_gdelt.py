import unittest

import pandas as pd

from ml.news_intelligence.gdelt import build_query, canonicalize_export


class GdeltAcquisitionTest(unittest.TestCase):
    def test_query_is_partition_pruned_and_asset_filtered(self):
        sql = build_query("2025-01-01T00:00:00Z", "2025-02-01T00:00:00Z",
                          {"BTC-USD": ("bitcoin",), "ETH-USD": ("ethereum",)})
        self.assertIn("gkg_partitioned", sql)
        self.assertIn("_PARTITIONTIME >=", sql)
        self.assertIn("_PARTITIONTIME <", sql)
        self.assertIn("ARRAY_LENGTH(asset_ids) > 0", sql)

    def test_export_uses_observation_time_and_valid_vectors(self):
        raw = pd.DataFrame([{
            "DATE": 20250101123000, "SourceCommonName": "example.com",
            "DocumentIdentifier": "https://example.com/bitcoin-story",
            "V2Organizations": "Bitcoin Foundation", "V2Persons": "",
            "V2Themes": "ECON_CRYPTOCURRENCY", "V2Tone": "-5.0,1,2,3",
            "asset_ids": '["BTC-USD"]',
        }])
        result = canonicalize_export(raw, "2025-01-02T00:00:00Z")
        self.assertEqual(result.iloc[0]["asset_ids"], ["BTC-USD"])
        self.assertEqual(result.iloc[0]["timestamp_semantics"],
                         "gdelt_first_observed_not_publisher_timestamp")
        self.assertEqual(len(result.iloc[0]["embedding"]), 256)
        self.assertLess(result.iloc[0]["sentiment"], 0)


if __name__ == "__main__":
    unittest.main()
