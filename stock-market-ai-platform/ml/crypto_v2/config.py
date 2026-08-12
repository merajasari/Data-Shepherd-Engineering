"""Crypto V2 historical research configuration.

Crypto V2 is intentionally isolated from Crypto V1. It may read validated
provider-specific Bronze artifacts, but it must not rewrite or silently merge
them. Canonical source selection is deterministic, provenance-preserving, and
must never depend on realized returns or model performance.
"""

from pathlib import Path

RESEARCH_VERSION = "crypto_v2"
DEFAULT_GRANULARITY = "daily"

BRONZE_ROOT = Path("data/bronze/crypto")
MODEL_ROOT = Path("data/model/crypto_v2")

SOURCE_INVENTORY_PATH = MODEL_ROOT / "source_inventory.csv"
GAP_INVENTORY_PATH = MODEL_ROOT / "gap_inventory.csv"
OVERLAP_DIAGNOSTICS_PATH = MODEL_ROOT / "overlap_diagnostics.csv"
BASELINE_MANIFEST_PATH = MODEL_ROOT / "baseline_manifest.json"
RECONCILIATION_MANIFEST_PATH = MODEL_ROOT / "reconciliation_manifest.json"
CANONICAL_HISTORY_PATH = MODEL_ROOT / "canonical_history.parquet"
CANONICAL_PROVENANCE_PATH = MODEL_ROOT / "canonical_provenance.csv"
CANONICAL_MANIFEST_PATH = MODEL_ROOT / "canonical_manifest.json"

COINBASE_PROVIDER_NAME = "coinbase_exchange"
KRAKEN_PROVIDER_NAME = "kraken_exchange"
CANONICAL_PROVIDER_PRIORITY = (
    COINBASE_PROVIDER_NAME,
    KRAKEN_PROVIDER_NAME,
)

KRAKEN_OHLCVT_ARCHIVE_FILE_ID = "1ptNqWYidLkhb2VAKuLCxmp2OXEfGO-AP"
KRAKEN_OHLCVT_SOURCE_PAGE = (
    "https://support.kraken.com/articles/"
    "360047124832-downloadable-historical-ohlcvt-open-high-low-close-volume-trades-data"
)
KRAKEN_OHLCVT_ARCHIVE_URL = (
    "https://drive.usercontent.google.com/download?export=download&confirm=t&id="
    + KRAKEN_OHLCVT_ARCHIVE_FILE_ID
)

HISTORICAL_POLICY = (
    "Observed provider gaps remain missing. No forward-fill, backward-fill, "
    "interpolation, synthetic OHLCV, silent provider overwrite, or "
    "performance-driven provider selection is permitted."
)

RECONCILIATION_POLICY = (
    "Provider overlap is diagnostic only. Every source observation retains "
    "provenance and no canonical provider is selected in Crypto V2 Phase 1A."
)

CANONICAL_HISTORY_POLICY = (
    "For each product_id and timestamp_utc, select the first valid observed "
    "row according to the pre-registered provider priority: Coinbase Exchange "
    "first, then Kraken Exchange. Kraken may extend history before Coinbase "
    "availability or fill a genuinely absent Coinbase timestamp. OHLCV values "
    "are never averaged, interpolated, synthesized, or selected using future "
    "returns, model performance, or provider disagreement magnitude. The "
    "selected provider is retained on every canonical row."
)
