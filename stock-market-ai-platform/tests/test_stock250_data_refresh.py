import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from ml import run_stock250_data_refresh as module


class Stock250DataRefreshTests(
    unittest.TestCase
):
    def test_uses_same_rolling_ledger_as_legacy_refresh(self):
        from ml import run_v5_data_refresh

        self.assertEqual(
            module.REQUEST_LEDGER_PATH,
            run_v5_data_refresh.REQUEST_LEDGER_PATH,
        )

    @patch.object(
        module,
        "prune_request_ledger",
    )
    @patch.object(
        module,
        "available_request_budget",
        return_value=(0, 500),
    )
    @patch.object(
        module,
        "run_incremental_refresh",
    )
    def test_quota_wait_does_not_touch_data(
        self,
        refresh,
        _budget,
        prune,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            result = module.run_stock250_refresh(
                hourly_request_limit=500,
                ledger_path=Path(tmp) / "ledger.json",
            )

        self.assertEqual(
            result,
            "quota_wait",
        )

        refresh.assert_not_called()
        prune.assert_called_once()

    @patch.object(
        module,
        "rebuild_and_validate_spark_features",
    )
    @patch.object(
        module,
        "propagate_price_layers",
    )
    @patch.object(
        module,
        "prune_request_ledger",
    )
    @patch.object(
        module,
        "available_request_budget",
        return_value=(151, 0),
    )
    @patch.object(
        module,
        "run_incremental_refresh",
    )
    def test_partial_bronze_defers_spark(
        self,
        refresh,
        _budget,
        _prune,
        propagate,
        rebuild,
    ):
        refresh.return_value = {
            "target_date_utc": "2026-10-19",
            "requests_used": 151,
            "updated_symbols": [
                "ABNB",
                "ACN",
            ],
            "complete": False,
        }

        result = module.run_stock250_refresh(
            hourly_request_limit=500,
            max_requests=151,
            ledger_path=Path(
                "/tmp/test-stock250-ledger.json"
            ),
            client=Mock(),
        )

        self.assertEqual(
            result,
            "bronze_partial",
        )

        propagate.assert_called_once_with(
            [
                "ABNB",
                "ACN",
            ]
        )

        rebuild.assert_not_called()

    @patch.object(
        module,
        "rebuild_and_validate_spark_features",
    )
    @patch.object(
        module,
        "propagate_price_layers",
    )
    @patch.object(
        module,
        "prune_request_ledger",
    )
    @patch.object(
        module,
        "available_request_budget",
        return_value=(500, 0),
    )
    @patch.object(
        module,
        "run_incremental_refresh",
    )
    def test_complete_bronze_rebuilds_spark_but_not_models(
        self,
        refresh,
        _budget,
        _prune,
        propagate,
        rebuild,
    ):
        refresh.return_value = {
            "target_date_utc": "2026-10-19",
            "requests_used": 151,
            "updated_symbols": [
                "ABNB",
                "ACN",
            ],
            "complete": True,
        }

        result = module.run_stock250_refresh(
            hourly_request_limit=500,
            ledger_path=Path(
                "/tmp/test-stock250-ledger.json"
            ),
            client=Mock(),
        )

        self.assertEqual(
            result,
            "rebuilt",
        )

        propagate.assert_called_once_with(
            [
                "ABNB",
                "ACN",
            ]
        )

        rebuild.assert_called_once_with()

        self.assertFalse(
            hasattr(
                module,
                "refresh_v8_production",
            )
        )

        self.assertFalse(
            hasattr(
                module,
                "refresh_v10_production",
            )
        )

    def test_contract_is_250_plus_spy(self):
        self.assertEqual(
            module.INVESTABLE_CANDIDATE_COUNT,
            250,
        )

        self.assertEqual(
            module.DATA_SYMBOL_COUNT,
            251,
        )


if __name__ == "__main__":
    unittest.main()
