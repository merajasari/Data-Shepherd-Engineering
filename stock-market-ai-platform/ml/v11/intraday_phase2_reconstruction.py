"""Build the V11 Phase 2 pre-boundary development reconstruction.

The curve applies the locked balanced-momentum Phase 2 rules to the bounded
historical five-minute research dataset. Its post-hoc origin is explicit. It
does not read the fresh Phase 2 evidence journal, select a model, freeze a
model, access V8/V10 production, or grant brokerage authority.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Mapping, Sequence

from ml.v11.intraday_phase2_contract import (
    contract_sha256,
    load_contract as load_phase2_contract,
)
from ml.v11.intraday_walk_forward import (
    Configuration,
    FEATURE_NAMES,
    MANIFEST_PATH,
    _group_sessions,
    _session_observation,
    load_dataset,
    get_v5_data_symbols,
)

ROOT = Path(__file__).resolve().parents[2]
OUTPUT_PATH = (
    ROOT
    / "data/research/v11/intraday/phase2/development_reconstruction.json"
)
STARTING_CAPITAL = 100_000.0


def _sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def _atomic_write(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"), sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def reconstruct(
    manifest: Mapping[str, object],
    dataset: Mapping[str, Sequence[Mapping[str, object]]],
    contract: Mapping[str, object],
) -> dict[str, object]:
    configuration = contract["configuration"]
    config = Configuration(
        config_id=str(configuration["config_id"]),
        holding_bars=int(configuration["holding_bars"]),
        weights={
            name: float(configuration["weights"][name])
            for name in FEATURE_NAMES
        },
    )
    grouped = {
        symbol: _group_sessions(rows)
        for symbol, rows in dataset.items()
    }
    symbols = get_v5_data_symbols()
    common_sessions = sorted(
        set.intersection(*(set(grouped[symbol]) for symbol in symbols))
    )
    if len(common_sessions) < 2:
        raise ValueError("V11_RECONSTRUCTION_INSUFFICIENT_COMMON_SESSIONS")

    decision_index = int(contract["decision_bar_index"])
    exit_index = decision_index + config.holding_bars
    boundary = datetime.fromisoformat(
        str(contract["fresh_confirmation_start_utc"])
    ).astimezone(timezone.utc)
    observations: list[dict[str, object]] = []
    skipped_sessions: list[str] = []
    for index in range(1, len(common_sessions)):
        session = common_sessions[index]
        previous_session = common_sessions[index - 1]
        row = _session_observation(
            session,
            grouped,
            previous_session,
            config,
            decision_bar_index=decision_index,
            top_n=int(contract["top_n"]),
            total_cost_bps=float(
                contract["modeled_total_cost_bps_round_trip"]
            ),
        )
        if row is None:
            skipped_sessions.append(session)
            continue
        spy_bars = grouped["SPY"][session]
        entry_timestamp = str(
            spy_bars[decision_index + 1]["timestamp_utc"]
        )
        exit_timestamp = str(spy_bars[exit_index]["timestamp_utc"])
        exit_utc = datetime.fromisoformat(
            exit_timestamp.replace("Z", "+00:00")
        ).astimezone(timezone.utc)
        if exit_utc >= boundary:
            raise ValueError(
                "V11_RECONSTRUCTION_FRESH_EVIDENCE_BOUNDARY_VIOLATION"
            )
        observations.append(
            {
                **row,
                "entry_timestamp_utc": entry_timestamp,
                "exit_timestamp_utc": exit_timestamp,
            }
        )

    if not observations:
        raise ValueError("V11_RECONSTRUCTION_HAS_NO_ELIGIBLE_SESSIONS")

    equity = STARTING_CAPITAL
    history = [
        {
            "timestamp": observations[0]["entry_timestamp_utc"],
            "equity": STARTING_CAPITAL,
            "source": "V11 Phase 2 development starting capital",
        }
    ]
    for observation in observations:
        equity *= 1.0 + float(observation["strategy_net_return"])
        history.append(
            {
                "timestamp": observation["exit_timestamp_utc"],
                "equity": equity,
                "source": (
                    "V11 Phase 2 post-hoc balanced-momentum "
                    "development reconstruction"
                ),
                "session": observation["session"],
            }
        )

    body: dict[str, object] = {
        "status": "POST_HOC_DEVELOPMENT_RECONSTRUCTION",
        "classification": "V11_PHASE2_DEVELOPMENT_ONLY",
        "configuration": config.config_id,
        "contract_sha256": contract_sha256(contract),
        "source_manifest_sha256": manifest["manifest_sha256"],
        "source_window_start": manifest.get("first_common_session"),
        "source_window_end": manifest.get("last_common_session"),
        "fresh_confirmation_start_utc": contract[
            "fresh_confirmation_start_utc"
        ],
        "starting_capital": STARTING_CAPITAL,
        "ending_equity": equity,
        "total_return": equity / STARTING_CAPITAL - 1.0,
        "eligible_sessions": len(observations),
        "skipped_incomplete_sessions": skipped_sessions,
        "modeled_total_cost_bps_round_trip": contract[
            "modeled_total_cost_bps_round_trip"
        ],
        "history": history,
        "post_hoc_origin_disclosed": True,
        "model_frozen": False,
        "fresh_evidence_included": False,
        "fresh_journal_read": False,
        "holdout_outcomes_read": False,
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "brokerage_orders": False,
        "v8_modified": False,
        "v10_modified": False,
    }
    body["reconstruction_sha256"] = _sha(body)
    return body


def run(
    *,
    manifest_path: Path = MANIFEST_PATH,
    output_path: Path = OUTPUT_PATH,
    write: bool = True,
) -> dict[str, object]:
    manifest, dataset = load_dataset(manifest_path)
    contract = load_phase2_contract()
    payload = reconstruct(manifest, dataset, contract)
    payload["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    if write:
        _atomic_write(output_path, payload)
    return payload


def main() -> None:
    payload = run()
    print("V11 PHASE 2 DEVELOPMENT RECONSTRUCTION")
    print("=" * 80)
    print(f"Status: {payload['status']}")
    print(f"Configuration: {payload['configuration']}")
    print(f"Eligible sessions: {payload['eligible_sessions']}")
    print(f"Ending equity: ${payload['ending_equity']:,.2f}")
    print(f"Net return: {payload['total_return']:+.2%}")
    print(f"Reconstruction SHA-256: {payload['reconstruction_sha256']}")
    print("Post-hoc development reconstruction: YES")
    print("Fresh Phase 2 evidence included: NO")
    print("Model frozen: NO")
    print("Paper trading only: YES")
    print("Brokerage orders: OFF")
    print("V8/V10 production modified: NO")


if __name__ == "__main__":
    main()
