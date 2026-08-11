"""Versioned V5 experiment contract and artifact locations."""

from pathlib import Path


RESEARCH_VERSION = "v5"
FORWARD_HORIZONS = (5, 10, 20)
PRIMARY_TARGET = "forward_relative_return"
TOP_COUNT = 5

BENCHMARK_SYMBOL = "SPY"
CORE_ALLOCATION = 0.60
STRATEGY_ALLOCATION = 0.40
POSITION_ALLOCATION = STRATEGY_ALLOCATION / TOP_COUNT

# Costs are explicit contract inputs, not values to silently optimize away.
# Phase 2 should run sensitivity analysis around these initial assumptions.
TRANSACTION_COST_BPS_PER_SIDE = 5.0
SLIPPAGE_BPS_PER_SIDE = 5.0

FEATURE_ROOT = Path("data/features/stocks")
OUTPUT_ROOT = Path("data/model/v5")
RESEARCH_PANEL_PATH = OUTPUT_ROOT / "research_panel.parquet"

V5_FEATURE_COLUMNS = (
    "daily_return",
    "return_2d",
    "return_3d",
    "return_5d",
    "return_10d",
    "return_20d",
    "return_60d",
    "price_vs_sma_7",
    "price_vs_sma_20",
    "price_vs_sma_50",
    "price_vs_sma_200",
    "sma_7_vs_sma_20",
    "sma_20_vs_sma_50",
    "sma_50_vs_sma_200",
    "intraday_range",
    "open_close_range",
    "volume_ratio",
    "volume_change_5d",
    "volatility_5d",
    "volatility_20d",
    "volatility_ratio_5_20",
    "trend_20_50",
    "trend_50_200",
    "distance_from_20d_high",
    "distance_from_20d_low",
    "rsi_centered",
)

SCORECARD_METRICS = (
    "cumulative_return",
    "annualized_return",
    "spy_return",
    "excess_return_over_spy",
    "sharpe_ratio",
    "sortino_ratio",
    "maximum_drawdown",
    "volatility",
    "hit_rate",
    "turnover",
    "transaction_costs",
    "number_of_trades",
    "number_of_rebalance_periods",
)

COMPARISON_BASELINES = (
    "spy_buy_and_hold",
    "equal_weight_stock_universe",
    "simple_momentum",
    "frozen_v4_strategy",
)
