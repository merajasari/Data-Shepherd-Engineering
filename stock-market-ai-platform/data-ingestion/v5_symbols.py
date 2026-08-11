"""Isolated stock-universe configuration for V5 research.

V4 continues to use ``symbols.py``.  Nothing in the frozen V4 workflow
imports this module.
"""

V5_BENCHMARK_SYMBOL = "SPY"


V5_SYMBOLS_BY_SECTOR = {
    "Communication Services": (
        "GOOGL", "META", "NFLX", "DIS", "CMCSA", "T", "VZ", "TMUS",
    ),
    "Consumer Discretionary": (
        "AMZN", "TSLA", "HD", "MCD", "BKNG", "LOW", "TJX", "NKE",
        "SBUX", "CMG", "MAR", "ORLY",
    ),
    "Consumer Staples": (
        "WMT", "COST", "PG", "KO", "PEP", "PM", "MO", "MDLZ",
    ),
    "Energy": (
        "XOM", "CVX", "COP", "SLB", "EOG", "MPC", "PSX",
    ),
    "Financials": (
        "JPM", "BAC", "V", "MA", "WFC", "GS", "MS", "C", "AXP",
        "SCHW", "BLK", "SPGI",
    ),
    "Health Care": (
        "JNJ", "UNH", "LLY", "ABBV", "MRK", "TMO", "ABT", "AMGN",
        "GILD", "ISRG", "SYK", "MDT",
    ),
    "Industrials": (
        "CAT", "GE", "RTX", "HON", "UNP", "BA", "DE", "LMT", "ETN",
        "UPS", "ADP",
    ),
    "Information Technology": (
        "AAPL", "MSFT", "NVDA", "AVGO", "ORCL", "CRM", "AMD", "ADBE",
        "CSCO", "IBM", "QCOM", "TXN", "AMAT", "MU", "INTU", "NOW",
        "PANW", "PLTR",
    ),
    "Materials": (
        "LIN", "APD", "SHW", "FCX",
    ),
    "Real Estate": (
        "PLD", "AMT", "EQIX", "WELL",
    ),
    "Utilities": (
        "NEE", "SO", "DUK", "AEP",
    ),
}


V5_SYMBOLS = tuple(
    symbol
    for sector_symbols in V5_SYMBOLS_BY_SECTOR.values()
    for symbol in sector_symbols
)


def get_v5_symbols():
    """Return a mutable copy of the V5 candidate-equity universe."""
    return list(V5_SYMBOLS)


def get_v5_data_symbols():
    """Return candidates plus the separately tracked SPY benchmark."""
    return [*V5_SYMBOLS, V5_BENCHMARK_SYMBOL]


def get_v5_sector(symbol):
    """Return the configured sector for a V5 candidate symbol."""
    for sector, symbols in V5_SYMBOLS_BY_SECTOR.items():
        if symbol in symbols:
            return sector
    raise KeyError(f"Symbol is not in the V5 candidate universe: {symbol}")


def validate_v5_universe():
    """Fail fast if the research-universe contract is violated."""
    if len(V5_SYMBOLS) != 100:
        raise ValueError(f"Expected 100 V5 candidates, found {len(V5_SYMBOLS)}")
    if len(set(V5_SYMBOLS)) != len(V5_SYMBOLS):
        raise ValueError("V5 candidate symbols must be unique")
    if V5_BENCHMARK_SYMBOL in V5_SYMBOLS:
        raise ValueError("SPY must remain outside the V5 candidate universe")


validate_v5_universe()


if __name__ == "__main__":
    print(f"V5 candidate equities: {len(V5_SYMBOLS)}")
    print(f"Benchmark (not a candidate): {V5_BENCHMARK_SYMBOL}")
    for sector, symbols in V5_SYMBOLS_BY_SECTOR.items():
        print(f"{sector}: {len(symbols)}")
