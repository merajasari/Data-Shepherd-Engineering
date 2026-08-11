"""
Stock universe configuration.

Defines the equities processed by the Stock Market AI Platform.
"""

SYMBOLS = [
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "GOOGL",
    "META",
    "TSLA",
    "AVGO",
    "AMD",
    "ORCL",
    "CRM",
    "JPM",
    "BAC",
    "V",
    "MA",
    "WMT",
    "COST",
    "HD",
    "JNJ",
    "UNH",
    "LLY",
    "XOM",
    "CVX",
    "CAT",
    "NFLX",
    "DIS",
]


# Portfolio benchmark/core holding.
# SPY is intentionally NOT part of the V4 ML ranking universe.
CORE_SYMBOL = "SPY"

# Forward-test allocation:
# 60% passive SPY core + 40% V4 stock-selection overlay.
CORE_ALLOCATION = 0.60
V4_ALLOCATION = 0.40


def get_core_symbol():
    """Return the passive portfolio core symbol."""
    return CORE_SYMBOL


def get_portfolio_allocations():
    """Return the configured core and V4 allocations."""
    return {
        "core": CORE_ALLOCATION,
        "v4": V4_ALLOCATION,
    }


def get_symbols():
    """Return the configured stock universe."""
    return SYMBOLS.copy()


if __name__ == "__main__":
    print(f"Configured symbols: {len(SYMBOLS)}")

    for symbol in SYMBOLS:
        print(symbol)
