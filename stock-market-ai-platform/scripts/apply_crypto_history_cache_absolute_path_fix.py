#!/usr/bin/env python3
"""Fix Crypto Visual persistent history cache paths to be project-root absolute."""
from pathlib import Path

TARGET = Path("webapp/services/crypto_history_web_cache_service.py")


def main() -> None:
    text = TARGET.read_text()
    old = 'CACHE_ROOT = Path("data/live/crypto_rt/history_web")\n'
    new = (
        'PROJECT_ROOT = Path(__file__).resolve().parents[2]\n'
        'CACHE_ROOT = PROJECT_ROOT / "data/live/crypto_rt/history_web"\n'
    )

    if new in text:
        print("[SKIP] persistent history cache already uses absolute project-root path")
    elif old in text:
        TARGET.write_text(text.replace(old, new, 1))
        print("[APPLY] persistent history cache absolute project-root path")
    else:
        raise SystemExit(
            "Cannot apply persistent history cache path fix: expected CACHE_ROOT line not found"
        )

    print("Crypto Visual persistent history cache path fix complete.")
    print("Flask send_file will now receive an absolute path outside webapp/.")
    print("Historical data, models, journals, policies, and brokerage settings are unchanged.")


if __name__ == "__main__":
    main()
