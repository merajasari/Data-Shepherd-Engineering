# Machine Learning Model Guide

## Overview

The Stock Market AI Platform currently uses a per-symbol binary classification model to research **five-trading-day stock direction**.

The implementation intentionally begins with a transparent baseline: NumPy logistic regression. The goal is not to maximize model complexity; it is to establish a reproducible benchmark that can be compared honestly against future model families.

> Experimental research only. Model outputs are not trading recommendations.

## Prediction Target

Each model predicts:

```text
target_up_5d
```

Interpretation:

```text
1 (UP)   -> price is higher five trading days later
0 (DOWN) -> price is not higher five trading days later
```

The model returns a probability between 0 and 1 and currently uses a 0.50 classification threshold.

```text
probability >= 0.50 -> UP
probability <  0.50 -> DOWN
```

This is a **direction classification model**, not a direct future-price forecast.

## Why Logistic Regression?

The current NumPy logistic-regression baseline provides:

- transparent mathematical behavior
- fast training across 26 symbols
- probabilistic output
- inspectable coefficients
- small portable artifacts
- a clear benchmark for future models

A more complex model should only replace or complement it if it demonstrates stronger out-of-sample performance under better validation.

## Feature Vector

The current model uses 26 numerical features:

| Category | Features |
|---|---|
| Returns | `daily_return`, `cumulative_return`, `return_5d`, `return_10d`, `return_20d` |
| Trend | `sma_7`, `sma_20`, `sma_50`, `sma_200` |
| Price vs Trend | `price_vs_sma_7`, `price_vs_sma_20`, `price_vs_sma_50`, `price_vs_sma_200` |
| Moving-Average Relationships | `sma_7_vs_sma_20`, `sma_20_vs_sma_50`, `sma_50_vs_sma_200` |
| Volume | `volume_sma_20`, `volume_ratio`, `volume_change_5d` |
| Volatility / Range | `daily_volatility`, `volatility_5d`, `volatility_20d`, `intraday_range`, `open_close_range` |
| Momentum | `rsi_14`, `momentum_10d` |

The model does not train directly on live IEX ticks. Live quotes are a presentation and market-state path today; model training remains based on the historical feature pipeline.

## Training Flow

```text
Gold market data
       |
       v
Feature engineering
       |
       v
26 features + target_up_5d
       |
       v
Chronological 80/20 split
       |
       +----------------------+
       |                      |
       v                      v
Training 80%             Holdout 20%
       |
       v
Training-only mean/std
       |
       v
Feature standardization
       |
       v
NumPy logistic regression
       |
       v
Holdout evaluation
       |
       v
Serialized model artifact
       |
       v
Prediction service
       |
       v
Flask dashboard
```

## Leakage Awareness

Two important safeguards are already in place:

1. Observations remain in chronological order rather than being randomly shuffled.
2. Feature means and standard deviations are calculated from the training partition only.

The same training-derived scaling is then applied to the holdout data and future inference rows.

These practices reduce common forms of time-series leakage, but they do not by themselves make the evaluation production-grade.

## Optimization

Current logistic-regression defaults:

```text
Learning rate: 0.05
Epochs:        3000
L2 penalty:    0.001
Threshold:     0.50
```

The sigmoid transformation is:

```text
p = 1 / (1 + exp(-z))
```

L2 regularization discourages unnecessarily large coefficients.

## One Model Per Symbol

The platform currently trains independent models for all 26 configured symbols.

Examples:

```text
models/aapl_direction_model.pkl
models/msft_direction_model.pkl
models/nvda_direction_model.pkl
...
```

`ml/train_all.py` orchestrates the full universe.

This design allows each model to learn its own coefficients. Future research should compare it with pooled, cross-sectional, sector-aware, and regime-aware approaches.

## Model Artifact Contents

Each serialized artifact contains enough information to reproduce inference consistently, including:

```text
model_type
version
symbol
target
target_horizon_days
prediction_threshold
feature_columns
weights
bias
feature_mean
feature_std
metrics
majority_baseline
training_rows
test_rows
```

Generated `.pkl` artifacts are intentionally ignored by Git.

## Evaluation Metrics

The holdout period reports:

- accuracy
- precision
- recall
- F1 score
- confusion-matrix counts
- majority-class baseline
- training/test row counts

### Why the Majority Baseline Matters

A model should not be considered useful just because its raw accuracy sounds reasonable. If the holdout set contains many more observations of one class, always predicting that majority class may outperform the trained model.

The dashboard therefore displays **Accuracy vs Baseline** for each symbol.

## Probability Is Not Accuracy

A model output such as:

```text
UP probability: 0.90
```

does **not** mean the model has historically been correct 90% of the time.

That value is the model's output for one feature vector. Accuracy is a separate holdout metric measured across many labeled observations. Calibration, precision, recall, F1, and baseline-relative performance all answer different questions.

## Current Observed Model Quality

The current dashboard makes a critical result visible: several symbol models remain below their majority baseline.

Examples observed in the current research run include large negative baseline edges for symbols such as AAPL, AMD, and ORCL, while a smaller number of symbols outperform baseline.

This should not be interpreted as a failure of the platform. It is exactly why the system exposes model-quality metrics instead of hiding them behind high prediction probabilities.

The infrastructure is currently more mature than the predictive model. Improving validation and modeling is now a primary research priority.

## Automated Retraining

Model retraining is integrated into `refresh_pipeline.sh`.

Retraining does **not** occur every hour by default. The scheduled job first checks whether a newer EOD bar exists using a sentinel symbol. If historical data has not advanced, downstream feature rebuilding and model training are skipped.

When new EOD data is detected, the workflow becomes:

```text
refresh 26 symbols
  -> Silver
  -> Gold
  -> Features
  -> train all 26 models
```

This reduces unnecessary API calls and unnecessary retraining.

## Relationship to Live Market Data

The platform now has a live Tiingo IEX path, but the ML architecture remains deliberately separate:

```text
Live IEX quote -> dashboard live price
Historical EOD -> features -> trained model -> prediction
```

The current live quote does not automatically become a new training observation or recompute technical features every 10 seconds.

A future intraday ML architecture would require a separate feature definition, target definition, validation design, and retraining/inference strategy.

## Current Limitations

Important limitations include:

- a single chronological 80/20 split is not sufficient for robust time-series validation
- several current models underperform a trivial majority baseline
- model probabilities may be poorly calibrated
- technical features alone may not contain enough predictive information
- market regimes change
- transaction costs and slippage are not represented by classification metrics
- accuracy is not profitability
- no walk-forward or rolling-window validation is implemented yet
- live market prices are not yet part of the ML feature/training path

## Research Priorities

The next ML phase should focus on evidence quality before model complexity:

1. walk-forward / rolling-window validation
2. baseline diagnostics by symbol
3. probability calibration
4. coefficient and feature analysis
5. class-balance diagnostics
6. alternative decision thresholds
7. additional simple baselines
8. tree-based model experiments
9. pooled and cross-symbol models
10. sector and market-regime features
11. model versioning and experiment tracking
12. drift and performance monitoring
13. historical prediction logging
14. backtesting with realistic costs and slippage

## Research Standard

A future model should only be considered an improvement if it adds repeatable out-of-sample value beyond simple baselines across multiple time windows.

The goal is not to produce confident-looking predictions. The goal is to determine scientifically whether the model contains measurable predictive information.

## Disclaimer

This machine-learning system is built for software engineering and research. It does not guarantee profitable trades and should not be interpreted as personalized financial advice. Any future trading use should require stronger validation, realistic backtesting, risk controls, and independent review.
