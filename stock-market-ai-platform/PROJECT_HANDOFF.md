# Stock Market AI Platform — Project Handoff

## Purpose
Continuity handoff for a new ChatGPT session. Read this file, inspect the repository, treat the repository as authoritative if anything here is stale, and continue from **Next Task**.

## Repository
Project: `stock-market-ai-platform`
Current branch: `feature/paper-trading`

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

# HISTORICAL NEXT TASK — Append-only Forward Journal (completed)
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

# Progress Since the Previous Handoff

This section supersedes the stale historical next task above and records completed work through Crypto V1 Phase 3. Future work is explicitly separated under **Recommended Next Steps**.

## Repository and Stock Research State

As inspected on 2026-08-11 (America/Los_Angeles), the active branch is `feature/paper-trading`, tracking `origin/feature/paper-trading`. Local `HEAD` and the remote-tracking ref both point to pushed checkpoint `0e16022` (`0e160221f33528ced4d0f289e0725e60c1e22f72`), with no ahead/behind indicator. The tree was clean before this handoff-only edit. `origin/main` remains at `3f0d86f`; this work is not merged to main.

Stock V4 remains the frozen production/paper control. The journal, every-cycle recording, forward report, SPY benchmark, and dashboard work were completed in `e742522`, `dade8ef`, `87b13c8`, `96ccd20`, and `c6252a9`. Do not retrain or overwrite its model, dataset, 26-stock universe, ranking logic, paper state, journal, report, or monitoring during forward testing. Stock V5 and Crypto V1 have separate modules, ingestion entry points, contracts, and model roots; neither is called by the V4 daily runner. Crypto writes only under crypto-specific data paths and has no order methods. V4 remains paper-only.

Stock V5 Phase 1 is complete and pushed at `effecc1`. It added an isolated 100-stock universe, separate Tiingo Bronze ingestion, config/experiment contracts, 5/10/20-trading-day stock-minus-SPY targets, multi-horizon panel preparation, chronological purge/embargo rules, untouched-test policy, and contract tests. Its intended portfolio is 60% SPY plus a 40% equal-weight Top 5 sleeve, without sharing V4 runtime state. Full population, modeling, evaluation, and promotion remain future work; partial panels are smoke-test-only.

## Crypto V1 Phase 1 — Coinbase Foundation

Phase 1 is complete and pushed at `916135c`. It established a provider-neutral `MarketDataProvider`/`Candle` boundary, public research-only Coinbase Exchange adapter, versioned contracts, BTC benchmark, ranking-consumer boundary, isolated storage, and daily/hourly CLI ingestion with inclusive start/exclusive end.

The exact 25-pair universe is: `BTC-USD, ETH-USD, SOL-USD, XRP-USD, DOGE-USD, ADA-USD, AVAX-USD, LINK-USD, LTC-USD, BCH-USD, DOT-USD, UNI-USD, AAVE-USD, ATOM-USD, NEAR-USD, ICP-USD, FIL-USD, ETC-USD, XLM-USD, HBAR-USD, SHIB-USD, SUI-USD, OP-USD, ARB-USD, INJ-USD`.

Coinbase caps responses at 300 candles. The adapter chunks at 299 buckets, traverses the half-open interval, filters boundary rows back to `[start,end)`, deduplicates timestamps, sorts ascending, pauses, and retries retryable failures. Daily Bronze is `data/bronze/crypto/coinbase_exchange/daily/<PAIR>/candles.csv` plus `metadata.json`; hourly uses the parallel `hourly/<PAIR>/` root.

## Crypto V1 Phase 2 — Research Data Architecture and Results

Phase 2 is complete and pushed in `8107296` and `c12d958`. Strict Bronze validation checks metadata, UTC/alignment, bounds, order, uniqueness, numeric/OHLC integrity, and gaps. Missing rows are reported, never synthesized or forward-filled. Silver stores canonical sorted unique float64 OHLCV Parquet per pair. Gold preserves one observed candle per asset/date and differing listing histories at `data/gold/crypto/coinbase_exchange/daily/research_panel.parquet`.

