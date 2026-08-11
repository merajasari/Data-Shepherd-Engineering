# Stock Market AI Platform — Project Handoff

## Purpose
Continuity handoff for a new ChatGPT session. Read this file, inspect the repository, treat the repository as authoritative if anything here is stale, and continue from **Next Task**.

## Repository
Project: `stock-market-ai-platform`
Branch used during this work: `feature/paper-trading`

Recent commits:
- `0b76d66` — Build V4 cross-sectional strategy and paper trading workflow
- `e39769b` — Ignore local source backup files
- `82aaac2` — Add daily V4 data refresh and paper trading pipeline

The working tree was clean after `82aaac2`.

## Architecture
Tiingo → Bronze → Silver → Gold → Feature layer → V4 ranking → Portfolio decision → paper-trading state.

The V4 ML universe contains 26 stocks. SPY is deliberately outside the V4 universe and is maintained separately as the portfolio core.

## Frozen Strategy
Strategy name: `spy_core_v4_overlay`

Allocation:
- SPY core: 60%
- V4 overlay: 40%
- Five V4 positions at 8% each

SPY remains the permanent core. The V4 sleeve rotates according to the latest top-five ranking.

The V4 model is FROZEN during forward paper testing. The daily pipeline must not automatically retrain V4 or rebuild its training dataset.

## V4 Universe
Configured in `data-ingestion/symbols.py`:

AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA, AVGO, AMD, ORCL, CRM, JPM, BAC, V, MA, WMT, COST, HD, JNJ, UNH, LLY, XOM, CVX, CAT, NFLX, DIS.

SPY is not in this list.

## V4 Model / Dataset
Dataset builder: `ml/build_v4_dataset.py`
Generated dataset: `data/model/v4_cross_section.parquet`
Training script: `ml/train_model_v4.py`
Model artifact: `models/cross_section_model_v4.pkl`

Observed dataset:
- 2,455 trading dates
- 63,830 rows
- 12,275 positive targets
- 19.23% positive rate
- 31 columns
- 26 model features

Walk-forward validation:
- Fold 1 Precision@5 31.43%, selected 5-day return 1.08%
- Fold 2 Precision@5 27.84%, selected 5-day return 0.76%
- Fold 3 Precision@5 28.90%, selected 5-day return 0.87%
- Fold 4 Precision@5 28.19%, selected 5-day return 0.44%
- Mean Precision@5 29.09%
- Random baseline 19.23%
- Mean selected 5-day return 0.79%

## V4 Portfolio Backtest
Backtester: `ml/backtest_portfolio_v4.py`

Observed results:
- Starting capital: $100,000
- Final equity: $248,040.19
- Total return: 148.04%
- CAGR: 9.74%
- Maximum drawdown: -35.79%
- Completed trades: 960
- Win rate: 53.33%
- Average trade return: 0.58%
- Average positions: 1.96
- Capital utilization: 39.10%
- Period: 2016-10-25 through 2026-08-03

## 60% SPY + 40% V4 Backtest
Observed:
- Total return: 247.32%
- CAGR: 13.59%
- Max drawdown: -24.13%
- Calmar: 0.563
- Period: 2016-10-25 through 2026-08-03

Reference:
- SPY CAGR 15.64%, drawdown -33.70%
- V4 CAGR 9.74%, drawdown -35.79%

The blend materially reduced historical drawdown.

## Ranking Service
`webapp/services/ranking_service_v4.py`
Main function: `rank_latest_universe()`

Earlier top five:
AMD, ORCL, CRM, MSFT, LLY.

After the latest full daily refresh:
AMD, ORCL, CRM, MSFT, AMZN.

This caused LLY to exit and AMZN to enter.

## Paper Trading Service
`webapp/services/paper_trading_service.py`

Major functions at last checkpoint:
- `utc_now`
- `default_state`
- `save_state`
- `load_state`
- `get_execution_price`
- `get_portfolio_summary`
- `evaluate_trade_candidates`
- `build_target_portfolio_plan`
- `initialize_strategy_positions`
- `build_rebalance_plan`
- `execute_rebalance`

A temporary duplicate `build_rebalance_plan()` was removed and the module compiled successfully.

Runtime state: `data/paper_trading/portfolio.json` (ignored by Git).

Initial portfolio:
SPY 60%; AMD, ORCL, CRM, MSFT, LLY at 8% each.

