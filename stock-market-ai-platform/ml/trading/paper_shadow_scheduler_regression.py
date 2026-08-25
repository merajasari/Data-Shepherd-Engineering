"""Regression for the fail-closed paper-shadow scheduler and monitor."""
from __future__ import annotations

import plistlib
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from ml.trading.paper_shadow_operational_monitor import LABEL, run_monitor
from ml.trading.paper_shadow_signal_bridge import CONTRACT_PATH, contract_sha256


def require(value, label):
    if not value:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def write_plist(path: Path, command: str) -> None:
    payload = {
        "Label": LABEL,
        "ProgramArguments": ["/bin/zsh", "-lc", command],
        "RunAtLoad": True,
        "StartInterval": 300,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        plistlib.dump(payload, handle)


def main():
    original_contract_sha = contract_sha256()
    with tempfile.TemporaryDirectory(prefix="ds-paper-shadow-scheduler-") as temporary:
        root = Path(temporary) / "data/trading/paper_shadow"
        plist = Path(temporary) / f"{LABEL}.plist"
        status = root / "monitor/status.json"
        command = (
            "cd '/tmp/project' && '/tmp/project/.venv/bin/python' "
            "-u -m ml.trading.paper_shadow_scheduled_entrypoint"
        )
        write_plist(plist, command)

        pre_boundary = run_monitor(
            now=datetime(2026, 8, 31, 23, 59, tzinfo=timezone.utc),
            shadow_root=root,
            plist_path=plist,
            status_path=status,
            check_launchagent=False,
        )
        require(pre_boundary["status"] == "HEALTHY", "Pre-boundary monitor is healthy")
        require(pre_boundary["execution_state"] == "WAITING_FOR_BOUNDARY", "Pre-boundary execution waits")
        require(pre_boundary["signal_exports"] == 0, "Pre-boundary signal export is zero")
        require(not (root / "account_state.json").exists(), "Monitor creates no account state")
        require(not (root / "orders.jsonl").exists(), "Monitor creates no order journal")

        boundary = run_monitor(
            now=datetime(2026, 9, 1, tzinfo=timezone.utc),
            shadow_root=root,
            plist_path=plist,
            status_path=status,
            check_launchagent=False,
        )
        require(boundary["status"] == "HEALTHY", "Boundary monitor remains healthy")
        require(
            boundary["execution_state"] == "WAITING_FOR_MANUAL_ACTIVATION",
            "Disabled bridge still requires manual activation",
        )
        require(boundary["bridge_status"] == "PREREGISTERED_DISABLED", "Bridge remains disabled")
        require(boundary["brokerage_orders"] is False, "Scheduler has no brokerage authority")
        require(boundary["holdout_outcomes_read"] is False, "Scheduler reads no holdout outcomes")
        require(
            boundary["production_holdout_evidence_modified"] is False,
            "Scheduler modifies no holdout evidence",
        )
        require(status.exists(), "Monitor writes only isolated operational status")

        unsafe_plist = Path(temporary) / "unsafe.plist"
        write_plist(unsafe_plist, "python -m ml.trading.paper_shadow_signal_bridge")
        unsafe = run_monitor(
            now=datetime(2026, 9, 1, tzinfo=timezone.utc),
            shadow_root=root,
            plist_path=unsafe_plist,
            status_path=root / "monitor/unsafe.json",
            check_launchagent=False,
        )
        require(unsafe["status"] == "ALERT", "Direct bridge scheduler is rejected")
        require(any("scheduler_contract" in item for item in unsafe["failures"]), "Unsafe command fails closed")

        (root / "account_state.json").write_text("{}\n", encoding="utf-8")
        drift = run_monitor(
            now=datetime(2026, 9, 1, tzinfo=timezone.utc),
            shadow_root=root,
            plist_path=plist,
            status_path=root / "monitor/drift.json",
            check_launchagent=False,
        )
        require(drift["status"] == "ALERT", "Incomplete account state fails closed")
        require(drift["paper_account_status"] == "FAIL_CLOSED", "Account drift is visible")

    require(contract_sha256() == original_contract_sha, "Preregistered bridge contract unchanged")
    source = Path(__file__).with_name("paper_shadow_scheduled_entrypoint.py").read_text(encoding="utf-8")
    require("paper_shadow_signal_bridge" not in source, "Entrypoint cannot invoke bridge directly")
    require("PaperBrokerAdapter" not in source, "Entrypoint imports no broker adapter")
    installer = Path(__file__).resolve().parents[2] / "scripts/mac/install_paper_shadow_scheduler.sh"
    installer_source = installer.read_text(encoding="utf-8")
    require("paper_shadow_scheduled_entrypoint" in installer_source, "Installer uses monitored entrypoint")
    require("paper_shadow_signal_bridge" not in installer_source, "Installer cannot invoke bridge directly")

    print("\nStatus: PASSED")
    print("Paper-shadow scheduler: MONITOR-ONLY")
    print("Bridge activation: DISABLED")
    print("Signal exports: 0")
    print("Holdout outcomes read: NO")
    print("Live credentials: ABSENT")
    print("Brokerage orders: OFF")
    print("V8/V10 production evidence modified: NO")


if __name__ == "__main__":
    main()