Point-in-time eligibility requires 60 days since first observation, complete trailing windows, and trailing 30-day median dollar volume >= $1,000,000. The 22 model features cover exact 1/3/7/14/30-day returns, 7/14/30-day volatility, dollar-volume level/ratio, SMA distances, drawdown, BTC-relative strength, and 14/30-day BTC correlation. Targets are exact 1/3/7-day asset and BTC forward returns, asset-minus-BTC returns, percentile ranks, and Top-3/Top-5 labels; targets are excluded from features. Convention: completed UTC close at t to exact observed UTC close at t+h.

The `c12d958` horizon-specific correction was necessary because requiring all 1/3/7-day targets first wrongly discarded valid short-horizon rows near the dataset end and XRP discontinuity, and could define rank/Top-N labels over a different cross-section. Each authoritative horizon file now filters on its own target and recomputes ranks and Top-3/Top-5 over that exact eligible date/horizon universe. The combined `research_panel.parquet` is audit/compatibility-only.

The Phase 2 manifest now records generation time, source Git hash, universe, eligibility configuration, features/columns, paths, counts/ranges, complete and aggregate Bronze reports, authoritative horizon inputs, and SHA-256 dataset hashes.

Full Coinbase daily ingestion covers inclusive 2020-01-01 through 2026-08-10 (exclusive end 2026-08-11). Manifest results: 25 Bronze files and 48,430 rows; 24 have no gaps. XRP alone has one gap, exactly 904 missing daily intervals after 2021-01-19 and before 2023-07-13, preserved as a Coinbase-source gap; XRP has 1,510 rows. Gold has 48,430 rows from 2020-01-01 through 2026-08-10 UTC. Authoritative research inputs are: 1d 44,323 rows, 2020-02-29–2026-08-09; 3d 44,283 rows, 2020-02-29–2026-08-07; 7d 44,203 rows, 2020-02-29–2026-08-03. The combined all-target reference has 44,203 rows.

The stable Ubuntu environment remains `/opt/venvs/crypto-v1`: Python 3.14.4, pandas 3.0.5, NumPy 2.5.2, PyArrow 25.0.1, scikit-learn 1.9.0, joblib 1.5.3. Fresh verification ran `tests.test_crypto_v1_contract`, `tests.test_crypto_v1_dataset`, and `tests.test_crypto_v1_phase3`: all 24 tests passed in 1.125 seconds. Coverage includes pagination/end exclusivity, strict validation, gap preservation, point-in-time eligibility, exact targets/ranks, future-mutation leakage traps, horizon-specific XRP ranking, chronological purge/holdout rules, train-only preprocessing, metrics, and prediction uniqueness.

## Crypto V1 Phase 3 — Implementation and Evaluation

Phase 3 is complete and pushed at `0e16022`. It predicts cross-sectional BTC-relative forward returns at 1/3/7 days with the frozen 22 features. Learned models are Ridge (alpha 10), Elastic Net (alpha .001, l1_ratio .25), and HistGradientBoosting (150 iterations, learning rate .05, 15 leaves, minimum leaf 20, L2 1). Linear pipelines use training-fold median imputation and scaling; HGB uses training-fold median imputation. Baselines are momentum, deterministic seeded random, and equal score; seed 1729.

Validation uses chronological expanding windows: ten development folds per horizon (half-years from 2021-01-01 through 2025-06-30, then July 2025), followed by an untouched holdout starting 2025-08-01. No holdout result was used for selection/tuning. Each boundary purges h decision days and verifies all training target endpoints precede validation. Holdout ends are 2026-08-09 (1d), 2026-08-07 (3d), and 2026-08-03 (7d). There are 11 folds/horizon, 99 learned model artifacts plus 99 metadata files, 750,378 prediction rows across models/baselines, and 468 summary rows.

