"""Fail-closed archival disposition for V11 Phase 2.

This preserves V11 scientific artifacts and the narrow V11 code dependencies
used by V13 while disabling V11 as an operational market-data consumer.  It
never unloads schedulers itself; the separate macOS installer performs that
recoverable operating-system transition only after this audit passes.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from ml.v11.intraday_phase2_contract import contract_sha256, load_contract
from ml.v11.intraday_phase2_journal import (
    DEFAULT_JOURNAL_PATH,
    Phase2EvidenceJournal,
)
from ml.v11.intraday_phase2_preflight import EXPECTED_CONTRACT_SHA256
from ml.v11.intraday_phase2_scheduled_entrypoint import STATUS_PATH

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = Path(__file__).with_name(
    "intraday_phase2_archive_contract.json"
)
CONTRACT_SHA_PATH = Path(__file__).with_name(
    "intraday_phase2_archive_contract.sha256"
)
ARCHIVE_STATUS_PATH = (
    ROOT / "data/research/v11/intraday/phase2/archive/disposition.json"
)


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def load_archive_contract() -> tuple[dict[str, object], str]:
    payload = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    observed = canonical_sha256(payload)
    expected = CONTRACT_SHA_PATH.read_text(encoding="utf-8").strip()
    if observed != expected:
        raise RuntimeError("V11_ARCHIVE_CONTRACT_SHA_MISMATCH")
    return payload, observed


def _file_sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def _snapshot(path: Path) -> tuple[bool, bytes | None]:
    return path.exists(), path.read_bytes() if path.exists() else None


def _v13_dependency_map(project_root: Path) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for path in sorted((project_root / "ml/v13").glob("*.py")):
        modules: set[str] = set()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and str(node.module).startswith(
                "ml.v11"
            ):
                modules.add(str(node.module))
            elif isinstance(node, ast.Import):
                modules.update(
                    alias.name
                    for alias in node.names
                    if alias.name.startswith("ml.v11")
                )
        if modules:
            result[path.name] = sorted(modules)
    return result


def _atomic_write(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def load_archive_status(
    path: Path = ARCHIVE_STATUS_PATH,
) -> dict[str, object] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    recorded = str(payload.get("archive_manifest_sha256") or "")
    unsigned = dict(payload)
    unsigned.pop("archive_manifest_sha256", None)
    if recorded != canonical_sha256(unsigned):
        raise RuntimeError("V11_ARCHIVE_MANIFEST_SHA_MISMATCH")
    if payload.get("status") != "ARCHIVED_RESEARCH_REFERENCE":
        raise RuntimeError("V11_ARCHIVE_MANIFEST_STATUS_INVALID")
    return payload


def run_archive(
    *,
    apply: bool = False,
    project_root: Path = ROOT,
    journal_path: Path = DEFAULT_JOURNAL_PATH,
    operational_status_path: Path = STATUS_PATH,
    archive_status_path: Path = ARCHIVE_STATUS_PATH,
    now: datetime | None = None,
) -> dict[str, object]:
    archive_contract, archive_contract_sha = load_archive_contract()
    source_contract = load_contract()
    source_sha = contract_sha256(source_contract)
    if source_sha != EXPECTED_CONTRACT_SHA256:
        raise RuntimeError("V11_SOURCE_CONTRACT_SHA_MISMATCH")

    expected_dependencies = {
        str(name): sorted(str(item) for item in modules)
        for name, modules in dict(
            archive_contract["allowed_v13_dependencies"]
        ).items()
    }
    observed_dependencies = _v13_dependency_map(project_root)
    if observed_dependencies != expected_dependencies:
        raise RuntimeError("V11_V13_DEPENDENCY_BOUNDARY_CHANGED")

    before = _snapshot(journal_path)
    events = Phase2EvidenceJournal(journal_path).read()
    existing = load_archive_status(archive_status_path)
    if existing is not None:
        result = dict(existing)
        result["command_status"] = "ALREADY_ARCHIVED"
        return result

    payload: dict[str, object] = {
        "status": "ARCHIVED_RESEARCH_REFERENCE",
        "archived_at_utc": (now or datetime.now(timezone.utc))
        .astimezone(timezone.utc)
        .isoformat(),
        "archive_contract_sha256": archive_contract_sha,
        "source_contract_sha256": source_sha,
        "source_contract_verified": True,
        "journal_event_count": len(events),
        "journal_sha256": _file_sha256(journal_path),
        "operational_status_sha256": _file_sha256(operational_status_path),
        "v13_preserved_dependency_map": observed_dependencies,
        "scheduled_collection_enabled": False,
        "scheduled_alerts_enabled": False,
        "maximum_market_data_requests": 0,
        "evidence_preserved": True,
        "historical_artifacts_modified": False,
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "brokerage_orders": False,
        "v8_modified": False,
        "v10_modified": False,
        "v13_modified": False,
    }
    payload["archive_manifest_sha256"] = canonical_sha256(payload)
    if apply:
        _atomic_write(archive_status_path, payload)
        load_archive_status(archive_status_path)

    if _snapshot(journal_path) != before:
        raise RuntimeError("V11_ARCHIVE_MODIFIED_EVIDENCE")
    result = dict(payload)
    result["command_status"] = (
        "ARCHIVED" if apply else "READY_TO_ARCHIVE"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = run_archive(apply=args.apply)
    print("V11 PHASE 2 ARCHIVAL DISPOSITION")
    print("=" * 80)
    print(f"Status: {result['command_status']}")
    print(f"Disposition: {result['status']}")
    print(f"Journal events preserved: {result['journal_event_count']}")
    print(
        "V13 locked V11 dependencies preserved: "
        f"{len(result['v13_preserved_dependency_map'])} modules"
    )
    print("Scheduled collection enabled: NO")
    print("Scheduled alerts enabled: NO")
    print("Maximum V11 market-data requests: 0")
    print("Historical artifacts modified: NO")
    print("Live trading: DISABLED")
    print("Brokerage orders: OFF")
    print("V8/V10/V13 modified: NO")


if __name__ == "__main__":
    main()
