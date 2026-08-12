"""Import Kraken's official historical OHLCVT archive into Crypto V2 Bronze.

The importer is intentionally source-preserving: it reads only native Kraken
1440-minute USD candles, keeps missing intervals missing, records provenance,
and never overwrites Coinbase or creates a canonical merged history.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
from urllib.request import Request, urlopen
import zipfile

import pandas as pd

from ml.crypto_v1.config import CRYPTO_UNIVERSE
from ml.crypto_v2.config import (
    BRONZE_ROOT,
    KRAKEN_OHLCVT_ARCHIVE_URL,
    KRAKEN_OHLCVT_SOURCE_PAGE,
    KRAKEN_PROVIDER_NAME,
    RESEARCH_VERSION,
)

GRANULARITY = "daily"
INTERVAL_MINUTES = 1440

# Kraken has used both user-facing and legacy/internal asset codes.  The archive
# filename is matched against these exact USD-pair candidates only; USDT/EUR or
# any other quote is never silently substituted for USD.
PAIR_CANDIDATES = {
    "BTC-USD": ("XBTUSD", "BTCUSD", "XXBTZUSD"),
    "ETH-USD": ("ETHUSD", "XETHZUSD"),
    "SOL-USD": ("SOLUSD",),
    "XRP-USD": ("XRPUSD", "XXRPZUSD"),
    "DOGE-USD": ("DOGEUSD", "XDGUSD", "XXDGZUSD"),
    "ADA-USD": ("ADAUSD",),
    "AVAX-USD": ("AVAXUSD",),
    "LINK-USD": ("LINKUSD",),
    "LTC-USD": ("LTCUSD", "XLTCZUSD"),
    "BCH-USD": ("BCHUSD",),
    "DOT-USD": ("DOTUSD",),
    "UNI-USD": ("UNIUSD",),
    "AAVE-USD": ("AAVEUSD",),
    "ATOM-USD": ("ATOMUSD",),
    "NEAR-USD": ("NEARUSD",),
    "ICP-USD": ("ICPUSD",),
    "FIL-USD": ("FILUSD",),
    "ETC-USD": ("ETCUSD", "XETCZUSD"),
    "XLM-USD": ("XLMUSD", "XXLMZUSD"),
    "HBAR-USD": ("HBARUSD",),
    "SHIB-USD": ("SHIBUSD",),
    "SUI-USD": ("SUIUSD",),
    "OP-USD": ("OPUSD",),
    "ARB-USD": ("ARBUSD",),
    "INJ-USD": ("INJUSD",),
}

BRONZE_COLUMNS = [
    "product_id", "provider", "granularity", "timestamp_utc",
    "open", "high", "low", "close", "volume",
]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_utc(value: str) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts


def download_archive(destination: Path, url: str = KRAKEN_OHLCVT_ARCHIVE_URL) -> Path:
    """Download the current official Kraken OHLCVT ZIP to ``destination``."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = Request(url, headers={"User-Agent": "Data-Shepherd-Crypto-V2/1.0"})
    with urlopen(request, timeout=120) as response, destination.open("wb") as handle:
        shutil.copyfileobj(response, handle, length=1024 * 1024)
    if not zipfile.is_zipfile(destination):
        raise ValueError(
            "Downloaded Kraken artifact is not a ZIP file. Download the Single ZIP File "
            f"from {KRAKEN_OHLCVT_SOURCE_PAGE} and pass it with --archive."
        )
    return destination


def _member_index(archive: zipfile.ZipFile) -> dict[str, str]:
    result = {}
    suffix = f"_{INTERVAL_MINUTES}.csv"
    for member in archive.namelist():
        base = Path(member).name
        upper = base.upper()
        if not upper.endswith(suffix.upper()):
            continue
        pair = upper[: -len(suffix)]
        # If duplicates exist in nested folders, fail instead of silently choosing.
        if pair in result and result[pair] != member:
            raise ValueError(f"Duplicate Kraken archive member for {pair}: {result[pair]} and {member}")
        result[pair] = member
    return result


def _find_member(index: dict[str, str], product_id: str) -> tuple[str | None, str | None]:
    for pair in PAIR_CANDIDATES.get(product_id, (product_id.replace("-", ""),)):
        if pair.upper() in index:
            return pair.upper(), index[pair.upper()]
    return None, None


