"""Linux/systemd adapter for frozen Data Shepherd scheduled entrypoints.

The frozen V8/V10 operational files remain byte-for-byte unchanged.  This
module replaces only the macOS LaunchAgent health probes in memory with
equivalent systemd timer/service checks before invoking the existing reviewed
scheduled entrypoint.

It does not alter model rules, holdout evidence, candidate identities, frozen
hashes, or brokerage-order protections.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SYSTEMD_ROOT = Path("/etc/systemd/system")

CONTRACTS = {
    "v8": {
        "service": "datashepherd-v8paper.service",
        "timer": "datashepherd-v8paper.timer",
        "interval": "OnUnitActiveSec=300s",
        "exec_fragment": "-m ml.linux_scheduler_adapter v8",
    },
    "v10": {
        "service": "datashepherd-v10cycle3.service",
        "timer": "datashepherd-v10cycle3.timer",
        "interval": "OnUnitActiveSec=300s",
        "exec_fragment": "-m ml.linux_scheduler_adapter v10",
    },
}


def _contract(kind: str) -> dict:
    try:
        return CONTRACTS[kind]
    except KeyError as exc:
        raise ValueError(f"Unsupported scheduler: {kind}") from exc


def scheduler_contract_safe(
    kind: str,
    unit_root: Path = SYSTEMD_ROOT,
) -> tuple[bool, str]:
    """Validate the installed Linux scheduler contract without running it."""

    config = _contract(kind)

    service_path = unit_root / config["service"]
    timer_path = unit_root / config["timer"]

    missing = [
        str(path)
        for path in (service_path, timer_path)
        if not path.is_file()
    ]
    if missing:
        return False, "missing unit file(s): " + ", ".join(missing)

    service_text = service_path.read_text(encoding="utf-8")
    timer_text = timer_path.read_text(encoding="utf-8")

    required_service = (
        "User=ubuntu",
        f"WorkingDirectory={PROJECT_ROOT}",
        config["exec_fragment"],
    )

    required_timer = (
        f"Unit={config['service']}",
        config["interval"],
    )

    failures = []

    for value in required_service:
        if value not in service_text:
            failures.append(f"service missing {value!r}")

    for value in required_timer:
        if value not in timer_text:
            failures.append(f"timer missing {value!r}")

    if failures:
        return False, "; ".join(failures)

    return True, (
        f"systemd contract verified: "
        f"{config['service']} + {config['timer']}"
    )


def _systemctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["systemctl", *args],
        text=True,
        capture_output=True,
        check=False,
    )


def scheduler_loaded(kind: str) -> tuple[bool, str]:
    """Treat an enabled, active timer as Linux's LaunchAgent-loaded equivalent."""

    config = _contract(kind)
    timer = config["timer"]

    active = _systemctl("is-active", timer)
    enabled = _systemctl("is-enabled", timer)

    if active.returncode == 0 and enabled.returncode == 0:
        return True, f"{timer} active and enabled"

    active_detail = (
        active.stdout.strip()
        or active.stderr.strip()
        or f"exit={active.returncode}"
    )
    enabled_detail = (
        enabled.stdout.strip()
        or enabled.stderr.strip()
        or f"exit={enabled.returncode}"
    )

    return False, (
        f"{timer} active={active_detail}; "
        f"enabled={enabled_detail}"
    )


def _notification_unavailable(_title: str, _message: str) -> bool:
    """Desktop Notification Center has no Linux equivalent in this service."""

    return False


def _prepare_v8():
    from ml.v8.operational_change_control import verify
    from ml.v8 import operational_monitor

    _, _, failures = verify()
    if failures:
        raise RuntimeError(
            "V8_OPERATIONAL_CHANGE_CONTROL_BLOCKED: "
            + "; ".join(failures)
        )

    operational_monitor._plist_safe = (
        lambda: scheduler_contract_safe("v8")
    )
    operational_monitor._launchagent_loaded = (
        lambda: scheduler_loaded("v8")
    )
    operational_monitor._notify = _notification_unavailable

    from ml.v8.scheduled_entrypoint import main

    return main


def _prepare_v10():
    from ml.v10.cycle3_operational_change_control import verify
    from ml.v10 import cycle3_operational_monitor

    _, _, failures = verify()
    if failures:
        raise RuntimeError(
            "V10_OPERATIONAL_CHANGE_CONTROL_BLOCKED: "
            + "; ".join(failures)
        )

    cycle3_operational_monitor._plist_safe = (
        lambda: scheduler_contract_safe("v10")
    )
    cycle3_operational_monitor._launchagent_loaded = (
        lambda: scheduler_loaded("v10")
    )
    cycle3_operational_monitor._notify = _notification_unavailable

    from ml.v10.cycle3_scheduled_entrypoint import main

    return main


def main(argv=None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "scheduler",
        choices=sorted(CONTRACTS),
    )
    args = parser.parse_args(argv)

    if args.scheduler == "v8":
        entrypoint = _prepare_v8()
    else:
        entrypoint = _prepare_v10()

    print(
        "Linux scheduler adapter: "
        f"{args.scheduler} | "
        "frozen runtime unchanged | brokerage orders OFF"
    )

    entrypoint()


if __name__ == "__main__":
    main()
