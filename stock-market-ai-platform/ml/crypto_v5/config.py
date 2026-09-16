from pathlib import Path
import pandas as pd

RESEARCH_VERSION = "crypto_v5"
SOURCE_PANEL = Path("data/research/crypto_ten_year/reconstruction/crypto_v2/labeled_panel.parquet")
MODEL_ROOT = Path("data/research/crypto_ten_year/reconstruction/crypto_v5")
PHASE1_ROOT = MODEL_ROOT / "phase1"
FUTURE_HOLDOUT_START_UTC = pd.Timestamp("2026-09-16T00:00:00Z")
PRIMARY_HORIZON_DAYS = 3
CONTROL_HORIZONS_DAYS = (1, 7)
ALL_HORIZONS_DAYS = (1, 3, 7)
MIN_NON_BTC_ASSETS = 10
BTC_PRODUCT = "BTC-USD"
ROUND_TRIP_COST_BPS = (10.0, 25.0, 50.0)
PRIMARY_COST_BPS = 25.0
MINIMUM_HOLD_DAYS = 3
SWITCH_CONFIDENCE_MARGIN = 0.10
MAX_TURNOVER_PER_REBALANCE = 0.60
ALLOCATION_TEMPLATES = {
    "RISK_ON": {"BTC": 0.30, "ALT": 0.60, "CASH": 0.10},
    "DEFENSIVE": {"BTC": 0.40, "ALT": 0.10, "CASH": 0.50},
    "CASH": {"BTC": 0.00, "ALT": 0.00, "CASH": 1.00},
}
