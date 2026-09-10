"""Regression checks for the read-only V14 ML/AI dashboard payload."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from webapp.services import v14_ml_ai_service as service


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _decision(session: str, cohort: int) -> dict[str, object]:
    rankings = [
        {
            "rank": index + 1,
            "symbol": f"S{index:03d}",
            "predicted_probability": 0.72 - index * 0.002,
            "selected_top10": index < 10,
        }
        for index in range(100)
    ]
    return {
        "event_type": "DECISION",
        "candidate_id": "v14_logistic_walk_forward_top10",
        "decision_timestamp_utc": session,
        "cohort_offset": cohort,
        "symbols": [row["symbol"] for row in rankings[:10]],
        "ranked_predictions": rankings,
        "model_sha256": f"model-{cohort}",
        "training_rows": 125000,
        "training_positive_rate": 0.514,
        "training_start_utc": "2016-01-04T00:00:00+00:00",
        "training_cutoff_utc": "2026-09-03T00:00:00+00:00",
        "model_snapshot": {
            "feature_columns": [
                "daily_return",
                "return_5d",
                "return_20d",
                "price_vs_sma_20",
                "volatility_ratio_5_20",
                "volume_ratio",
            ],
            "weights": [0.12, -0.08, 0.2, 0.05, -0.16, 0.03],
            "bias": 0.01,
            "feature_mean": [0.0] * 6,
            "feature_std": [1.0] * 6,
        },
        "created_at_utc": session,
    }


def main() -> None:
    project_root = Path(__file__).resolve().parents[2]
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        status = root / "status.json"
        refresh = root / "refresh_status.json"
        journal = root / "journal.jsonl"
        live = root / "latest_quotes.json"
        _write_json(
            status,
            {
                "status": "COLLECTING_PAPER_FORWARD",
                "candidate_id": "v14_logistic_walk_forward_top10",
                "contract_sha256": "contract-test-sha",
                "checked_at_utc": "2026-09-15T17:00:00+00:00",
            },
        )
        _write_json(
            refresh,
            {
                "status": "FEATURES_CURRENT",
                "feature_backend": "spark",
                "common_feature_timestamp_utc": "2026-09-14T00:00:00+00:00",
                "required_symbols": 101,
                "ready_for_collection": True,
                "scheduled_network_requests": 0,
            },
        )
        first = _decision("2026-09-11T00:00:00+00:00", 0)
        second = _decision("2026-09-14T00:00:00+00:00", 1)
        first_entry = {
            "event_type": "ENTRY",
            "decision_timestamp_utc": first["decision_timestamp_utc"],
            "cohort_offset": 0,
            "symbols": first["symbols"],
            "entry_timestamp_utc": "2026-09-14T00:00:00+00:00",
            "entry_prices": {symbol: 100.0 for symbol in first["symbols"]},
            "spy_entry_price": 650.0,
            "modeled_cost_rate": 0.001,
        }
        first_exit = {
            "event_type": "EXIT",
            "decision_timestamp_utc": first["decision_timestamp_utc"],
            "cohort_offset": 0,
            "exit_timestamp_utc": "2026-09-21T00:00:00+00:00",
            "net_portfolio_return": 0.02,
            "spy_return": 0.01,
            "net_relative_return": 0.01,
        }
        second_entry = {
            "event_type": "ENTRY",
            "decision_timestamp_utc": second["decision_timestamp_utc"],
            "cohort_offset": 1,
            "symbols": second["symbols"],
            "entry_timestamp_utc": "2026-09-15T00:00:00+00:00",
            "entry_prices": {symbol: 100.0 for symbol in second["symbols"]},
            "spy_entry_price": 650.0,
            "modeled_cost_rate": 0.001,
        }
        journal.write_text(
            "\n".join(
                json.dumps(event)
                for event in (first, first_entry, first_exit, second, second_entry)
            )
            + "\n",
            encoding="utf-8",
        )
        _write_json(
            live,
            {
                "updated_at": "2026-09-15T17:00:00+00:00",
                "quotes": {
                    **{
                        symbol: {
                            "reference_price": 103.0,
                            "timestamp": "2026-09-15T17:00:00+00:00",
                        }
                        for symbol in second["symbols"]
                    },
                    "SPY": {
                        "reference_price": 656.5,
                        "timestamp": "2026-09-15T17:00:00+00:00",
                    },
                },
            },
        )
        service._cache.update(
            {"signature": None, "expires_at": 0.0, "payload": None}
        )
        with (
            patch.object(service, "STATUS_PATH", status),
            patch.object(service, "REFRESH_STATUS_PATH", refresh),
            patch.object(service, "JOURNAL_PATH", journal),
            patch.object(
                service,
                "CONTRACT_PATH",
                project_root / "ml/v14/logistic_forward_contract.json",
            ),
            patch.object(service, "LIVE_QUOTES_PATH", live),
            patch.object(service, "ROLLING_QUOTES_PATHS", ()),
        ):
            payload = service.get_v14_ml_ai_dashboard()

        assert payload["classification"] == "TRAINED_ML_LOGISTIC_REGRESSION_PAPER_FORWARD"
        assert payload["runner_invoked"] is False
        assert payload["brokerage_orders"] is False
        assert payload["v8_modified"] is False and payload["v10_modified"] is False
        assert len(payload["rankings"]) == 100
        assert len(payload["coefficients"]) == 6
        assert len(payload["open_positions"]) == 10
        assert payload["priced_open_cohorts"] == 1
        assert payload["current_equity"] > service.STARTING_EQUITY
        assert payload["current_spy_equity"] > service.STARTING_EQUITY
        assert payload["curve"]
        assert payload["complete_five_sleeve_blocks"] == 0
        assert payload["sleeves_toward_next_block"] == 1
        assert len(payload["event_history"]) == 5
        print("[PASS] V14 dashboard exposes learned model lineage and 100 predictions")
        print("[PASS] V14 dashboard exposes read-only positions and SPY comparison")
        print("[PASS] V14 dashboard cannot invoke runners or modify V8/V10")

    renderer = (
        project_root / "webapp/static/js/v14_ml_ai_dashboard.js"
    ).read_text(encoding="utf-8")
    tabs = (
        project_root / "webapp/static/js/model_research_tabs.js"
    ).read_text(encoding="utf-8")
    app_source = (project_root / "webapp/app.py").read_text(encoding="utf-8")
    assert "V14_ML_AI" in tabs
    assert "research-(overview|v8|v10|v14|v13)" in tabs
    assert "/api/v14/ml-ai" in renderer and "/api/v14/ml-ai" in app_source
    assert "Learned standardized coefficients" in renderer
    assert "100-STOCK ML RANKING BOARD" in renderer
    assert "Interactive paper-forward performance" in renderer
    print("[PASS] V14 tab includes model, ranking, position, and chart surfaces")
    print("Status: PASSED")


if __name__ == "__main__":
    main()
