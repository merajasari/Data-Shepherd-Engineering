# Machine Learning Model Guide

## Overview

The Stock Market AI Platform uses one binary classification model per configured symbol to research **five-trading-day stock direction**.

The current model family is NumPy logistic regression. The system deliberately emphasizes reproducibility, baseline comparison, and transparent evaluation over model complexity.

> Experimental research only. Model outputs and forecast scores are not trading recommendations or future price targets.

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

The current classification threshold is 0.50.

## Forecast Score Layer

The dashboard now adds a market-wide trend view covering all 26 symbols.

`webapp/services/forecast_service.py` transforms the model probabilities into a normalized score:

```text
forecast_score = (probability_up - probability_down) * 100
```

Because `probability_down = 1 - probability_up`, the score spans approximately:

```text
-100 ... 0 ... +100
```

Interpretation:

```text
+50 to +100   strong bullish bias
+20 to +50    bullish bias
-20 to +20    neutral zone
-50 to -20    bearish bias
-100 to -50   strong bearish bias
```

The score is **not** a predicted percentage return and is **not** a future price estimate. It is a visualization of directional model imbalance.

## Feature Vector

The current model uses 26 numerical features spanning:

- returns
- moving averages
- price-vs-trend relationships
- volume
- volatility
- RSI
- momentum

The model does not train directly on live IEX ticks. Live quotes remain a presentation/market-state path.

## Training Flow

```text
Gold market data
  -> feature engineering
  -> 26 features + target_up_5d
  -> chronological 80/20 split
  -> training-only scaling
  -> NumPy logistic regression
  -> holdout evaluation
  -> serialized artifact
  -> prediction service
  -> forecast service
  -> Flask API/dashboard
```

## Leakage Awareness

Current safeguards include:

1. chronological ordering rather than random shuffling
2. scaling statistics derived from the training partition only

These reduce common leakage risks but do not replace walk-forward validation.

## Optimization

Current logistic-regression defaults:

```text
Learning rate: 0.05
Epochs:        3000
L2 penalty:    0.001
Threshold:     0.50
```

## One Model Per Symbol

The platform trains independent models for all 26 configured symbols.

Examples:

```text
models/aapl_direction_model.pkl
models/msft_direction_model.pkl
models/nvda_direction_model.pkl
...
```

A complete training run produces up to 26 artifacts.

## Artifact Contents

Each artifact includes:

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

Generated `.pkl` files are intentionally excluded from Git.

## Evaluation Metrics

The holdout period reports:

- accuracy
- precision
- recall
- F1
- confusion-matrix counts
- majority-class baseline
- training/test row counts

## Why the Majority Baseline Matters

A model is not automatically useful because its raw accuracy sounds reasonable. A trivial always-majority classifier can outperform a trained model when the classes are imbalanced.

The dashboard therefore exposes **accuracy vs baseline** for each symbol.

## Probability Is Not Accuracy

A prediction such as:

```text
UP probability: 0.90
```

means the current feature vector produced a strong UP model output. It does **not** mean the model has historically been correct 90% of the time.

Likewise, a forecast score of `+80` is not an expected 80% return. It simply reflects a large probability imbalance toward UP.

## Current Model Quality

Several current symbol models remain below their majority baseline. The platform intentionally surfaces this fact in the dashboard and in the 26-stock forecast view.

This is important because the infrastructure is currently more mature than the predictive model. The next research phase should focus on evidence quality rather than visual confidence.

## Automated Retraining

`refresh_pipeline.sh` retrains models only when new EOD data is detected.

```text
sentinel freshness check
  -> no new bar: stop
  -> new bar:
       refresh 26 symbols
       -> Silver
       -> Gold
       -> Features
       -> train all 26 models
```

## Relationship to Live Market Data

```text
Live IEX quote -> displayed live price
Historical EOD -> features -> trained model -> prediction/forecast score
```

The live quote does not automatically become a training observation or recompute the model every 10 seconds.

## Forecast API

The production API exposes all 26 model trend records:

```text
GET /api/forecast
```

Each valid forecast includes values such as:

```text
symbol
prediction
probability_up
probability_down
confidence
forecast_score
trend_strength
accuracy
majority_baseline
horizon_days
reference_close
prediction_timestamp
```

## Current Limitations

- one chronological 80/20 split is not sufficient for robust time-series validation
- several models underperform a majority baseline
- probabilities may be poorly calibrated
- technical features alone may have limited predictive information
- market regimes change
- classification accuracy is not profitability
- transaction costs/slippage are not represented
- no walk-forward validation yet
- no historical forecast-performance tracking yet
- live prices are not part of the training path
- forecast scores are directional, not return forecasts

## Research Priorities

1. walk-forward / rolling-window validation
2. baseline diagnostics by symbol
3. probability calibration
4. feature and coefficient analysis
5. class-balance diagnostics
6. threshold tuning
7. stronger simple baselines
8. alternative model families
9. pooled/cross-symbol models
10. regime and sector features
11. experiment tracking and model versioning
12. drift monitoring
13. historical prediction/forecast logging
14. realistic backtesting with costs and slippage

## Research Standard

A future model should only be considered an improvement if it demonstrates repeatable out-of-sample value beyond simple baselines across multiple time windows.

The goal is not to produce confident-looking predictions. The goal is to determine whether the model contains measurable predictive information.

## Disclaimer

This machine-learning system is built for software engineering and research. It does not guarantee profitable trades and should not be interpreted as personalized financial advice.
