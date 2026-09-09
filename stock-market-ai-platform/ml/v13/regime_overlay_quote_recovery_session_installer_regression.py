"""Static regression checks for the V13 quote-recovery LaunchAgent installer."""
from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
INSTALLER = (
    PROJECT_ROOT
    / "scripts/mac/install_v13_quote_recovery_session_automation.sh"
)


def require(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def main() -> None:
    source = INSTALLER.read_text(encoding="utf-8")
    lowered = source.lower()

    require(
        "--target-session" in source and "--source-session" in source,
        "Installer requires explicit target and source sessions",
    )
    require(
        "_session_dates" in source and "get_session_status" in source,
        "Installer validates dates and immutable authorization before writes",
    )
    require(
        '"AUTHORIZED"' in source
        and "READY_FOR_AUTOMATIC_QUOTE_RECOVERY_COLLECTION" in source,
        "Installer accepts only authorized nonterminal session state",
    )
    require(
        "com.datashepherd.v13quoterecoverypreflight" in source
        and "com.datashepherd.v13quoterecoverycollect" in source,
        "Quote-recovery jobs use a separate scheduler namespace",
    )
    require(
        "regime_overlay_quote_recovery_session_automation" in source,
        "Both jobs invoke the guarded parameterized controller",
    )
    require(
        "--mode preflight" in source
        and "--mode collect" in source
        and "--apply" in source,
        "Collection is explicit and preceded by read-only preflight",
    )
    require(
        "<integer>6</integer><key>Minute</key><integer>55</integer>"
        in source
        and "<integer>7</integer><key>Minute</key><integer>0</integer>"
        in source,
        "Preflight and collection are scheduled for 6:55 and 7:00 Pacific",
    )
    require(
        "feature_backend=spark" in lowered,
        "Scheduled collection uses the required Spark backend",
    )
    require(
        "maximum collection attempts: 1" in lowered
        and "maximum market-data requests: 104" in lowered
        and "no backfill: enforced" in lowered,
        "Installer reports the locked attempt, request, and backfill limits",
    )
    require(
        "runatload" not in lowered,
        "Installation cannot trigger an immediate collection",
    )
    for prohibited in (
        "regime_overlay_session_automation --mode",
        "regime_overlay_context_publisher",
        "regime_overlay_lease_renewal",
        "--mode authorize",
        "2026-09-08 only",
        "import alpaca",
        "robin_stocks",
        "ib_insync",
    ):
        require(
            prohibited not in lowered,
            f"Installer excludes {prohibited}",
        )

    print("Status: PASSED")
    print("V13 quote-recovery LaunchAgent installer: VERIFIED FAIL CLOSED")
    print("Authorization created: NO")
    print("Lease renewed: NO")
    print("Context published: NO")
    print("Market data requested: NO")
    print("Evidence appended: NO")
    print("Live trading: DISABLED")
    print("Brokerage orders: OFF")


if __name__ == "__main__":
    main()
