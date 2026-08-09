# Machine Learning Model Guide

## Overview

The Stock Market AI Platform contains a machine-learning layer designed to experiment with **five-trading-day stock direction classification**.

The current implementation intentionally begins with an interpretable baseline model rather than presenting a complex black-box model as if complexity guaranteed predictive power. Every configured equity is trained independently, evaluated against later observations, and compared with a simple majority-class baseline.

## What Does the Model Predict?

For each stock, the target is:

```text
target_up_5d
```

Conceptually:

```text
1 (UP)   -> price is higher five trading days later
0 (DOWN) -> price is not higher five trading days later
```

The model produces a probability between 0 and 1. The current decision threshold is `0.50`.

```text
probability >= 0.50 -> UP
probability <  0.50 -> DOWN
```

This is a classification model, not a direct future-price forecasting model.

## Why Logistic Regression?

The current model is a lightweight binary logistic regression implemented with NumPy.

This provides several useful properties for the first ML baseline:

- Transparent mathematical behavior
- Fast training across many stocks
- Probabilistic output
- Easy inspection of feature weights
- Small portable model artifacts
- A meaningful benchmark for future algorithms

A more complicated model should only replace or complement this baseline if it demonstrates stronger out-of-sample performance under appropriate validation.

## Feature Vector

The model currently uses **26 numerical features**:

| Category | Features |
|---|---|
| Returns | `daily_return`, `cumulative_return`, `return_5d`, `return_10d`, `return_20d` |
| Trend | `sma_7`, `sma_20`, `sma_50`, `sma_200` |
| Price vs Trend | `price_vs_sma_7`, `price_vs_sma_20`, `price_vs_sma_50`, `price_vs_sma_200` |
| Moving-Average Relationships | `sma_7_vs_sma_20`, `sma_20_vs_sma_50`, `sma_50_vs_sma_200` |
| Volume | `volume_sma_20`, `volume_ratio`, `volume_change_5d` |
| Volatility / Range | `daily_volatility`, `volatility_5d`, `volatility_20d`, `intraday_range`, `open_close_range` |
| Momentum | `rsi_14`, `momentum_10d` |

These features allow the model to examine several different aspects of recent market behavior rather than relying on closing price alone.

## Training Flow

```text
Gold Market Data
       |
       v
Feature Engineering
       |
       v
26 Input Features + target_up_5d
       |
       v
Chronological 80/20 Split
       |
       +----------------------+
       |                      |
       v                      v
Training 80%             Holdout 20%
       |
       v
Compute training-only
mean and standard deviation
       |
       v
Standardize training data
       |
       v
Train Logistic Regression
       |
       v
Apply same scaling to holdout data
       |
       v
Out-of-Sample Evaluation
       |
       v
Serialize Model Artifact
       |
       v
Prediction Service
       |
       v
Flask Dashboard
```

## Avoiding a Common Form of Data Leakage

Feature scaling is calculated from the **training partition only**.

The training mean and standard deviation are then applied to both training and holdout observations. This prevents future holdout observations from influencing the normalization statistics used to train the model.

The observations are also kept in chronological order rather than randomly shuffled. For market/time-series research, this is a more realistic baseline evaluation because later observations act as the unseen test period.

## Optimization

The NumPy logistic-regression implementation uses gradient descent.

Current defaults:

```text
Learning rate: 0.05
Epochs:        3000
L2 penalty:    0.001
Threshold:     0.50
```

The sigmoid function converts the linear model score into a probability:

```text
p = 1 / (1 + exp(-z))
```

where `z` is the weighted feature combination plus the learned bias.

L2 regularization is applied to the weights to discourage unnecessarily large coefficients.

## Evaluation Metrics

The holdout period is evaluated with:

### Accuracy
Percentage of all classifications that were correct.

### Precision
Of the observations classified as UP, how many were actually UP?

### Recall
Of the observations that actually moved UP, how many did the model identify?

### F1 Score
Harmonic mean of precision and recall.

### Majority Baseline
The accuracy that could be achieved by always choosing the most common class in the holdout set.

The baseline is particularly important. A model can have an apparently respectable accuracy while still performing worse than a trivial classifier.

## Probability Is Not Accuracy

This distinction is intentionally visible in the dashboard.

Suppose a model returns:

```text
UP probability: 0.90
```

That does **not** mean the model has historically been correct 90% of the time.

The probability is the model's output for one observation. Accuracy is measured over a collection of labeled holdout observations. Calibration, accuracy, precision, recall, F1 and baseline performance provide different information about model quality.

## One Model Per Symbol

The platform currently trains independent models for every configured stock instead of one universal model.

Example artifacts:

```text
models/aapl_direction_model.pkl
models/msft_direction_model.pkl
models/nvda_direction_model.pkl
...
```

The multi-model trainer iterates through all **26 configured symbols** and reports successful and failed training runs.

This design allows each model to learn coefficients from the historical feature behavior of its own equity. Future research can compare this approach against pooled, sector-aware and cross-sectional models.

## Model Artifact Contents

Each saved model artifact contains:

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

Saving the preprocessing statistics with the learned parameters is important because inference must transform new feature vectors the same way training data was transformed.

## Relationship to the Dashboard

The web application does not train a model every time someone loads the page.

Instead, the architecture separates responsibilities:

```text
Training pipeline -> saved model artifacts
                         |
                         v
                  Prediction service
                         |
                         v
                    Flask app
                         |
                         v
                     Dashboard
```

The dashboard combines ML output with current market analytics such as closing price, moving averages, RSI, volatility and volume behavior.

## Current Limitations

The model should be viewed as an experimental baseline. Important limitations include:

- Historical performance does not guarantee future performance.
- A single 80/20 chronological holdout is useful but not sufficient for robust time-series validation.
- Transaction costs, slippage and execution constraints are not represented by classification metrics.
- Model probability may not be calibrated.
- Market regimes can change.
- Technical features alone may not contain enough predictive information.
- Accuracy alone is not a trading strategy or profitability measure.

## ML Roadmap

Planned research improvements include:

1. Walk-forward / rolling-window validation
2. Backtesting with realistic execution assumptions
3. Probability calibration analysis
4. Feature importance and coefficient analysis
5. Additional baseline models
6. Tree-based model experiments
7. Cross-symbol and sector-aware modeling
8. Hyperparameter experimentation
9. Model versioning and experiment tracking
10. Drift and performance monitoring
11. Automated retraining
12. Risk-adjusted strategy evaluation

The goal is not to maximize model complexity. The goal is to determine, scientifically and reproducibly, whether a model adds measurable out-of-sample value beyond simple baselines.

## Research Disclaimer

This machine-learning system is built for engineering and research purposes. It does not guarantee profitable trades and should not be interpreted as personalized financial advice. Any future trading use should be preceded by robust validation, backtesting, risk controls and independent review.
