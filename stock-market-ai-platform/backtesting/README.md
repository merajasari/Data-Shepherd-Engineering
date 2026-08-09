# Backtesting Framework

This module is the planned validation layer for turning model outputs into evidence about strategy behavior.

The platform now has a functioning data pipeline, live market feed, automated retraining workflow, and dashboard. The next research priority is stronger out-of-sample validation before treating any model output as a trading signal.

## Why Backtesting Matters

Classification metrics alone are not enough.

A model can have acceptable accuracy and still produce a poor strategy because of:

- class imbalance
- badly calibrated probabilities
- transaction costs
- slippage
- low payoff on correct predictions
- large losses on incorrect predictions
- excessive turnover
- drawdowns
- changing market regimes

Backtesting is therefore a separate research layer, not a replacement for model evaluation.

## Planned Flow

```text
Historical feature data
      +
Stored model predictions
      +
Strategy rules
      |
      v
Walk-forward simulation
      |
      v
Execution assumptions
      |
      v
Portfolio / position logic
      |
      v
Performance and risk metrics
```

## Planned Capabilities

- walk-forward prediction generation
- entry and exit rules
- threshold-based strategy definitions
- realistic transaction costs
- slippage assumptions
- position sizing
- maximum exposure controls
- benchmark comparison
- drawdown analysis
- rolling performance
- historical prediction persistence

## Metrics

Planned metrics include:

- total return
- annualized return
- annualized volatility
- Sharpe ratio
- maximum drawdown
- hit rate
- turnover
- average trade return
- profit factor
- exposure
- benchmark-relative performance

## Research Standard

The current machine-learning models include symbols that materially underperform their majority-class baseline. Backtesting should therefore begin only after walk-forward model evaluation is implemented and should preserve strict chronological separation between training and future evaluation periods.

Any future strategy should be judged on repeatable out-of-sample results, not a single favorable historical period.

## Live Data Relationship

The Tiingo IEX feed currently powers live dashboard pricing. It does not yet provide the historical intraday event store required for intraday backtesting.

If the project evolves toward intraday ML, it will need a separate persistent intraday dataset, feature definition, targets, and execution simulator.

## Safety and Scope

This framework is for research and engineering. A backtest is not proof that a strategy will perform similarly in live markets. Any future real-world execution would require paper trading, monitoring, risk controls, and independent review.
