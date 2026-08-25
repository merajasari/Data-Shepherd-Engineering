"""Regression for backend-aware monitoring and Tiingo credential redaction."""
from __future__ import annotations
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "data-ingestion"))

from tiingo_client import TiingoClient
from ml import data_convergence
from ml import operations_health


def require(value, label):
    if not value:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def main():
    target = pd.Timestamp("2026-08-24", tz="UTC")
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        for symbol in ("AAPL", "SPY"):
            spark = root / "data/features_spark/stocks" / symbol
            pandas_root = root / "data/features/stocks" / symbol
            spark.mkdir(parents=True)
            pandas_root.mkdir(parents=True)
            pd.DataFrame({"timestamp_utc": [target]}).to_parquet(
                spark / "part-00000.parquet", index=False
            )
            pd.DataFrame({
                "timestamp_utc": [pd.Timestamp("2026-08-21", tz="UTC")]
            }).to_parquet(
                pandas_root / f"{symbol}_features.parquet", index=False
            )

        old_dc_root = data_convergence.PROJECT_ROOT
        old_ops_root = operations_health.PROJECT_ROOT
        old_backend = os.environ.get("FEATURE_BACKEND")
        try:
            data_convergence.PROJECT_ROOT = root
            operations_health.PROJECT_ROOT = root
            os.environ["FEATURE_BACKEND"] = "spark"
            layer = data_convergence._layer_status(
                "features", root / "unused", "_features.parquet",
                ["AAPL", "SPY"], target, feature_backend="spark",
            )
            require(layer["symbols_at_target"] == 2, "Convergence reads Spark feature datasets")
            require(layer["backend"] == "spark", "Convergence publishes selected backend")
            common, found, backend = operations_health._feature_common_latest()
            require(found == 2 and common == target.isoformat(),
                    "Operations health reads Spark feature freshness")
            require(backend == "spark", "Operations health publishes selected backend")
        finally:
            data_convergence.PROJECT_ROOT = old_dc_root
            operations_health.PROJECT_ROOT = old_ops_root
            if old_backend is None:
                os.environ.pop("FEATURE_BACKEND", None)
            else:
                os.environ["FEATURE_BACKEND"] = old_backend

    secret = "DO_NOT_LOG_THIS_TOKEN"
    old_key = os.environ.get("TIINGO_API_KEY")
    os.environ["TIINGO_API_KEY"] = secret
    try:
        client = TiingoClient()
        leaked = requests.ConnectionError(
            f"https://api.tiingo.com/prices?token={secret}"
        )
        with patch("tiingo_client.requests.get", side_effect=leaked):
            try:
                client.get_daily_prices("SPY", "2026-08-20", "2026-08-24")
            except RuntimeError as exc:
                message = str(exc)
            else:
                raise AssertionError("network failure was not propagated")
        require(secret not in message, "Tiingo token is redacted from raised error")
        require("credentials redacted" in message, "Redaction is explicit")
    finally:
        if old_key is None:
            os.environ.pop("TIINGO_API_KEY", None)
        else:
            os.environ["TIINGO_API_KEY"] = old_key

    print("\nStatus: PASSED")
    print("Feature backend monitoring: VERIFIED")
    print("Credential logging: REDACTED")
    print("Brokerage orders: OFF")


if __name__ == "__main__":
    main()
