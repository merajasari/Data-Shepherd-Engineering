"""Publish the isolated V8 rehearsal checklist as a read-only dashboard artifact.

This module copies only the rehearsal launch checklist into webapp/static/generated.
It never reads or writes production holdout journal events, strategy state, model
artifacts, or brokerage settings.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

SOURCE = Path("data/model/v8/rehearsal/launch_checklist.json")
OUTPUT = Path("webapp/static/generated/v8_launch_checklist.json")


def main():
    if not SOURCE.exists():
        raise FileNotFoundError(f"Missing {SOURCE}; run python -m ml.v8.holdout_rehearsal first")
    checklist = json.loads(SOURCE.read_text(encoding="utf-8"))
    payload = dict(checklist)
    payload["published_at_utc"] = datetime.now(timezone.utc).isoformat()
    payload["source"] = str(SOURCE)
    payload["rehearsal_only"] = True
    payload["production_holdout_modified"] = False
    payload["brokerage_orders"] = False
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUTPUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(OUTPUT)
    print("V8 HOLDOUT LAUNCH READINESS PUBLISHED")
    print(f"Source: {SOURCE}")
    print(f"Output: {OUTPUT}")
    print(f"Status: {payload.get('status', 'UNKNOWN')}")
    print("Production holdout modified: False")
    print("Brokerage orders: False")


if __name__ == "__main__":
    main()
