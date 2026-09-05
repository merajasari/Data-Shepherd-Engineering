"""Regression checks for the signed frozen-V10 V13 inbox publisher."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from ml.v13.regime_overlay_context_publisher import (
    _require_contract,
    build_signed_context,
    derive_and_publish,
    publish_signed_context,
)
from ml.v13.regime_overlay_observation import canonical_sha256


SOURCE = Path(__file__).with_name("regime_overlay_context_publisher.py")
TARGET = "2026-09-08"
SOURCE_SESSION = "2026-09-04"
REGIME_SESSIONS = ["2026-09-03", SOURCE_SESSION]
SYMBOLS = [f"S{index:03d}" for index in range(100)]


def require(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def fake_source(_: str):
    return SYMBOLS, [True, True], REGIME_SESSIONS


def main() -> None:
    require(len(_require_contract()) == 64, "Context publisher contract identity is locked")
    ranking, control = build_signed_context(
        session_date=TARGET,
        source_decision_session=SOURCE_SESSION,
        ranked_symbols=SYMBOLS,
        v10_negative_flags=[True, True],
        v10_negative_sessions=REGIME_SESSIONS,
    )
    ranking_body = dict(ranking)
    ranking_sha = ranking_body.pop("ranking_sha256")
    control_body = dict(control)
    control_sha = control_body.pop("control_context_sha256")
    require(
        ranking_sha == canonical_sha256(ranking_body)
        and control_sha == canonical_sha256(control_body),
        "Ranking and regime context are canonically signed",
    )
    require(
        ranking["symbols"] == SYMBOLS and len(ranking["symbols"]) == 100,
        "Exact ordered 100-symbol ranking is preserved",
    )
    require(
        control["source_decision_sessions"] == REGIME_SESSIONS
        and control["v10_negative_flags"] == [True, True],
        "Two flags bind their exact completed-session dates",
    )
    require(
        ranking["holdout_outcomes_read"] is False
        and control["holdout_outcomes_read"] is False,
        "Published context attests that holdout outcomes were not read",
    )

    try:
        build_signed_context(
            session_date=TARGET,
            source_decision_session=SOURCE_SESSION,
            ranked_symbols=SYMBOLS[:-1],
            v10_negative_flags=[True, True],
            v10_negative_sessions=REGIME_SESSIONS,
        )
    except ValueError:
        require(True, "Incomplete frozen ranking fails closed")
    else:
        raise AssertionError("Incomplete frozen ranking fails closed")

    try:
        build_signed_context(
            session_date=TARGET,
            source_decision_session=SOURCE_SESSION,
            ranked_symbols=SYMBOLS,
            v10_negative_flags=[True, True],
            v10_negative_sessions=["2026-09-02", "2026-09-03"],
        )
    except ValueError:
        require(True, "Regime dates not ending at the ranking session fail closed")
    else:
        raise AssertionError("Regime dates not ending at the ranking session fail closed")

    with TemporaryDirectory(prefix="v13_context_publisher_regression_") as directory:
        inbox = Path(directory) / "inbox"
        publication = derive_and_publish(
            session_date=TARGET,
            source_decision_session=SOURCE_SESSION,
            now_utc=datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc),
            inbox_root=inbox,
            source_loader=fake_source,
        )
        target = inbox / TARGET
        require(
            publication.published
            and {item.name for item in target.iterdir()}
            == {"ranking_snapshot.json", "control_context.json"},
            "Injected read-only source publishes exactly one immutable inbox pair",
        )
        original = {item.name: item.read_bytes() for item in target.iterdir()}
        duplicate = derive_and_publish(
            session_date=TARGET,
            source_decision_session=SOURCE_SESSION,
            now_utc=datetime(2026, 9, 5, 12, 1, tzinfo=timezone.utc),
            inbox_root=inbox,
            source_loader=fake_source,
        )
        require(
            duplicate.status == "DUPLICATE_SAFE_NOOP" and not duplicate.published,
            "Identical publication restart is duplicate-safe",
        )

        tampered = deepcopy(control)
        tampered["v10_negative_flags"] = [False, True]
        try:
            publish_signed_context(
                session_date=TARGET,
                source_decision_session=SOURCE_SESSION,
                ranking_snapshot=ranking,
                control_context=tampered,
                inbox_root=inbox,
            )
        except ValueError:
            require(
                original == {item.name: item.read_bytes() for item in target.iterdir()},
                "Tampered context is rejected before immutable inbox changes",
            )
        else:
            raise AssertionError("Tampered context is rejected before immutable inbox changes")

    source_calls = 0

    def counted_source(_: str):
        nonlocal source_calls
        source_calls += 1
        return fake_source("")

    try:
        derive_and_publish(
            session_date=TARGET,
            source_decision_session=SOURCE_SESSION,
            now_utc=datetime(2026, 9, 8, 14, 5, tzinfo=timezone.utc),
            source_loader=counted_source,
        )
    except RuntimeError:
        require(source_calls == 0, "Late publication fails before loading frozen context")
    else:
        raise AssertionError("Late publication fails before loading frozen context")

    source = SOURCE.read_text(encoding="utf-8").lower()
    for prohibited in (
        "requests.",
        "httpx",
        "urlopen",
        "commit_session_decision",
        "regimeoverlayevidencejournal",
        "launchctl",
        "crontab",
        "import alpaca",
        "robin_stocks",
        "ib_insync",
    ):
        require(prohibited not in source, f"Context publisher excludes {prohibited}")

    print("Status: PASSED")
    print("V13 frozen ranking + exact regime dates -> signed inbox: VERIFIED")
    print("Market data requested: NO")
    print("Holdout outcomes read: NO")
    print("V13 evidence appended: NO")
    print("Scheduler installed or changed: NO")
    print("Brokerage orders: OFF")


if __name__ == "__main__":
    main()
