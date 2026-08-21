from __future__ import annotations

import pandas as pd

RESEARCH_VERSION = "stock_v10"
BENCHMARK_SYMBOL = "SPY"
TARGET_HORIZON_SESSIONS = 5

# V10 is a separate research generation. Its future holdout remains untouched
# during all development phases. V8 production/holdout artifacts remain read-only.
FUTURE_HOLDOUT_START_UTC = pd.Timestamp("2026-11-02T00:00:00Z")

# Predeclared decision-time regime definitions for Phase 1.
SPY_TREND_LOOKBACK = 20
SPY_VOL_LOOKBACK = 20
SPY_VOL_BASELINE_LOOKBACK = 252
