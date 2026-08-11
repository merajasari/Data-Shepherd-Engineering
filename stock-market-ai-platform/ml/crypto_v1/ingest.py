"""Ingest provider-neutral Crypto V1 candles into isolated Bronze storage."""

import argparse
import csv
import json
from datetime import datetime, timezone

from ml.crypto_v1.config import (
    BRONZE_ROOT, CRYPTO_UNIVERSE, DEFAULT_GRANULARITY, PROVIDER_NAME,
)
from ml.crypto_v1.providers import CoinbaseExchangeProvider


def parse_timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def provider_for(name):
    if name == "coinbase_exchange":
        return CoinbaseExchangeProvider()
    raise ValueError(f"Unknown provider: {name}")


def write_bronze(product_id, candles, provider_name, granularity, requested_start, requested_end):
    output_dir = BRONZE_ROOT / provider_name / granularity / product_id
    output_dir.mkdir(parents=True, exist_ok=True)
    records = [candle.as_record(product_id, provider_name, granularity) for candle in candles]
    data_path = output_dir / "candles.csv"
    fields = (
        "product_id", "provider", "granularity", "timestamp_utc",
        "open", "high", "low", "close", "volume",
    )
    with data_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)

    metadata = {
        "product_id": product_id,
        "provider": provider_name,
        "granularity": granularity,
        "requested_start_utc": requested_start.isoformat(),
        "requested_end_utc_exclusive": requested_end.isoformat(),
        "first_available_utc": records[0]["timestamp_utc"] if records else None,
        "last_available_utc": records[-1]["timestamp_utc"] if records else None,
        "row_count": len(records),
        "ingested_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    metadata_path = output_dir / "metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return data_path, metadata_path


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True, help="ISO date/time, inclusive")
    parser.add_argument("--end", required=True, help="ISO date/time, exclusive")
    parser.add_argument("--products", nargs="+", default=list(CRYPTO_UNIVERSE))
    parser.add_argument("--granularity", choices=("daily", "hourly"), default=DEFAULT_GRANULARITY)
    parser.add_argument("--provider", default=PROVIDER_NAME)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    products = list(dict.fromkeys(value.upper().strip() for value in args.products))
    unsupported = sorted(set(products) - set(CRYPTO_UNIVERSE))
    if unsupported:
        raise ValueError("Products outside Crypto V1 universe: " + ", ".join(unsupported))
    start, end = parse_timestamp(args.start), parse_timestamp(args.end)
    print(f"Crypto V1 provider: {args.provider}")
    print(f"Products ({len(products)}): {', '.join(products)}")
    print(f"Range: {start.isoformat()} -> {end.isoformat()} (exclusive)")
    if args.dry_run:
        return

    provider = provider_for(args.provider)
    failures = []
    for index, product_id in enumerate(products, start=1):
        try:
            candles = provider.get_candles(product_id, start, end, args.granularity)
            data_path, _ = write_bronze(
                product_id, candles, provider.name, args.granularity, start, end,
            )
            print(f"[{index}/{len(products)}] {product_id}: {len(candles)} -> {data_path}")
        except Exception as exc:
            failures.append((product_id, str(exc)))
            print(f"[{index}/{len(products)}] {product_id}: ERROR {exc}")
    if failures:
        raise SystemExit("Failed products: " + "; ".join(f"{p}: {e}" for p, e in failures))


if __name__ == "__main__":
    main()
