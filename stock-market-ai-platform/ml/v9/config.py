from __future__ import annotations

import pandas as pd

RESEARCH_VERSION = "stock_v9"
BENCHMARK_SYMBOL = "SPY"
TARGET_HORIZON_SESSIONS = 5

# V9 is a new research track with its own untouched future holdout.  V8's
# Sep-2026 holdout remains sealed and is never used for V9 candidate selection.
FUTURE_HOLDOUT_START_UTC = pd.Timestamp("2026-10-01T00:00:00Z")
