import importlib.util
import tempfile
import unittest
from datetime import date
from pathlib import Path
import sys

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_INGESTION = PROJECT_ROOT / "data-ingestion"

if str(DATA_INGESTION) not in sys.path:
    sys.path.insert(
        0,
        str(DATA_INGESTION),
    )

spec = importlib.util.spec_from_file_location(
    "tiingo_stock250_incremental",
    DATA_INGESTION
    / "tiingo_stock250_incremental.py",
)

module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FakeClient:
    def __init__(self, frames):
        self.frames = frames
        self.calls = []

    def get_daily_prices(
        self,
        symbol,
        start_date,
        end_date,
    ):
        self.calls.append(
            (
                symbol,
                start_date,
                end_date,
            )
        )

        return self.frames[
            symbol
        ].copy()


def price_frame(
    symbol,
    timestamp,
    close=1.0,
):
    return pd.DataFrame(
        [
            {
                "symbol": symbol,
                "timestamp": timestamp,
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": 1,
                "vwap": None,
            }
        ]
    )


class TiingoStock250IncrementalTests(
    unittest.TestCase
):
    def test_real_contract_is_250_plus_spy(self):
        symbols = module.contracted_symbols()

        self.assertEqual(
            len(symbols),
            251,
        )

        self.assertEqual(
            len(set(symbols)),
            251,
        )

        self.assertEqual(
            symbols[-1],
            "SPY",
        )

        self.assertEqual(
            len(
                [
                    s
                    for s in symbols
                    if s != "SPY"
                ]
            ),
            250,
        )

    def test_merge_prefers_incoming_overlap(self):
        existing = pd.DataFrame(
            [
                {
                    "symbol": "AAA",
                    "timestamp": 1,
                    "close": 10.0,
                },
                {
                    "symbol": "AAA",
                    "timestamp": 2,
                    "close": 20.0,
                },
            ]
        )

        incoming = pd.DataFrame(
            [
                {
                    "symbol": "AAA",
                    "timestamp": 2,
                    "close": 21.0,
                },
                {
                    "symbol": "AAA",
                    "timestamp": 3,
                    "close": 30.0,
                },
            ]
        )

        out = module.merge_price_frames(
            existing,
            incoming,
        )

        self.assertEqual(
            out["timestamp"].tolist(),
            [1, 2, 3],
        )

        self.assertEqual(
            out.loc[
                out["timestamp"] == 2,
                "close",
            ].iloc[0],
            21.0,
        )

    def test_budget_is_total_including_spy_and_resumes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            bronze_root = root / "bronze"
            state_path = root / "state.json"

            original_get_symbols = (
                module.get_stock_250_data_symbols
            )

            try:
                module.get_stock_250_data_symbols = (
                    lambda: [
                        "AAA",
                        "BBB",
                        "SPY",
                    ]
                )

                original_candidate_count = (
                    module.INVESTABLE_CANDIDATE_COUNT
                )

                original_data_count = (
                    module.DATA_SYMBOL_COUNT
                )

                module.INVESTABLE_CANDIDATE_COUNT = 2
                module.DATA_SYMBOL_COUNT = 3

                old_ts = 1_700_000_000_000
                new_ts = 1_700_086_400_000

                for symbol in [
                    "AAA",
                    "BBB",
                    "SPY",
                ]:
                    path = module.bronze_file(
                        symbol,
                        bronze_root,
                    )

                    path.parent.mkdir(
                        parents=True,
                        exist_ok=True,
                    )

                    price_frame(
                        symbol,
                        old_ts,
                    ).to_csv(
                        path,
                        index=False,
                    )

                frames = {
                    symbol: price_frame(
                        symbol,
                        new_ts,
                        close=2.0,
                    )
                    for symbol in [
                        "AAA",
                        "BBB",
                        "SPY",
                    ]
                }

                client = FakeClient(frames)

                first = (
                    module.run_incremental_refresh(
                        max_requests=2,
                        today=date(
                            2026,
                            10,
                            20,
                        ),
                        client=client,
                        bronze_root=bronze_root,
                        state_path=state_path,
                    )
                )

                self.assertEqual(
                    first["requests_used"],
                    2,
                )

                self.assertFalse(
                    first["complete"]
                )

                self.assertEqual(
                    len(
                        first[
                            "remaining_symbols"
                        ]
                    ),
                    1,
                )

                second = (
                    module.run_incremental_refresh(
                        max_requests=2,
                        today=date(
                            2026,
                            10,
                            20,
                        ),
                        client=client,
                        bronze_root=bronze_root,
                        state_path=state_path,
                    )
                )

                self.assertTrue(
                    second["complete"]
                )

                self.assertEqual(
                    second[
                        "remaining_symbols"
                    ],
                    [],
                )

                self.assertEqual(
                    module.latest_timestamp_ms(
                        "AAA",
                        bronze_root,
                    ),
                    new_ts,
                )

                self.assertEqual(
                    module.latest_timestamp_ms(
                        "BBB",
                        bronze_root,
                    ),
                    new_ts,
                )

                self.assertEqual(
                    module.latest_timestamp_ms(
                        "SPY",
                        bronze_root,
                    ),
                    new_ts,
                )

                self.assertFalse(
                    second["v8_modified"]
                )

                self.assertFalse(
                    second["v10_modified"]
                )

                self.assertFalse(
                    second[
                        "holdout_evidence_modified"
                    ]
                )

                self.assertFalse(
                    second["brokerage_orders"]
                )

            finally:
                module.get_stock_250_data_symbols = (
                    original_get_symbols
                )

                module.INVESTABLE_CANDIDATE_COUNT = (
                    original_candidate_count
                )

                module.DATA_SYMBOL_COUNT = (
                    original_data_count
                )

    def test_state_path_is_separate_from_v5(self):
        self.assertEqual(
            module.STATE_PATH,
            Path(
                "data/live/"
                "stock250_eod_refresh_state.json"
            ),
        )

        self.assertNotEqual(
            module.STATE_PATH,
            Path(
                "data/live/"
                "v5_eod_refresh_state.json"
            ),
        )


if __name__ == "__main__":
    unittest.main()
