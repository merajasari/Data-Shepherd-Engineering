"""Isolated stock-universe configuration for V5 research.

V4 continues to use ``symbols.py``. Nothing in the frozen V4 workflow imports
this module. Company names are presentation metadata only and do not affect the
frozen V5 model, features, rankings, or portfolio contract.
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


V5_COMPANY_NAMES = {
    "AAPL": "Apple Inc.",
    "ABBV": "AbbVie Inc.",
    "ABT": "Abbott Laboratories",
    "ADBE": "Adobe Inc.",
    "ADP": "Automatic Data Processing, Inc.",
    "AEP": "American Electric Power Company, Inc.",
    "AMAT": "Applied Materials, Inc.",
    "AMD": "Advanced Micro Devices, Inc.",
    "AMGN": "Amgen Inc.",
    "AMT": "American Tower Corporation",
    "AMZN": "Amazon.com, Inc.",
    "APD": "Air Products and Chemicals, Inc.",
    "AVGO": "Broadcom Inc.",
    "AXP": "American Express Company",
    "BA": "The Boeing Company",
    "BAC": "Bank of America Corporation",
    "BKNG": "Booking Holdings Inc.",
    "BLK": "BlackRock, Inc.",
    "C": "Citigroup Inc.",
    "CAT": "Caterpillar Inc.",
    "CMCSA": "Comcast Corporation",
    "CMG": "Chipotle Mexican Grill, Inc.",
    "COP": "ConocoPhillips",
    "COST": "Costco Wholesale Corporation",
    "CRM": "Salesforce, Inc.",
    "CSCO": "Cisco Systems, Inc.",
    "CVX": "Chevron Corporation",
    "DE": "Deere & Company",
    "DIS": "The Walt Disney Company",
    "DUK": "Duke Energy Corporation",
    "EOG": "EOG Resources, Inc.",
    "EQIX": "Equinix, Inc.",
    "ETN": "Eaton Corporation plc",
    "FCX": "Freeport-McMoRan Inc.",
    "GE": "GE Aerospace",
    "GILD": "Gilead Sciences, Inc.",
    "GOOGL": "Alphabet Inc.",
    "GS": "The Goldman Sachs Group, Inc.",
    "HD": "The Home Depot, Inc.",
    "HON": "Honeywell International Inc.",
    "IBM": "International Business Machines Corporation",
    "INTU": "Intuit Inc.",
    "ISRG": "Intuitive Surgical, Inc.",
    "JNJ": "Johnson & Johnson",
    "JPM": "JPMorgan Chase & Co.",
    "KO": "The Coca-Cola Company",
    "LIN": "Linde plc",
    "LLY": "Eli Lilly and Company",
    "LMT": "Lockheed Martin Corporation",
    "LOW": "Lowe's Companies, Inc.",
    "MA": "Mastercard Incorporated",
    "MAR": "Marriott International, Inc.",
    "MCD": "McDonald's Corporation",
    "MDLZ": "Mondelez International, Inc.",
    "MDT": "Medtronic plc",
    "META": "Meta Platforms, Inc.",
    "MO": "Altria Group, Inc.",
    "MPC": "Marathon Petroleum Corporation",
    "MRK": "Merck & Co., Inc.",
    "MS": "Morgan Stanley",
    "MSFT": "Microsoft Corporation",
    "MU": "Micron Technology, Inc.",
    "NEE": "NextEra Energy, Inc.",
    "NFLX": "Netflix, Inc.",
    "NKE": "NIKE, Inc.",
    "NOW": "ServiceNow, Inc.",
    "NVDA": "NVIDIA Corporation",
    "ORCL": "Oracle Corporation",
    "ORLY": "O'Reilly Automotive, Inc.",
    "PANW": "Palo Alto Networks, Inc.",
    "PEP": "PepsiCo, Inc.",
    "PG": "The Procter & Gamble Company",
    "PLD": "Prologis, Inc.",
    "PLTR": "Palantir Technologies Inc.",
    "PM": "Philip Morris International Inc.",
    "PSX": "Phillips 66",
    "QCOM": "QUALCOMM Incorporated",
    "RTX": "RTX Corporation",
    "SBUX": "Starbucks Corporation",
    "SCHW": "The Charles Schwab Corporation",
    "SHW": "The Sherwin-Williams Company",
    "SLB": "SLB",
    "SO": "The Southern Company",
    "SPGI": "S&P Global Inc.",
    "SYK": "Stryker Corporation",
    "T": "AT&T Inc.",
    "TJX": "The TJX Companies, Inc.",
    "TMUS": "T-Mobile US, Inc.",
    "TMO": "Thermo Fisher Scientific Inc.",
    "TSLA": "Tesla, Inc.",
    "TXN": "Texas Instruments Incorporated",
    "UNH": "UnitedHealth Group Incorporated",
    "UNP": "Union Pacific Corporation",
    "UPS": "United Parcel Service, Inc.",
    "V": "Visa Inc.",
    "VZ": "Verizon Communications Inc.",
    "WELL": "Welltower Inc.",
    "WFC": "Wells Fargo & Company",
    "WMT": "Walmart Inc.",
    "XOM": "Exxon Mobil Corporation",
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


def get_v5_company_name(symbol):
    """Return dashboard presentation name for a V5 candidate symbol."""
    symbol = symbol.upper().strip()
    try:
        return V5_COMPANY_NAMES[symbol]
    except KeyError as exc:
        raise KeyError(f"Company name is not configured for V5 symbol: {symbol}") from exc


def get_v5_symbol_options():
    """Return ticker/company metadata alphabetically by ticker for selectors."""
    return [
        {"symbol": symbol, "company_name": get_v5_company_name(symbol)}
        for symbol in sorted(V5_SYMBOLS)
    ]


def validate_v5_universe():
    """Fail fast if the research-universe contract is violated."""
    if len(V5_SYMBOLS) != 100:
        raise ValueError(f"Expected 100 V5 candidates, found {len(V5_SYMBOLS)}")
    if len(set(V5_SYMBOLS)) != len(V5_SYMBOLS):
        raise ValueError("V5 candidate symbols must be unique")
    if V5_BENCHMARK_SYMBOL in V5_SYMBOLS:
        raise ValueError("SPY must remain outside the V5 candidate universe")
    if set(V5_COMPANY_NAMES) != set(V5_SYMBOLS):
        missing = sorted(set(V5_SYMBOLS) - set(V5_COMPANY_NAMES))
        extra = sorted(set(V5_COMPANY_NAMES) - set(V5_SYMBOLS))
        raise ValueError(
            "V5 company-name metadata must match the candidate universe; "
            f"missing={missing}, extra={extra}"
        )


validate_v5_universe()


if __name__ == "__main__":
    print(f"V5 candidate equities: {len(V5_SYMBOLS)}")
    print(f"Benchmark (not a candidate): {V5_BENCHMARK_SYMBOL}")
    for sector, symbols in V5_SYMBOLS_BY_SECTOR.items():
        print(f"{sector}: {len(symbols)}")
