"""250-stock data and live-observability universe.

This expands market-data coverage without modifying the frozen 100-candidate V5,
V14, or V15 model contracts. SPY remains benchmark-only, so the configured data
universe contains 251 symbols.
"""

from v5_symbols import (
    V5_BENCHMARK_SYMBOL,
    V5_SYMBOLS,
    V5_SYMBOLS_BY_SECTOR,
)

STOCK_250_ADDITIONS_BY_SECTOR = {
    "Communication Services": (
        "FOXA", "CHTR", "WBD", "RBLX", "TTWO", "OMC", "LYV",
    ),
    "Consumer Discretionary": (
        "ROST", "AZO", "GM", "F", "ABNB", "DHI", "LEN", "TGT",
        "YUM", "ULTA", "EBAY", "DECK", "RCL", "CCL", "GPC", "EXPE",
    ),
    "Consumer Staples": (
        "CL", "KMB", "GIS", "KHC", "KR", "SYY", "STZ", "MNST", "ADM", "HSY",
    ),
    "Energy": (
        "OXY", "VLO", "KMI", "WMB", "EQT", "HAL", "DVN", "FANG", "APA",
        "BKR", "TRGP",
    ),
    "Financials": (
        "COF", "USB", "PNC", "TFC", "HOOD", "STT", "CME", "ICE", "MCO", "MSCI",
        "CB", "PGR", "ALL", "AIG", "MET", "PRU", "AFL", "AMP", "AJG", "TRV",
    ),
    "Health Care": (
        "PFE", "BMY", "CVS", "CI", "ELV", "HCA", "BSX", "EW", "ZTS", "REGN",
        "VRTX", "BIIB", "MCK", "COR", "HUM", "DXCM", "IDXX", "IQV", "RMD", "BDX",
    ),
    "Industrials": (
        "MMM", "GD", "NOC", "EMR", "PH", "ITW", "CSX", "NSC", "WM", "RSG",
        "FDX", "PCAR", "CARR", "OTIS", "JCI", "TDG", "FAST", "CPRT", "URI",
        "GWW", "CTAS",
    ),
    "Information Technology": (
        "ACN", "APP", "KLAC", "LRCX", "MCHP", "NXPI", "CDNS", "SNPS", "ANET",
        "FTNT", "CRWD", "MSI", "HPQ", "DELL", "WDAY", "ADSK", "FICO", "MPWR",
        "ON", "TEL", "GLW", "STX",
    ),
    "Materials": (
        "NUE", "NEM", "DOW", "DD", "ECL", "MLM", "VMC", "CTVA",
    ),
    "Real Estate": (
        "O", "PSA", "CCI", "DLR", "SPG", "CBRE", "VICI", "EXR",
    ),
    "Utilities": (
        "SRE", "D", "EXC", "XEL", "ED", "PEG", "PCG",
    ),
}

STOCK_250_SYMBOLS_BY_SECTOR = {
    sector: (*V5_SYMBOLS_BY_SECTOR[sector], *STOCK_250_ADDITIONS_BY_SECTOR[sector])
    for sector in V5_SYMBOLS_BY_SECTOR
}
STOCK_250_SYMBOLS = tuple(
    symbol
    for sector_symbols in STOCK_250_SYMBOLS_BY_SECTOR.values()
    for symbol in sector_symbols
)


def get_stock_250_symbols():
    """Return the 250 investable data/research candidates."""
    return list(STOCK_250_SYMBOLS)


def get_stock_250_data_symbols():
    """Return 250 candidates plus benchmark-only SPY."""
    return [*STOCK_250_SYMBOLS, V5_BENCHMARK_SYMBOL]


def get_stock_250_sector(symbol):
    """Return configured sector metadata for a candidate."""
    for sector, symbols in STOCK_250_SYMBOLS_BY_SECTOR.items():
        if symbol in symbols:
            return sector
    raise KeyError(f"Symbol is not in the 250-stock universe: {symbol}")


def validate_stock_250_universe():
    if len(STOCK_250_SYMBOLS) != 250:
        raise ValueError(f"Expected 250 candidates, found {len(STOCK_250_SYMBOLS)}")
    if len(set(STOCK_250_SYMBOLS)) != 250:
        raise ValueError("250-stock candidates must be unique")
    if not set(V5_SYMBOLS).issubset(STOCK_250_SYMBOLS):
        raise ValueError("Frozen V5 candidates must remain a subset")
    if V5_BENCHMARK_SYMBOL in STOCK_250_SYMBOLS:
        raise ValueError("SPY must remain outside the candidate universe")
    if set(STOCK_250_ADDITIONS_BY_SECTOR) != set(V5_SYMBOLS_BY_SECTOR):
        raise ValueError("Sector keys must match the frozen V5 sector taxonomy")


validate_stock_250_universe()