Initial simulated execution produced approximately $99,900.10 equity, six open positions, six trade records, and $0 cash.

## First Forward Rebalance
The first forward membership change was LLY → AMZN.

The system correctly generated:
- SELL LLY
- BUY AMZN

After execution:
- Open positions: 6
- Trade records: 8
- Cash: $0
- Equity: approximately $99,884.13
- Realized P&L: approximately -$15.98
- Unrealized P&L: approximately -$99.88
- Total return: approximately -0.1159%

Positions: SPY, AMD, AMZN, CRM, MSFT, ORCL.

This validated ranking → rebalance decision → simulated execution end-to-end.

## Paper Cycle Runner
`ml/run_paper_cycle_v4.py`

Workflow:
1. Load latest V4 ranking.
2. Build rebalance plan.
3. Identify BUY/SELL actions.
4. Execute simulated rebalance when required.
5. Print portfolio state.

Repeated runs with unchanged rankings correctly create no duplicate trades.

## SPY Core Ingestion
`data-ingestion/tiingo_core_ingest.py`

SPY refreshes separately, then flows through generic Silver, Gold, and Feature pipelines. Those pipelines therefore process 27 datasets: 26 V4 stocks plus SPY. SPY remains outside the V4 candidate universe.

## Daily Pipeline
`ml/run_daily_v4_pipeline.py`

Stages:
1. 26-stock Tiingo ingestion
2. SPY core ingestion
3. Silver pipeline
4. Gold pipeline
5. Feature pipeline
6. V4 paper cycle

The complete pipeline ran successfully in approximately 51.8 seconds and detected/executed the LLY → AMZN rotation.

## Git / Runtime Policy
Generated/runtime data should not be committed. `.gitignore` covers generated data layers, model/runtime data, paper-trading state, logs, PID state, model pickle artifacts, and local source backups.

Legacy V3/research scripts remain. Do not delete them without inspecting their purpose.

## Trading Boundary
PAPER TRADING ONLY. The current system does not place real brokerage orders. Do not add live brokerage execution without explicit authorization and a separate design/safety review.

## Engineering Principles
1. Freeze V4 during forward testing.
2. Keep SPY outside the V4 ML universe.
3. Separate mutable portfolio state from historical observations.
4. Avoid duplicate trades when rankings do not change.
5. Treat repository code as authoritative over this handoff.

# NEXT TASK — Append-only Forward Journal
Create an append-only paper-trading journal.

Proposed service:
`webapp/services/paper_journal_service.py`

Proposed runtime file:
`data/paper_trading/journal.jsonl`

The journal remains ignored by Git and does NOT replace `portfolio.json`.

Each successful paper cycle should append exactly one observation containing at least:
- timestamp
- portfolio equity
- cash
- market value
- realized P&L
- unrealized P&L
- total return
- open-position count
- cumulative trade count
- latest V4 top-five symbols
- BUY/SELL actions generated during that cycle

Recommended sequence:
1. Inspect active branch, Git status/history, and current repository code.
2. Read `ml/run_paper_cycle_v4.py`.
3. Read `webapp/services/paper_trading_service.py`.
4. Create `webapp/services/paper_journal_service.py`.
5. Implement append-only JSONL writing.
6. Wire it into `ml/run_paper_cycle_v4.py`.
7. Record both rebalance and no-rebalance cycles.
8. Compile affected files.
9. Run the paper cycle and inspect the final journal line.
10. Run again with unchanged ranking.
11. Confirm no duplicate trades but a second journal observation.
12. Run the full daily wrapper.
13. Commit source-code changes only.

## Longer-term Forward Test
Accumulate genuine out-of-sample observations while V4 stays frozen. Eventually evaluate forward CAGR, drawdown, volatility, Sharpe, Calmar, turnover, transaction-cost drag, Precision@5, selected-stock returns, SPY-relative performance, blend performance, and ranking stability.

## Instructions for a New Session
Read this handoff completely, connect to GitHub, inspect the active branch/history/status, and read the actual current versions of:
- `data-ingestion/symbols.py`
- `webapp/services/ranking_service_v4.py`
- `webapp/services/paper_trading_service.py`
- `ml/run_paper_cycle_v4.py`
- `ml/run_daily_v4_pipeline.py`

Verify the handoff against the repository. Repository code wins if there are discrepancies. Then continue with the append-only journal using small, testable changes. Compile/test before committing and preserve the frozen V4 strategy unless the research objective is explicitly changed.
