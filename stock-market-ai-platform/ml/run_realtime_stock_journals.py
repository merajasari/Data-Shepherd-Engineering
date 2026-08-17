"""Continuously collect near-real-time stock diagnostic journal snapshots."""
from __future__ import annotations

import json
import signal
import time

from webapp.services.v4_realtime_equity_journal_service import append_realtime_equity_observation
from webapp.services.v5_shadow_comparison_journal_service import append_comparison_observation

POLL_SECONDS = 5.0
_running = True


def _stop(_sig, _frame):
    global _running
    _running = False


def main():
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    print("REAL-TIME STOCK DIAGNOSTIC JOURNALS", flush=True)
    print("Polling every 5 seconds; unchanged quote fingerprints are skipped.", flush=True)
    print("No portfolio writes, official holdout writes, or brokerage orders.", flush=True)
    while _running:
        try:
            v4 = append_realtime_equity_observation(skip_duplicate_quotes=True)
            comp = append_comparison_observation(skip_duplicate_quotes=True)
            if v4.get("status") == "appended" or comp.get("status") == "appended":
                print(json.dumps({"v4": v4, "comparison": comp}, sort_keys=True), flush=True)
        except Exception as exc:
            print(f"[REALTIME STOCK JOURNAL ERROR] {type(exc).__name__}: {exc}", flush=True)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
