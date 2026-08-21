"""Resolve the active stock-feature dataset location.

Pandas remains the default production backend and uses the established
single-Parquet-file layout under data/features/stocks. The optional Spark backend
uses the isolated directory layout under data/features_spark/stocks.
"""
from __future__ import annotations

import os
from pathlib import Path

DEFAULT_FEATURE_BACKEND = "pandas"
SUPPORTED_FEATURE_BACKENDS = {"pandas", "spark"}


def get_feature_backend(value=None) -> str:
    raw = os.environ.get("FEATURE_BACKEND", DEFAULT_FEATURE_BACKEND) if value is None else value
    backend = str(raw).strip().lower()
    if backend not in SUPPORTED_FEATURE_BACKENDS:
        supported = ", ".join(sorted(SUPPORTED_FEATURE_BACKENDS))
        raise ValueError(f"Unsupported FEATURE_BACKEND={raw!r}. Expected one of: {supported}")
    return backend


def get_feature_dataset_path(symbol: str, *, project_root: Path | str = ".", backend=None) -> Path:
    root = Path(project_root)
    resolved = get_feature_backend(backend)
    if resolved == "spark":
        return root / "data" / "features_spark" / "stocks" / symbol
    return root / "data" / "features" / "stocks" / symbol / f"{symbol}_features.parquet"


def feature_dataset_exists(path: Path | str) -> bool:
    p = Path(path)
    if p.is_file():
        return p.stat().st_size > 0
    if p.is_dir():
        return any(child.is_file() and child.suffix == ".parquet" and child.stat().st_size > 0 for child in p.glob("*.parquet"))
    return False


def feature_dataset_mtime_ns(path: Path | str) -> int:
    p = Path(path)
    if p.is_file():
        return p.stat().st_mtime_ns
    if p.is_dir():
        mtimes = [child.stat().st_mtime_ns for child in p.glob("*.parquet") if child.is_file()]
        if mtimes:
            return max(mtimes)
    raise FileNotFoundError(f"Feature dataset not found or empty: {p}")
