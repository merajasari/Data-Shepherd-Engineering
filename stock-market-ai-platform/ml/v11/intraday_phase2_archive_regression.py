"""Regression coverage for the V11 Phase 2 archival disposition."""
from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

from ml.v11.intraday_phase2_archive import (
    load_archive_contract,
    load_archive_status,
    run_archive,
)


def require(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def _write_dependencies(root: Path) -> None:
    target = root / "ml/v13"
    target.mkdir(parents=True)
    (target / "regime_overlay_backfill.py").write_text(
        "from ml.v11.intraday_backfill import build_intraday_panel\n"
    )
    (target / "regime_overlay_input_snapshot.py").write_text(
        "from ml.v11.intraday_contract import "
        "derive_features, validate_completed_bars\n"
    )
    (target / "regime_overlay_reconstruction.py").write_text(
        "from ml.v11.intraday_contract import derive_features\n"
        "from ml.v11.intraday_walk_forward import load_dataset\n"
    )


def main() -> None:
    contract, observed_sha = load_archive_contract()
    require(
        observed_sha
        == "9e5de39b793a7fe1864df0f0298abc7e92291838099cb593ba07254cf0fa3a6c",
        "Archive disposition contract identity is locked",
    )
    require(
        contract["disposition"] == "ARCHIVED_RESEARCH_REFERENCE",
        "V11 disposition is an archived research reference",
    )

    with tempfile.TemporaryDirectory(prefix="v11_phase2_archive_") as raw:
        root = Path(raw)
        _write_dependencies(root)
        journal = root / "evidence.jsonl"
        operational = root / "operational_status.json"
        archive = root / "archive/disposition.json"
        operational.write_text('{"status":"HEALTHY_PAPER_CONFIRMATION"}\n')
        evidence_before = journal.exists(), None

        ready = run_archive(
            project_root=root,
            journal_path=journal,
            operational_status_path=operational,
            archive_status_path=archive,
            now=datetime(2026, 9, 9, 18, 0, tzinfo=timezone.utc),
        )
        require(
            ready["command_status"] == "READY_TO_ARCHIVE"
            and not archive.exists(),
            "Readiness audit performs no writes",
        )
        require(
            ready["v13_preserved_dependency_map"]
            == contract["allowed_v13_dependencies"],
            "Exact V13 dependencies on locked V11 code are preserved",
        )

        applied = run_archive(
            apply=True,
            project_root=root,
            journal_path=journal,
            operational_status_path=operational,
            archive_status_path=archive,
            now=datetime(2026, 9, 9, 18, 1, tzinfo=timezone.utc),
        )
        require(
            applied["command_status"] == "ARCHIVED"
            and archive.exists(),
            "Archival disposition is persisted separately",
        )
        require(
            load_archive_status(archive)["archive_manifest_sha256"]
            == applied["archive_manifest_sha256"],
            "Archive manifest identity validates",
        )
        require(
            (journal.exists(), journal.read_bytes() if journal.exists() else None)
            == evidence_before,
            "V11 evidence remains byte-for-byte unchanged",
        )
        require(
            applied["maximum_market_data_requests"] == 0
            and applied["scheduled_collection_enabled"] is False
            and applied["scheduled_alerts_enabled"] is False,
            "Archived V11 has no scheduled collection or request budget",
        )
        require(
            applied["live_trading_enabled"] is False
            and applied["brokerage_orders"] is False,
            "Archive transition has no trading authority",
        )
        repeated = run_archive(
            apply=True,
            project_root=root,
            journal_path=journal,
            operational_status_path=operational,
            archive_status_path=archive,
        )
        require(
            repeated["command_status"] == "ALREADY_ARCHIVED",
            "Archive transition is restart-safe",
        )

    with tempfile.TemporaryDirectory(prefix="v11_phase2_drift_") as raw:
        root = Path(raw)
        _write_dependencies(root)
        (root / "ml/v13/unexpected.py").write_text(
            "from ml.v11.intraday_phase2_observation import run\n"
        )
        blocked = False
        try:
            run_archive(
                project_root=root,
                journal_path=root / "evidence.jsonl",
                operational_status_path=root / "status.json",
                archive_status_path=root / "archive.json",
            )
        except RuntimeError as exc:
            blocked = str(exc) == "V11_V13_DEPENDENCY_BOUNDARY_CHANGED"
        require(blocked, "Unexpected V13 dependency drift fails closed")
        require(
            not (root / "archive.json").exists(),
            "Rejected dependency audit creates no disposition",
        )

    project_root = Path(__file__).resolve().parents[2]
    source = (project_root / "ml/v11/intraday_phase2_archive.py").read_text()
    installer = (
        project_root / "scripts/mac/archive_v11_phase2.sh"
    ).read_text()
    require("launchctl" not in source, "Python disposition changes no scheduler")
    require("requests." not in source, "Archive disposition requests no data")
    require(".unlink(" not in source, "Archive disposition deletes no artifact")
    require(
        "com.datashepherd.v11phase2" in installer
        and "com.datashepherd.v11phase2alerts" in installer,
        "Installer disables both V11 LaunchAgents",
    )
    require(
        "DataShepherdArchive" in installer and "mv \"$plist\"" in installer,
        "LaunchAgent files are archived recoverably",
    )

    print("\nStatus: PASSED")
    print("V11 Phase 2 archival transition: VERIFIED FAIL CLOSED")
    print("V11 evidence and research artifacts modified: NO")
    print("V13 locked dependencies removed: NO")
    print("Ongoing V11 Tiingo requests after apply: 0")
    print("Brokerage orders: OFF")


if __name__ == "__main__":
    main()