Exact key overall metrics (mean rank IC / IC hit rate / top-bottom spread / Top-3 / Top-5 mean realized return) are:

- 1d HGB development: -0.009225 / 0.475194 / 0.001452 / 0.001817 / 0.001217; holdout: -0.004683 / 0.516043 / 0.002096 / 0.001041 / 0.000522.
- 3d HGB development: 0.008436 / 0.503885 / 0.003117 / 0.003259 / 0.003390; holdout: 0.000291 / 0.516129 / -0.001477 / -0.005319 / -0.003105.
- 7d HGB development: 0.002458 / 0.496712 / -0.001082 / 0.004122 / 0.004299; holdout: -0.006032 / 0.516304 / -0.004463 / -0.008099 / -0.008395.
- 7d momentum holdout: 0.041057 / 0.557065 / 0.008863 / -0.002584 / -0.001349.

Ridge/Elastic Net holdout mean IC is negative at every horizon: -0.013915/-0.020601 (1d), -0.021161/-0.031595 (3d), and -0.025460/-0.038181 (7d).

### Phase 3 conclusion

There is **insufficient evidence to proceed to Phase 4 or paper trading**. No learned model has stable positive IC across development and holdout. HGB weakness/non-persistence and negative 3d/7d holdout Top-N returns fail promotion. The notable 7d holdout IC belongs to momentum, yet its Top-3/Top-5 returns are negative. Phase 3 is a completed negative research checkpoint, not a deployable strategy.

## Limitations and Risks

The current-day candidate universe retains survivorship/selection bias despite point-in-time first-observation/liquidity rules. Coinbase listing/suspension history and missing no-trade candles matter; XRP is material. Spot OHLCV omits other venues, funding, open interest, basis, order books, token events, and execution capacity. Leakage controls are explicit and tested, but metrics are close-to-close research diagnostics, not a next-bar portfolio backtest with overlapping-horizon accounting, fees, slippage, turnover, capacity, or latency. The holdout has now been observed, so tuning inspired by it requires new governance and genuinely future untouched data. Changing cross-sectional breadth, correlated regimes, multiple comparisons, and a single venue increase false-discovery risk. Generated artifacts are Git-ignored and need external retention despite manifest hashes.

## Important Commits and Push State

Important pushed checkpoints: `0b76d66` V4 strategy/paper workflow; `82aaac2` daily V4 pipeline; `e742522`/`dade8ef` journal; `87b13c8`/`96ccd20` report/SPY benchmark; `effecc1` V5 Phase 1; `916135c` Crypto Phase 1; `8107296` Phase 2; `c12d958` horizon/ranking/manifest correction; `0e16022` Phase 3. All are ancestors of pushed `origin/feature/paper-trading`. This handoff edit is not committed or pushed.

## Recommended Next Steps (future, not completed)

1. Do not promote the current Crypto V1 models to Phase 4. Preserve Phase 3 artifacts/hashes as the frozen negative checkpoint.
2. Diagnose existing predictions without retuning the holdout: fold/year/regime stability, breadth, implied turnover, asset contribution, XRP-gap sensitivity, and uncertainty intervals.
3. If continuing, pre-register a materially different Phase 3B hypothesis and governance plan; select only on development data and reserve genuinely new future data.
4. Before any promotion, build execution-timed portfolio evaluation for Top 3/Top 5 with explicit overlap handling, fees, slippage, turnover, capacity, BTC comparison, and the full scorecard. Require stable fold/regime results.
5. Improve point-in-time universe/delisting coverage and consider a provider-neutral second venue; investigate rather than fill source gaps.
6. Continue frozen Stock V4 forward observation. Keep Stock V5 full ingestion/modeling isolated.
7. With approval, commit only this handoff; never commit generated datasets, models, or runtime state.
