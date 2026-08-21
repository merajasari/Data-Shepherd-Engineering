"""Resolve stock feature datasets for Pandas or Spark consumers.

The FEATURE_BACKEND contract is shared with data-ingestion/feature_pipeline.py:
Pandas remains the default; Spark must be selected explicitly.
"""

import os
from pathlib import Path


DEFAULT_FEATURE_BACKEND = "pandas"
SUPPORTED_FEATURE_BACKENDS = {"pandas", "spark"}
FEATURE_ROOTS = {
    "pandas": Path("data/features/stocks"),
    "spark": Path("data/features_spark/stocks"),
}


def get_feature_backend(value=None) -> str:
    """Resolve and validate the configured feature backend."""

    raw_value = (
        os.environ.get("FEATURE_BACKEND", DEFAULT_FEATURE_BACKEND)
        if value is None
        else value
    )
    backend = str(raw_value).strip().lower()

    if backend not in SUPPORTED_FEATURE_BACKENDS:
        supported = ", ".join(sorted(SUPPORTED_FEATURE_BACKENDS))
        raise ValueError(
            f"Unsupported FEATURE_BACKEND={raw_value!r}. "
            f"Expected one of: {supported}"
        )

    return backend


def get_feature_root(*, project_root=Path("."), backend=None) -> Path:
    """Return the selected backend's feature root."""

    selected = get_feature_backend(backend)
    return Path(project_root) / FEATURE_ROOTS[selected]


def get_feature_dataset_path(
    symbol: str,
    *,
    project_root=Path("."),
    backend=None,
) -> Path:
    """Return a symbol's file (Pandas) or Parquet directory (Spark)."""

    selected = get_feature_backend(backend)
    symbol = symbol.upper()
    symbol_root = get_feature_root(
        project_root=project_root,
        backend=selected,
    ) / symbol

    if selected == "spark":
        return symbol_root

    return symbol_root / f"{symbol}_features.parquet"


def feature_dataset_exists(path: Path) -> bool:
    """Return whether a resolved feature dataset contains readable Parquet."""

    path = Path(path)
    if path.is_file():
        return path.stat().st_size > 0
    if path.is_dir():
        return any(
            candidate.is_file() and candidate.stat().st_size > 0
            for candidate in path.glob("*.parquet")
        )
    return False


def require_feature_dataset(
    symbol: str,
    *,
    project_root=Path("."),
    backend=None,
) -> Path:
    """Resolve a feature dataset or raise a backend-aware error."""

    selected = get_feature_backend(backend)
    path = get_feature_dataset_path(
        symbol,
        project_root=project_root,
        backend=selected,
    )
    if not feature_dataset_exists(path):
        raise FileNotFoundError(
            f"{selected} feature dataset not found for {symbol.upper()}: {path}"
        )
    return path
