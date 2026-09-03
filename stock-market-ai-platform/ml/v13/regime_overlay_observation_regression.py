"""Regression suite for the disabled-by-default V13 observation runner."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile

from ml.v13.regime_overlay_contract import (
    EXPECTED_V10_CANDIDATE,
    EXPECTED_V10_SHA256,
)
from ml.v13.regime_overlay_journal import (
    RegimeOverlayEvidenceJournal,
    V13EvidenceActivationDisabled,
)
from ml.v13.regime_overlay_observation import (
    COMPLETE_INPUT_STATUS,
    COMPLETE_REGIME_STATUS,
    EXPECTED_RANKING_STATUS,
    canonical_sha256,
    run_paired_observation,
    run_session_decision,
    signed_payload,
)


SOURCE = Path(__file__).with_name("regime_overlay_observation.py")


def require(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def fixtures() -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    list[float],
    dict[str, float],
    dict[str, float],
]:
    symbols = [f"S{index:03d}" for index in range(100)]
    ranking = signed_payload(
        {
            "status": EXPECTED_RANKING_STATUS,
            "session_date": "2026-09-03",
            "candidate_id": EXPECTED_V10_CANDIDATE,
            "frozen_spec_sha256": EXPECTED_V10_SHA256,
            "symbols": symbols,
        },
        "ranking_sha256",
    )
    features: dict[str, dict[str, float]] = {
        "SPY": {
            "return_15m": 0.0,
            "volume_acceleration": 0.0,
            "realized_volatility_30m": 0.01,
        }
    }
    for index, symbol in enumerate(symbols):
        features[symbol] = {
            "return_15m": 0.01 if index < 4 else -0.01,
            "volume_acceleration": 1.0 if index < 4 else -1.0,
            "realized_volatility_30m": 0.01 + index / 10000.0,
        }
    prices = {symbol: 50.0 for symbol in symbols}
    spreads = {symbol: 10.0 for symbol in symbols}
    intraday = signed_payload(
        {
            "status": COMPLETE_INPUT_STATUS,
            "session_date": "2026-09-03",
            "collected_at_utc": "2026-09-03T14:00:05+00:00",
            "completed_bar_utc": "2026-09-03T13:55:00+00:00",
            "entry_timestamp_utc": "2026-09-03T14:00:00+00:00",
            "symbol_count": 101,
            "features": features,
            "entry_prices": prices,
            "spreads_bps": spreads,
        },
        "source_snapshot_sha256",
    )
    spy_closes = [100.0 if index % 2 == 0 else 102.0 for index in range(21)]
    regime = signed_payload(
        {
            "status": COMPLETE_REGIME_STATUS,
            "session_date": "2026-09-03",
            "collected_at_utc": "2026-09-03T14:00:00+00:00",
            "v10_negative_flags": [True, True],
            "spy_closes": spy_closes,
        },
        "source_regime_sha256",
    )
    return ranking, intraday, regime, spy_closes, prices, spreads


def main() -> None:
    ranking, intraday, regime, spy_closes, prices, spreads = fixtures()
    with tempfile.TemporaryDirectory(prefix="v13_observation_regression_") as directory:
        root = Path(directory)
        journal_path = root / "evidence.jsonl"
        decision = run_session_decision(
            session_date="2026-09-03",
            decision_timestamp_utc="2026-09-03T14:00:00+00:00",
            ranking_snapshot=ranking,
            intraday_snapshot=intraday,
            regime_snapshot=regime,
            journal_path=journal_path,
            rehearsal=True,
        )
        require(decision.event_appended, "First rehearsal decision appends")
        require(decision.regime_eligible, "Negative high-volatility gate activates")
        require(
            decision.action == "APPLY_V13_INTRADAY_CONFIRMATION",
            "Regime-bounded confirmation action is selected",
        )
        require(len(decision.control_symbols) == 10, "V10 control allocates ten positions")
        require(
            decision.challenger_symbols == ("S000", "S001", "S002", "S003"),
            "V11-derived tests retain only confirmed V10-ranked symbols",
        )
        rows = RegimeOverlayEvidenceJournal(journal_path).read()
        require(len(rows) == 1, "Exactly one decision event persists")
        require(rows[0]["fresh_evidence"] is False, "Rehearsal is not fresh evidence")
        require(rows[0]["brokerage_orders"] is False, "Decision has no brokerage authority")
        require(rows[0]["v10_modified"] is False, "Frozen V10 remains unchanged")
        require(rows[0]["v11_modified"] is False, "V11 remains unchanged")

        restart = run_session_decision(
            session_date="2026-09-03",
            decision_timestamp_utc="2026-09-03T14:00:00+00:00",
            ranking_snapshot=ranking,
            intraday_snapshot=intraday,
            regime_snapshot=regime,
            journal_path=journal_path,
            rehearsal=True,
        )
        require(not restart.event_appended, "Decision restart is idempotent")

        exits = {symbol: price * 1.02 for symbol, price in prices.items()}
        observation = run_paired_observation(
            session_date="2026-09-03",
            exit_session_date="2026-09-11",
            exit_timestamp_utc="2026-09-11T20:00:00+00:00",
            exit_prices=exits,
            exit_snapshot_sha256=canonical_sha256(exits),
            completed_holding_sessions=5,
            journal_path=journal_path,
            rehearsal=True,
        )
        require(observation.event_appended, "Paired five-session observation appends")
        require(observation.control_net_return > 0, "Control net return is calculated")
        require(observation.challenger_net_return > 0, "Challenger net return is calculated")
        require(
            len(RegimeOverlayEvidenceJournal(journal_path).read()) == 2,
            "Decision and paired observation form one lifecycle",
        )
        duplicate = run_paired_observation(
            session_date="2026-09-03",
            exit_session_date="2026-09-11",
            exit_timestamp_utc="2026-09-11T20:00:00+00:00",
            exit_prices=exits,
            exit_snapshot_sha256=canonical_sha256(exits),
            completed_holding_sessions=5,
            journal_path=journal_path,
            rehearsal=True,
        )
        require(not duplicate.event_appended, "Observation restart is idempotent")

        outside_path = root / "outside.jsonl"
        outside_regime = deepcopy(regime)
        outside_regime["v10_negative_flags"] = [False, True]
        outside_regime.pop("source_regime_sha256")
        outside_regime = signed_payload(outside_regime, "source_regime_sha256")
        outside = run_session_decision(
            session_date="2026-09-03",
            decision_timestamp_utc="2026-09-03T14:00:00+00:00",
            ranking_snapshot=ranking,
            intraday_snapshot=intraday,
            regime_snapshot=outside_regime,
            journal_path=outside_path,
            rehearsal=True,
        )
        require(not outside.regime_eligible, "Outside-regime session remains ineligible")
        require(
            outside.challenger_symbols == outside.control_symbols,
            "Outside regime executes the unchanged V10 control",
        )

        incomplete = deepcopy(intraday)
        incomplete["status"] = "INCOMPLETE_V13_FRESH_INPUT_SNAPSHOT"
        incomplete["symbol_count"] = 100
        incomplete["features"].pop("S099")
        incomplete.pop("source_snapshot_sha256")
        incomplete = signed_payload(incomplete, "source_snapshot_sha256")
        held = run_session_decision(
            session_date="2026-09-03",
            decision_timestamp_utc="2026-09-03T14:00:00+00:00",
            ranking_snapshot=ranking,
            intraday_snapshot=incomplete,
            regime_snapshot=regime,
            journal_path=root / "incomplete.jsonl",
            rehearsal=True,
        )
        require(
            held.hold_reason == "MISSING_INTRADAY_CONFIRMATION_HOLD_CASH"
            and not held.challenger_symbols,
            "Incomplete intraday input holds challenger cash",
        )

        incomplete_regime = deepcopy(regime)
        incomplete_regime["status"] = "INCOMPLETE_V13_REGIME_INPUT_SNAPSHOT"
        incomplete_regime["spy_closes"] = spy_closes[:-1]
        incomplete_regime.pop("source_regime_sha256")
        incomplete_regime = signed_payload(incomplete_regime, "source_regime_sha256")
        missing_regime = run_session_decision(
            session_date="2026-09-03",
            decision_timestamp_utc="2026-09-03T14:00:00+00:00",
            ranking_snapshot=ranking,
            intraday_snapshot=intraday,
            regime_snapshot=incomplete_regime,
            journal_path=root / "missing_regime.jsonl",
            rehearsal=True,
        )
        require(
            missing_regime.hold_reason == "MISSING_REGIME_INPUT_HOLD_CASH",
            "Missing regime input fails closed to cash",
        )

        wide_intraday = deepcopy(intraday)
        wide_intraday["spreads_bps"]["S000"] = 21.0
        wide_intraday.pop("source_snapshot_sha256")
        wide_intraday = signed_payload(wide_intraday, "source_snapshot_sha256")
        outside_flat = deepcopy(regime)
        outside_flat["v10_negative_flags"] = [False, False]
        outside_flat.pop("source_regime_sha256")
        outside_flat = signed_payload(outside_flat, "source_regime_sha256")
        spread_hold = run_session_decision(
            session_date="2026-09-03",
            decision_timestamp_utc="2026-09-03T14:00:00+00:00",
            ranking_snapshot=ranking,
            intraday_snapshot=wide_intraday,
            regime_snapshot=outside_flat,
            journal_path=root / "spread.jsonl",
            rehearsal=True,
        )
        require(
            spread_hold.hold_reason == "MISSING_QUOTE_OR_SPREAD_HOLD_CASH",
            "Spread above twenty basis points holds cash",
        )

        tampered = deepcopy(ranking)
        tampered["symbols"] = list(reversed(tampered["symbols"]))
        try:
            run_session_decision(
                session_date="2026-09-03",
                decision_timestamp_utc="2026-09-03T14:00:00+00:00",
                ranking_snapshot=tampered,
                intraday_snapshot=intraday,
                regime_snapshot=regime,
                journal_path=root / "tampered.jsonl",
                rehearsal=True,
            )
        except ValueError:
            require(True, "Tampered V10 ranking snapshot fails closed")
        else:
            raise AssertionError("Tampered V10 ranking snapshot fails closed")

        production_path = root / "production.jsonl"
        try:
            run_session_decision(
                session_date="2026-09-03",
                decision_timestamp_utc="2026-09-03T14:00:00+00:00",
                ranking_snapshot=ranking,
                intraday_snapshot=intraday,
                regime_snapshot=regime,
                journal_path=production_path,
                rehearsal=False,
            )
        except V13EvidenceActivationDisabled:
            require(True, "Production execution remains disabled")
        else:
            raise AssertionError("Production execution remains disabled")
        require(not production_path.exists(), "Disabled production run writes no journal")

    source = SOURCE.read_text(encoding="utf-8").lower()
    require("request.get" not in source, "Runner performs no market request")
    require("import alpaca" not in source, "Alpaca SDK is absent")
    require("robin_stocks" not in source, "Robinhood SDK is absent")
    require("ib_insync" not in source, "IBKR SDK is absent")
    require("enabled_fresh_evidence_paper_only" not in source, "No activation state is introduced")

    print("Status: PASSED")
    print("V13 decision -> paired five-session observation: VERIFIED REHEARSAL ONLY")
    print("Fresh evidence activation: DISABLED")
    print("Production evidence modified: NO")
    print("Brokerage orders: OFF")
    print("V8/V10/V11/V12 production modified: NO")


if __name__ == "__main__":
    main()
