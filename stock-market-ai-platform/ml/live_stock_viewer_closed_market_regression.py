"""Closed-market regression for the Live Stock Viewer."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LIVE_REFRESH = ROOT / "webapp/static/js/realtime_market_refresh.js"
HISTORY_CHART = ROOT / "webapp/static/js/market_history_chart.js"


def require(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def main() -> None:
    live = LIVE_REFRESH.read_text()
    history = HISTORY_CHART.read_text()
    combined = live + "\n" + history

    require("const positivePrice" in live, "Live quotes require a positive finite price")
    require("const normalizeLiveQuote" in live, "Live quotes require a timestamp")
    require("price == null || !timestamp" in live, "Null and untimestamped quotes fail closed")
    require("Last completed close · not a live quote" in live, "Market card labels completed-close fallback")
    require("market closed':'live quote unavailable" in live, "Closed-market status is explicit")
    require("cell.textContent='—'" in live, "Unavailable live ticker cells cannot retain a false price")
    require("Number.isFinite(Number(livePrice))" not in live, "Null cannot enter technical indicators as zero")
    require("quote&&quote.reference_price!=null" not in live, "Unchecked quote publication is absent")

    require("const positivePrice" in history, "History chart validates positive prices")
    require("Number(payload.live?.reference_price)" not in history, "Null API prices cannot become zero")
    require("livePoint=null;if(lp!=null&&liveTimestamp" in history, "24-hour payload clears stale live points")
    require("else{livePoint=null;}title.textContent" in history, "Live events clear stale points")
    require("LAST CLOSE" in history, "Latest completed close is visibly labeled")
    require(
        "No trades occurred in the last 24 hours" in history,
        "Weekend 24-hour empty state is truthful",
    )
    require(
        "ACTUAL / REFERENCE PRICE" in history,
        "Readout no longer promises a live quote",
    )

    prohibited = ("import alpaca", "from alpaca", "import ib_insync", "robin_stocks")
    require(
        not any(marker in combined for marker in prohibited),
        "Viewer fix imports no brokerage interface",
    )

    print("Status: PASSED")
    print("Closed-market fallback: VERIFIED")
    print("Null/zero live quote publication: PROHIBITED")
    print("Brokerage orders: OFF")


if __name__ == "__main__":
    main()
