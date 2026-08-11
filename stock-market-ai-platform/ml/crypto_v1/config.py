"""Versioned Crypto V1 experiment contract and artifact locations."""

from pathlib import Path


RESEARCH_VERSION = "crypto_v1"
PROVIDER_NAME = "coinbase_exchange"
BENCHMARK_PRODUCT = "BTC-USD"
QUOTE_CURRENCY = "USD"

# A deliberately compact, liquid research universe. Membership is not proof
# of historical eligibility; the panel must apply the per-date rules below.
CRYPTO_UNIVERSE = (
    "BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "DOGE-USD",
    "ADA-USD", "AVAX-USD", "LINK-USD", "LTC-USD", "BCH-USD",
    "DOT-USD", "UNI-USD", "AAVE-USD", "ATOM-USD", "NEAR-USD",
    "ICP-USD", "FIL-USD", "ETC-USD", "XLM-USD", "HBAR-USD",
    "SHIB-USD", "SUI-USD", "OP-USD", "ARB-USD", "INJ-USD",
)

FORWARD_HORIZONS_DAYS = (1, 3, 7)
PRIMARY_TARGET = "forward_return_relative_to_btc_3d"
TOP_COUNTS = (3, 5)
DEFAULT_TOP_COUNT = 5
REBALANCE_FREQUENCY = "daily"
ALLOW_LEVERAGE = False

# Eligibility is evaluated independently at every timestamp. Phase 2 should
# sensitivity-test these values; neither criterion may use future observations.
MINIMUM_HISTORY_DAYS = 60
LIQUIDITY_LOOKBACK_DAYS = 30
MINIMUM_MEDIAN_DAILY_DOLLAR_VOLUME = 1_000_000.0

TRANSACTION_FEE_BPS_PER_SIDE = 10.0
SLIPPAGE_BPS_PER_SIDE = 5.0

BRONZE_ROOT = Path("data/bronze/crypto")
SILVER_ROOT = Path("data/silver/crypto")
GOLD_ROOT = Path("data/gold/crypto")
FEATURE_ROOT = Path("data/features/crypto")
MODEL_ROOT = Path("data/model/crypto_v1")
RANKING_OUTPUT_PATH = MODEL_ROOT / "rankings.parquet"

SUPPORTED_GRANULARITIES = {"daily": 86400, "hourly": 3600}
DEFAULT_GRANULARITY = "daily"

FEATURE_ROADMAP = (
    "momentum_1d", "momentum_3d", "momentum_7d", "momentum_14d",
    "momentum_30d", "realized_volatility", "volume_change",
    "moving_average_distance", "drawdown", "btc_trend_regime",
    "asset_btc_correlation", "asset_vs_btc_relative_strength",
    "funding_rate_later", "open_interest_later",
    "basis_and_perpetual_signals_later",
)

SCORECARD_METRICS = (
    "cumulative_return", "annualized_return", "btc_return",
    "excess_return_vs_btc", "sharpe", "sortino", "max_drawdown",
    "volatility", "hit_rate", "turnover", "fees", "number_of_trades",
    "rebalance_count",
)
