"""Crypto V2 historical research configuration.

Crypto V2 is intentionally isolated from Crypto V1. It may read validated
provider-specific Bronze artifacts, but it must not rewrite or silently merge
them. Canonical source selection is deferred until overlap diagnostics exist.
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

HISTORICAL_POLICY = (
    "Observed provider gaps remain missing. No forward-fill, backward-fill, "
    "interpolation, synthetic OHLCV, silent provider overwrite, or "
    "performance-driven provider selection is permitted."
)

RECONCILIATION_POLICY = (
    "Provider overlap is diagnostic only. Every source observation retains "
    "provenance and no canonical provider is selected in Crypto V2 Phase 1A."
)