def _read_member(archive: zipfile.ZipFile, member: str, product_id: str,
                 start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    with archive.open(member) as handle:
        raw = pd.read_csv(handle, header=None)
    if raw.shape[1] < 7:
        raise ValueError(f"Unexpected Kraken OHLCVT shape for {member}: {raw.shape}")

    ts_numeric = pd.to_numeric(raw.iloc[:, 0], errors="coerce")
    raw = raw.loc[ts_numeric.notna()].copy()
    ts_numeric = ts_numeric.loc[ts_numeric.notna()]
    if raw.empty:
        return pd.DataFrame(columns=BRONZE_COLUMNS)

    # Kraken historical archives use Unix epoch timestamps. Support seconds and
    # milliseconds defensively without inventing any observations.
    median_abs = float(ts_numeric.abs().median())
    unit = "ms" if median_abs > 100_000_000_000 else "s"
    timestamps = pd.to_datetime(ts_numeric.astype("int64"), unit=unit, utc=True)

    frame = pd.DataFrame({
        "product_id": product_id,
        "provider": KRAKEN_PROVIDER_NAME,
        "granularity": GRANULARITY,
        "timestamp_utc": timestamps,
        "open": pd.to_numeric(raw.iloc[:, 1], errors="coerce"),
        "high": pd.to_numeric(raw.iloc[:, 2], errors="coerce"),
        "low": pd.to_numeric(raw.iloc[:, 3], errors="coerce"),
        "close": pd.to_numeric(raw.iloc[:, 4], errors="coerce"),
        "volume": pd.to_numeric(raw.iloc[:, 5], errors="coerce"),
    })
    if frame[["open", "high", "low", "close", "volume"]].isna().any().any():
        raise ValueError(f"Non-numeric Kraken OHLCV value in {member}")
    frame = frame[(frame["timestamp_utc"] >= start) & (frame["timestamp_utc"] < end)].copy()
    frame = frame.sort_values("timestamp_utc").drop_duplicates("timestamp_utc", keep="last")
    return frame.loc[:, BRONZE_COLUMNS].reset_index(drop=True)


def write_bronze(product_id: str, frame: pd.DataFrame, output_root: Path,
                 requested_start: pd.Timestamp, requested_end: pd.Timestamp,
                 archive_path: Path, archive_sha256: str, archive_pair: str,
                 archive_member: str) -> tuple[Path, Path]:
    output_dir = Path(output_root) / KRAKEN_PROVIDER_NAME / GRANULARITY / product_id
    output_dir.mkdir(parents=True, exist_ok=True)
    data_path = output_dir / "candles.csv"
    metadata_path = output_dir / "metadata.json"

    output = frame.copy()
    if len(output):
        output["timestamp_utc"] = output["timestamp_utc"].map(lambda x: pd.Timestamp(x).isoformat())
    output.to_csv(data_path, index=False)

    metadata = {
        "product_id": product_id,
        "provider": KRAKEN_PROVIDER_NAME,
        "granularity": GRANULARITY,
        "requested_start_utc": requested_start.isoformat(),
        "requested_end_utc_exclusive": requested_end.isoformat(),
        "first_available_utc": frame["timestamp_utc"].iloc[0].isoformat() if len(frame) else None,
        "last_available_utc": frame["timestamp_utc"].iloc[-1].isoformat() if len(frame) else None,
        "row_count": int(len(frame)),
        "ingested_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_type": "kraken_official_ohlcvt_archive",
        "source_page": KRAKEN_OHLCVT_SOURCE_PAGE,
        "archive_path": str(archive_path),
        "archive_sha256": archive_sha256,
        "archive_pair": archive_pair,
        "archive_member": archive_member,
        "archive_interval_minutes": INTERVAL_MINUTES,
        "policy": (
            "Native Kraken observations only; missing intervals remain missing; "
            "no interpolation, synthetic candles, quote substitution, or canonical merge."
        ),
    }
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return data_path, metadata_path


def import_archive(archive_path: Path, start: str, end: str,
                   products=CRYPTO_UNIVERSE, output_root=BRONZE_ROOT):
    archive_path = Path(archive_path)
    if not zipfile.is_zipfile(archive_path):
        raise ValueError(f"Not a Kraken ZIP archive: {archive_path}")
    requested_start, requested_end = _parse_utc(start), _parse_utc(end)
    if requested_start >= requested_end:
        raise ValueError("start must be earlier than end")

    products = list(dict.fromkeys(str(p).upper().strip() for p in products))
    unsupported = sorted(set(products) - set(CRYPTO_UNIVERSE))
    if unsupported:
        raise ValueError("Products outside frozen Crypto V2 universe: " + ", ".join(unsupported))

    archive_hash = _sha256(archive_path)
    imported, unavailable = [], []
    with zipfile.ZipFile(archive_path) as archive:
        index = _member_index(archive)
        for product_id in products:
            pair, member = _find_member(index, product_id)
            if member is None:
                unavailable.append(product_id)
                continue
            frame = _read_member(archive, member, product_id, requested_start, requested_end)
            if frame.empty:
                unavailable.append(product_id)
                continue
            data_path, _ = write_bronze(
                product_id, frame, output_root, requested_start, requested_end,
                archive_path, archive_hash, pair, member,
            )
            imported.append({
                "product_id": product_id,
                "archive_pair": pair,
                "archive_member": member,
                "row_count": int(len(frame)),
                "first_available_utc": frame["timestamp_utc"].iloc[0].isoformat(),
                "last_available_utc": frame["timestamp_utc"].iloc[-1].isoformat(),
                "data_path": str(data_path),
            })

    return {
        "research_version": RESEARCH_VERSION,
        "stage": "kraken_historical_archive_ingest",
        "provider": KRAKEN_PROVIDER_NAME,
        "requested_start_utc": requested_start.isoformat(),
        "requested_end_utc_exclusive": requested_end.isoformat(),
        "archive_path": str(archive_path),
        "archive_sha256": archive_hash,
        "imported_asset_count": len(imported),
        "unavailable_asset_count": len(unavailable),
        "unavailable_products": unavailable,
        "imported": imported,
        "canonical_source_selected": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, help="Kraken_OHLCVT.zip path")
    parser.add_argument("--download-to", type=Path, help="Download official Kraken ZIP here first")
    parser.add_argument("--start", default="2016-08-12")
    parser.add_argument("--end", default="2026-08-13")
    parser.add_argument("--products", nargs="+", default=list(CRYPTO_UNIVERSE))
    parser.add_argument("--output-root", type=Path, default=BRONZE_ROOT)
    args = parser.parse_args(argv)

    archive = args.archive
    if args.download_to is not None:
        archive = download_archive(args.download_to)
    if archive is None:
        parser.error("provide --archive or --download-to")

    manifest = import_archive(archive, args.start, args.end, args.products, args.output_root)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
