"""
Train direction models for all configured stock symbols.
"""

import subprocess
import sys

sys.path.append("data-ingestion")

from symbols import get_symbols


def main():
    symbols = get_symbols()

    successful = []
    failed = []

    print(
        f"Training models for {len(symbols)} symbols"
    )
    print()

    for index, symbol in enumerate(
        symbols,
        start=1,
    ):
        print(
            f"[{index}/{len(symbols)}] "
            f"Training {symbol}"
        )

        result = subprocess.run(
            [
                sys.executable,
                "ml/train_model_v3.py",
                symbol,
            ],
            text=True,
        )

        if result.returncode == 0:
            successful.append(symbol)
            print(
                f"[SUCCESS] {symbol}"
            )
        else:
            failed.append(symbol)
            print(
                f"[ERROR] {symbol}"
            )

        print()

    print("=" * 50)
    print("TRAINING SUMMARY")
    print("=" * 50)

    print(
        f"Successful: {len(successful)}"
    )

    print(
        f"Failed:     {len(failed)}"
    )

    if failed:
        print()
        print("Failed symbols:")

        for symbol in failed:
            print(
                f"  {symbol}"
            )


if __name__ == "__main__":
    main()
