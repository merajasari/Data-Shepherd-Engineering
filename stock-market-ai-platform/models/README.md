# Trained Models

This directory contains locally generated model artifacts.

Models are produced by the training pipelines under `ml/`.

Generated binary model artifacts are intentionally not committed to Git.
The reproducible source of truth is the training code and feature dataset.

Current model:

- `aapl_direction_model.pkl`
- Model type: NumPy logistic regression
- Target: 5-day forward stock direction
- Training data: AAPL feature dataset
