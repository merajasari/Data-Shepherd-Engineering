"""Validation for the immutable Crypto V1 Bronze candle contract."""

from dataclasses import asdict, dataclass
from datetime import datetime
import json
from pathlib import Path

import pandas as pd

from ml.crypto_v1.config import SUPPORTED_GRANULARITIES


BRONZE_COLUMNS = (
    "product_id", "provider", "granularity", "timestamp_utc",
    "open", "high", "low", "close", "volume",
)


class BronzeValidationError(ValueError):
    """Raised when Bronze candles or their provenance metadata are corrupt."""


@dataclass(frozen=True)
class Gap:
    after_utc: str
    before_utc: str
    missing_intervals: int


@dataclass(frozen=True)
class BronzeValidationReport:
    data_path: str
    metadata_path: str
    product_id: str
    provider: str
    granularity: str
    row_count: int
    requested_start_utc: str
    requested_end_utc_exclusive: str
    first_available_utc: str | None
    last_available_utc: str | None
    gap_count: int
    missing_interval_count: int
    gaps: tuple[Gap, ...]

    def as_dict(self):
        result = asdict(self)
        result["gaps"] = [asdict(gap) for gap in self.gaps]
        return result


def _aware_utc(value, label):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise BronzeValidationError(f"Invalid {label}: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise BronzeValidationError(f"{label} must include a UTC offset")
    if parsed.utcoffset().total_seconds() != 0:
        raise BronzeValidationError(f"{label} must be UTC")
    return pd.Timestamp(parsed)


def validate_bronze(data_path: Path, metadata_path: Path | None = None):
    """Validate one Bronze file and return its normalized frame and report.

    Missing intervals are reported, not repaired and not treated as corruption.
    """
    data_path = Path(data_path)
    metadata_path = Path(metadata_path or data_path.with_name("metadata.json"))
    if not data_path.is_file() or not metadata_path.is_file():
        raise BronzeValidationError(f"Missing Bronze data or metadata: {data_path}")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        frame = pd.read_csv(data_path)
    except (OSError, json.JSONDecodeError, pd.errors.ParserError) as exc:
        raise BronzeValidationError(f"Unreadable Bronze artifact: {data_path}") from exc

    missing = [column for column in BRONZE_COLUMNS if column not in frame]
    if missing:
        raise BronzeValidationError(f"Missing Bronze columns: {missing}")
    required_metadata = {
        "product_id", "provider", "granularity", "requested_start_utc",
        "requested_end_utc_exclusive", "first_available_utc",
        "last_available_utc", "row_count",
    }
    missing_metadata = sorted(required_metadata - metadata.keys())
    if missing_metadata:
        raise BronzeValidationError(f"Missing Bronze metadata: {missing_metadata}")

    product_id = str(metadata["product_id"])
    provider = str(metadata["provider"])
    granularity = str(metadata["granularity"])
    if granularity not in SUPPORTED_GRANULARITIES:
        raise BronzeValidationError(f"Unsupported granularity: {granularity}")
    start = _aware_utc(metadata["requested_start_utc"], "requested_start_utc")
    end = _aware_utc(metadata["requested_end_utc_exclusive"], "requested_end_utc_exclusive")
    if start >= end:
        raise BronzeValidationError("Requested coverage must be a non-empty half-open range")
    if int(metadata["row_count"]) != len(frame):
        raise BronzeValidationError("Metadata row_count does not match candles.csv")

    for column, expected in (
        ("product_id", product_id), ("provider", provider),
        ("granularity", granularity),
    ):
        if not frame.empty and (frame[column].astype(str) != expected).any():
            raise BronzeValidationError(f"{column} conflicts with metadata")

    timestamps = []
    for value in frame["timestamp_utc"]:
        timestamps.append(_aware_utc(value, "timestamp_utc"))
    frame = frame.copy()
    frame["timestamp_utc"] = pd.to_datetime(timestamps, utc=True)
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
        if frame[column].isna().any():
            raise BronzeValidationError(f"Non-numeric or missing {column}")
    if not frame["timestamp_utc"].is_monotonic_increasing:
        raise BronzeValidationError("Candles are not chronologically ordered")
    if frame.duplicated(["product_id", "timestamp_utc"]).any():
        raise BronzeValidationError("Duplicate product_id + timestamp_utc")
    if not frame.empty and ((frame["timestamp_utc"] < start) | (frame["timestamp_utc"] >= end)).any():
        raise BronzeValidationError("Candle falls outside requested half-open coverage")
    if (frame[["open", "high", "low", "close"]] <= 0).any().any():
        raise BronzeValidationError("OHLC values must be positive")
    if (frame["volume"] < 0).any():
        raise BronzeValidationError("Volume must be non-negative")
    if ((frame["low"] > frame["open"]) | (frame["open"] > frame["high"])).any():
        raise BronzeValidationError("OHLC inconsistency: low <= open <= high violated")
    if ((frame["low"] > frame["close"]) | (frame["close"] > frame["high"])).any():
        raise BronzeValidationError("OHLC inconsistency: low <= close <= high violated")

    actual_first = frame["timestamp_utc"].iloc[0].isoformat() if len(frame) else None
    actual_last = frame["timestamp_utc"].iloc[-1].isoformat() if len(frame) else None
    for key, actual in (("first_available_utc", actual_first), ("last_available_utc", actual_last)):
        declared = metadata[key]
        normalized = _aware_utc(declared, key).isoformat() if declared is not None else None
        if normalized != actual:
            raise BronzeValidationError(f"Metadata {key} does not match candles.csv")

    interval_seconds = SUPPORTED_GRANULARITIES[granularity]
    gaps = []
    if len(frame) > 1:
        differences = frame["timestamp_utc"].diff().dt.total_seconds()
        for index in differences[differences > interval_seconds].index:
            missing_count = int(differences.loc[index] // interval_seconds) - 1
            gaps.append(Gap(
                frame.loc[index - 1, "timestamp_utc"].isoformat(),
                frame.loc[index, "timestamp_utc"].isoformat(),
                missing_count,
            ))
    report = BronzeValidationReport(
        str(data_path), str(metadata_path), product_id, provider, granularity,
        len(frame), start.isoformat(), end.isoformat(), actual_first, actual_last,
        len(gaps), sum(gap.missing_intervals for gap in gaps), tuple(gaps),
    )
    return frame.loc[:, list(BRONZE_COLUMNS)], report
