"""Contract tests for the isolated Shared Crypto V2 Clean Forward V4 lane."""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from ml.crypto_15m_v2 import forward_service as service
from ml.crypto_15m_v2 import forward_service_v4 as v4


class SharedV2CleanForwardV4Tests(unittest.TestCase):
    def test_configures_isolated_future_lane_with_v3_as_parent(self):
        original = {
            name: getattr(service, name)
            for name in (
                "PHASE5_ROOT", "MODEL_PATH", "MANIFEST_PATH",
                "LEGACY_STATE_PATH", "LEGACY_JOURNAL_PATH", "LEGACY_STATUS_PATH",
                "CLEAN_ROOT", "STATE_PATH", "JOURNAL_PATH", "SHADOW_PATH",
                "SERVICE_STATUS_PATH", "LOCK_PATH", "CLEAN_LANE_MANIFEST_PATH",
                "CLEAN_START", "CLEAN_LANE_ID", "CLEAN_LANE_NAME",
            )
        }
        try:
            v4.configure()
            self.assertEqual(
                service.CLEAN_ROOT,
                Path("data/model/crypto_15m_v2/phase5/clean_forward_v4"),
            )
            self.assertEqual(
                service.LEGACY_JOURNAL_PATH,
                Path(
                    "data/model/crypto_15m_v2/phase5/"
                    "clean_forward_v3/forward_journal.csv"
                ),
            )
            self.assertEqual(
                service.LEGACY_STATE_PATH,
                Path(
                    "data/model/crypto_15m_v2/phase5/"
                    "clean_forward_v3/forward_state.json"
                ),
            )
            self.assertEqual(
                service.CLEAN_START,
                pd.Timestamp("2026-09-23T07:00:00Z"),
            )
            self.assertEqual(
                service.CLEAN_LANE_ID,
                "shared_crypto_v2_clean_forward_v4",
            )
            self.assertNotEqual(
                service.JOURNAL_PATH,
                service.LEGACY_JOURNAL_PATH,
            )
        finally:
            for name, value in original.items():
                setattr(service, name, value)

    def test_main_configures_before_starting_service(self):
        with patch.object(v4, "configure") as configure, patch.object(
            service, "main"
        ) as main:
            v4.main(["--once"])
        configure.assert_called_once_with()
        main.assert_called_once_with(["--once"])


if __name__ == "__main__":
    unittest.main()
