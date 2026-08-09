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


def get_symbols():
    """Return the configured stock universe."""
    return SYMBOLS.copy()


if __name__ == "__main__":
    print(f"Configured symbols: {len(SYMBOLS)}")

    for symbol in SYMBOLS:
        print(symbol)
