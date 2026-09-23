"""Shared Crypto V2 Clean Forward V4 isolated paper-evaluation entrypoint.

V4 reuses the unchanged frozen Phase 5 HGB artifact and confirm-2 policy while
placing every stateful output in a new lane. Clean Forward V3 is preserved as
an immutable interrupted parent and is never resumed or backfilled.

Preregistered boundary: 2026-09-23 07:00 UTC (midnight America/Los_Angeles).
Paper evaluation only. No brokerage orders and no automatic promotion.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ml.crypto_15m_v2 import forward_service as service

PHASE5_ROOT = Path("data/model/crypto_15m_v2/phase5")
PARENT_ROOT = PHASE5_ROOT / "clean_forward_v3"
CLEAN_ROOT = PHASE5_ROOT / "clean_forward_v4"
CLEAN_START = pd.Timestamp("2026-09-23T07:00:00Z")
CLEAN_LANE_ID = "shared_crypto_v2_clean_forward_v4"
CLEAN_LANE_NAME = "Shared Crypto V2 Clean Forward V4"


def configure() -> None:
    """Point the proven service implementation at the isolated V4 contract."""
    service.PHASE5_ROOT = PHASE5_ROOT
    service.MODEL_PATH = PHASE5_ROOT / "frozen_hgb.joblib"
    service.MANIFEST_PATH = PHASE5_ROOT / "freeze_manifest.json"

    # V3 is an immutable interrupted parent. V4 never changes or resumes it.
    service.LEGACY_STATE_PATH = PARENT_ROOT / "forward_state.json"
    service.LEGACY_JOURNAL_PATH = PARENT_ROOT / "forward_journal.csv"
    service.LEGACY_STATUS_PATH = PARENT_ROOT / "forward_service_status.json"

    service.CLEAN_ROOT = CLEAN_ROOT
    service.STATE_PATH = CLEAN_ROOT / "forward_state.json"
    service.JOURNAL_PATH = CLEAN_ROOT / "forward_journal.csv"
    service.SHADOW_PATH = CLEAN_ROOT / "waiting_latest.json"
    service.SERVICE_STATUS_PATH = CLEAN_ROOT / "forward_service_status.json"
    service.LOCK_PATH = CLEAN_ROOT / "forward_service.lock"
    service.CLEAN_LANE_MANIFEST_PATH = CLEAN_ROOT / "clean_lane_manifest.json"

    service.CLEAN_START = CLEAN_START
    service.CLEAN_LANE_ID = CLEAN_LANE_ID
    service.CLEAN_LANE_NAME = CLEAN_LANE_NAME


def main(argv=None) -> None:
    configure()
    service.main(argv)


if __name__ == "__main__":
    main()
