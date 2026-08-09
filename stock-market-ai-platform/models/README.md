# Trained Models

This directory contains locally generated machine-learning model artifacts produced by the training pipeline under `ml/`.

Generated `.pkl` files are intentionally excluded from Git. The reproducible source of truth is the training code plus the feature datasets.

## Current Model Family

The platform currently trains one NumPy logistic-regression model per configured symbol.

Target:

```text
target_up_5d
```

Interpretation:

```text
UP   -> stock is higher five trading days later
DOWN -> stock is not higher five trading days later
```

The configured universe contains 26 symbols, so a complete training run produces up to 26 model artifacts.

Examples:

```text
models/aapl_direction_model.pkl
models/msft_direction_model.pkl
models/nvda_direction_model.pkl
...
```

## Artifact Contents

Each artifact contains the information needed for consistent inference, including:

- model type and version
- symbol
- target and forecast horizon
- prediction threshold
- feature-column list
- learned weights and bias
- training feature means and standard deviations
- holdout metrics
- majority-class baseline
- training/test row counts

Keeping the scaling statistics with the model is essential because inference must transform new feature vectors using the same training-derived preprocessing.

## Training and Retraining

`ml/train_all.py` trains the full configured universe.

Scheduled retraining is orchestrated by `refresh_pipeline.sh`. The job first checks whether new EOD market data exists. If the newest historical timestamp has not changed, feature rebuilding and retraining are skipped.

When new EOD data is detected:

```text
Tiingo refresh
  -> Silver
  -> Gold
  -> Features
  -> train all models
```

## Model Quality

The current models are experimental baselines. The dashboard compares each model's holdout accuracy with a majority-class baseline.

Several current symbol models remain below baseline, while a smaller number outperform it. This is treated as an explicit research result rather than hidden behind prediction probabilities.

A high output probability is not equivalent to validated accuracy.

## Next Research Priorities

- walk-forward validation
- rolling-window evaluation
- calibration analysis
- feature and coefficient diagnostics
- stronger baseline models
- alternative model families
- experiment tracking and versioning
- drift monitoring
- historical prediction logging
- realistic backtesting

See `docs/MACHINE_LEARNING.md` for the full model guide.
