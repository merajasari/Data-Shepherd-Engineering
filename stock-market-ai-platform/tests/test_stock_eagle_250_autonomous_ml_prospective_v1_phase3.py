import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import pickle
import tempfile
import unittest

import numpy as np
import pandas as pd
from sklearn.dummy import DummyClassifier, DummyRegressor

from ml.stock_eagle_250_autonomous_ml_prospective_v1.phase3 import (
    EXPECTED_CANDIDATE_ORDER,
    _append_event,
    _read_events,
    _record_missed_decisions,
    _sha256_bytes,
    candidate_realized_return,
    decision_session_allowed_now,
    load_contract,
    run_once,
    score_candidate,
    summarize,
    validate_snapshot_manifest,
)


def _fit_classifier(width, probability_positive=0.5):
    # DummyClassifier(strategy=prior) learns the class prevalence.
    positives = max(1, int(round(20 * probability_positive)))
    positives = min(19, positives)
    y = np.array(
        [1] * positives
        + [0] * (20 - positives),
        dtype=int,
    )
    X = np.zeros((20, width), dtype=float)
    return DummyClassifier(strategy="prior").fit(X, y)


def _candidate_snapshot(candidate_id):
    width = 8 if candidate_id == "autonomous_ml_v1" else 12
    models = {
        "alpha_model":
            DummyRegressor(
                strategy="constant",
                constant=0.02,
            ).fit([[0.0], [1.0]], [0.02, 0.02]),
        "downside_model":
            _fit_classifier(1, 0.25),
        "meta_allocator":
            _fit_classifier(width, 0.65),
    }
    meta_features = [
        "alpha_top10_mean",
        "alpha_top10_min",
        "alpha_top10_vs_next10_gap",
        "alpha_cross_sectional_std",
        "downside_top10_mean",
        "downside_top10_max",
        "downside_top10_std",
    ]
    if candidate_id != "autonomous_ml_v1":
        models["tail_model"] = (
            DummyRegressor(
                strategy="constant",
                constant=-0.03,
            ).fit(
                [[0.0], [1.0]],
                [-0.03, -0.03],
            )
        )
        meta_features.extend([
            "tail10_top10_mean",
            "tail10_top10_min",
            "tail10_top10_std",
            "tail10_cross_sectional_min",
        ])
    meta_features.append("eligible_stock_count")
    return {
        "candidate_id": candidate_id,
        "feature_columns": ["f1"],
        "meta_features": meta_features,
        "models": models,
    }


def _decision_frame():
    return pd.DataFrame({
        "timestamp_utc": [
            pd.Timestamp("2026-10-01", tz="UTC")
        ] * 25,
        "symbol": [
            f"S{index:03d}"
            for index in range(25)
        ],
        "f1": np.linspace(0.0, 1.0, 25),
    })


def _synthetic_manifest(contract, snapshot_rows):
    fixed_source = contract["fixed_source"]
    return {
        "research_version":
            "stock_eagle_250_autonomous_ml_prospective_v1_oct2026",
        "phase": 2,
        "snapshots_built": True,
        "snapshots_fixed_for_prospective_evaluation": True,
        "post_snapshot_retraining_during_evaluation": False,
        "sealed_guard_band_read": False,
        "prospective_rows_read": 0,
        "prospective_performance_calculated": False,
        "automatic_winner_selection": False,
        "automatic_model_promotion": False,
        "brokerage_orders": False,
        "live_execution_enabled": False,
        "source_panel_sha256":
            fixed_source["development_panel_sha256"],
        "source": {
            "training_rows":
                fixed_source["training_rows"],
            "training_decision_end_utc":
                fixed_source["training_decision_end_utc"],
            "training_target_endpoint_max_utc":
                fixed_source["training_target_endpoint_max_utc"],
        },
        "candidate_order":
            list(EXPECTED_CANDIDATE_ORDER),
        "snapshots": snapshot_rows,
    }


class StockEagle250AutonomousMLProspectiveV1Phase3Test(
    unittest.TestCase
):
    def test_contract_seals_exact_snapshots_and_forbids_backfill(self):
        contract = load_contract()
        rows = contract["fixed_snapshots"]

        self.assertEqual(
            tuple(row["candidate_id"] for row in rows),
            EXPECTED_CANDIDATE_ORDER,
        )
        self.assertEqual(
            rows[0]["snapshot_sha256"],
            "4e2b88904f4c17d7df0552559191bf18735ddc5611ee6550731be108f5281932",
        )
        self.assertEqual(
            rows[1]["snapshot_sha256"],
            "d2c1754a54074958567a18c6c2d45bb21d6a0d000ed6bf3d679f8f945766fca5",
        )
        self.assertEqual(
            rows[2]["snapshot_sha256"],
            "aeecdb9f82082163f65ce6b3bb2645472529faa2507a4e0daa34d5802e6b80de",
        )
        self.assertFalse(
            contract["decision_capture"][
                "late_decision_backfill"
            ]
        )
        self.assertFalse(
            contract["authority"][
                "model_retraining_enabled"
            ]
        )

    def test_snapshot_manifest_must_match_fixed_hashes(self):
        contract = load_contract()
        rows = []
        research_versions = {
            "autonomous_ml_v1":
                "stock_eagle_250_autonomous_ml_v1",
            "autonomous_ml_v2":
                "stock_eagle_250_autonomous_ml_v2_tail_aware",
            "autonomous_ml_v3":
                "stock_eagle_250_autonomous_ml_v3_benchmark_relative",
        }
        for fixed in contract["fixed_snapshots"]:
            candidate_id = fixed["candidate_id"]
            rows.append({
                "candidate_id":
                    candidate_id,
                "research_version":
                    research_versions[candidate_id],
                "snapshot_sha256":
                    fixed["snapshot_sha256"],
                "learned_component_count":
                    fixed["learned_component_count"],
                "meta_oos_training_sessions":
                    fixed["meta_oos_training_sessions"],
                "training_cutoff_utc":
                    fixed["training_cutoff_utc"],
                "meta_oos_cutoff_utc":
                    fixed["meta_oos_cutoff_utc"],
                "feature_count": 1,
                "meta_feature_count":
                    8 if candidate_id == "autonomous_ml_v1" else 12,
            })
        manifest = _synthetic_manifest(
            contract,
            rows,
        )
        validate_snapshot_manifest(
            manifest,
            contract,
        )

        bad = copy.deepcopy(manifest)
        bad["snapshots"][1][
            "snapshot_sha256"
        ] = "0" * 64
        with self.assertRaisesRegex(
            RuntimeError,
            "snapshot manifest",
        ):
            validate_snapshot_manifest(
                bad,
                contract,
            )

    def test_decision_capture_is_same_new_york_date_only(self):
        decision = pd.Timestamp(
            "2026-10-01",
            tz="UTC",
        )
        same_day_after_close = datetime(
            2026,
            10,
            1,
            21,
            0,
            tzinfo=timezone.utc,
        )
        next_day_before_open = datetime(
            2026,
            10,
            2,
            13,
            0,
            tzinfo=timezone.utc,
        )

        self.assertTrue(
            decision_session_allowed_now(
                decision,
                same_day_after_close,
            )
        )
        self.assertFalse(
            decision_session_allowed_now(
                decision,
                next_day_before_open,
            )
        )

    def test_all_candidates_share_one_frame_but_keep_fixed_residual_policy(self):
        frame = _decision_frame()
        outputs = {
            candidate_id: score_candidate(
                candidate_id,
                _candidate_snapshot(candidate_id),
                frame,
            )
            for candidate_id in EXPECTED_CANDIDATE_ORDER
        }

        for candidate_id, payload in outputs.items():
            self.assertEqual(
                len(payload["selected_symbols"]),
                10,
            )
            self.assertGreater(
                payload["active_weight"],
                0.0,
            )
            account_weight = sum(
                row["account_weight"]
                for row in payload[
                    "selected_positions"
                ]
            )
            self.assertAlmostEqual(
                account_weight,
                payload["active_weight"],
            )

        self.assertGreater(
            outputs["autonomous_ml_v1"][
                "cash_fraction"
            ],
            0.0,
        )
        self.assertEqual(
            outputs["autonomous_ml_v1"][
                "spy_weight"
            ],
            0.0,
        )
        self.assertGreater(
            outputs["autonomous_ml_v2"][
                "cash_fraction"
            ],
            0.0,
        )
        self.assertEqual(
            outputs["autonomous_ml_v2"][
                "spy_weight"
            ],
            0.0,
        )
        self.assertEqual(
            outputs["autonomous_ml_v3"][
                "cash_fraction"
            ],
            0.0,
        )
        self.assertGreater(
            outputs["autonomous_ml_v3"][
                "spy_weight"
            ],
            0.0,
        )

    def test_realized_return_matches_v2_and_v3_cost_semantics(self):
        decision = {
            "active_weight": 0.5,
            "spy_weight": 0.0,
            "cash_fraction": 0.5,
            "selected_positions": [
                {
                    "symbol": "AAA",
                    "active_sleeve_weight": 0.5,
                },
                {
                    "symbol": "BBB",
                    "active_sleeve_weight": 0.5,
                },
            ],
        }
        entry = {
            "AAA": 100.0,
            "BBB": 100.0,
        }
        exit_prices = {
            "AAA": 110.0,
            "BBB": 90.0,
        }

        v2 = candidate_realized_return(
            "autonomous_ml_v2",
            decision,
            entry,
            exit_prices,
            100.0,
            104.0,
        )
        self.assertAlmostEqual(
            v2["active_top10_gross_return"],
            0.0,
        )
        expected_v2 = (
            (1.0 + 0.0)
            * (1.0 - 0.5 * 0.001) ** 2
            - 1.0
        )
        self.assertAlmostEqual(
            v2["primary_net_return"],
            expected_v2,
        )

        v3_decision = {
            **decision,
            "spy_weight": 0.5,
            "cash_fraction": 0.0,
        }
        v3 = candidate_realized_return(
            "autonomous_ml_v3",
            v3_decision,
            entry,
            exit_prices,
            100.0,
            104.0,
        )
        expected_gross = 0.5 * 0.0 + 0.5 * 0.04
        expected_v3 = (
            (1.0 + expected_gross)
            * (1.0 - 0.001) ** 2
            - 1.0
        )
        self.assertAlmostEqual(
            v3["blended_gross_return"],
            expected_gross,
        )
        self.assertAlmostEqual(
            v3["primary_net_return"],
            expected_v3,
        )

    def test_append_only_journal_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "journal.jsonl"
            event = {
                "event_type": "DECISION_BATCH",
                "decision_timestamp_utc":
                    "2026-10-01T00:00:00+00:00",
                "value": 1,
            }
            self.assertTrue(
                _append_event(event, path)
            )
            self.assertFalse(
                _append_event(
                    {**event, "value": 2},
                    path,
                )
            )
            lines = path.read_text(
                encoding="utf-8"
            ).splitlines()
            self.assertEqual(len(lines), 1)
            self.assertEqual(
                json.loads(lines[0])["value"],
                1,
            )

    def test_formal_review_requires_60_cohorts_and_12_complete_blocks(self):
        contract = load_contract()
        events = []
        for index in range(59):
            candidate_result = {
                candidate_id: {
                    "primary_net_return": 0.01,
                    "stress_20bps_net_return": 0.009,
                    "spy_return": 0.005,
                    "excess_vs_spy": 0.005,
                    "active_weight": 0.5,
                }
                for candidate_id
                in EXPECTED_CANDIDATE_ORDER
            }
            events.append({
                "event_type": "EXIT_BATCH",
                "decision_timestamp_utc":
                    f"2026-10-{(index % 28) + 1:02d}T00:00:00+00:00",
                "exit_timestamp_utc":
                    f"2026-11-{(index % 28) + 1:02d}T00:00:00+00:00",
                "cohort_offset":
                    index % 5,
                "candidates":
                    candidate_result,
            })
        summary = summarize(
            events,
            contract,
        )
        self.assertFalse(
            summary["formal_review_ready"]
        )

        index = 59
        events.append({
            "event_type": "EXIT_BATCH",
            "decision_timestamp_utc":
                "2026-12-01T00:00:00+00:00",
            "exit_timestamp_utc":
                "2026-12-08T00:00:00+00:00",
            "cohort_offset":
                index % 5,
            "candidates": {
                candidate_id: {
                    "primary_net_return": 0.01,
                    "stress_20bps_net_return": 0.009,
                    "spy_return": 0.005,
                    "excess_vs_spy": 0.005,
                    "active_weight": 0.5,
                }
                for candidate_id
                in EXPECTED_CANDIDATE_ORDER
            },
        })
        summary = summarize(
            events,
            contract,
        )
        self.assertTrue(
            summary["formal_review_ready"]
        )
        self.assertEqual(
            summary["complete_five_sleeve_blocks"],
            12,
        )

    def test_missed_decision_is_preserved_without_backfill(self):
        with tempfile.TemporaryDirectory() as temp:
            journal = Path(temp) / "journal.jsonl"
            sessions = [
                pd.Timestamp("2026-10-01", tz="UTC"),
                pd.Timestamp("2026-10-02", tz="UTC"),
            ]
            appended = _record_missed_decisions(
                prospective_sessions=sessions,
                events=[],
                now_utc=datetime(
                    2026,
                    10,
                    2,
                    18,
                    0,
                    tzinfo=timezone.utc,
                ),
                journal_path=journal,
                contract_sha="test-contract",
            )
            self.assertEqual(appended, 1)

            events = _read_events(journal)
            self.assertEqual(
                events[0]["event_type"],
                "MISSED_DECISION",
            )
            self.assertEqual(
                events[0]["decision_timestamp_utc"],
                "2026-10-01T00:00:00+00:00",
            )
            self.assertFalse(
                events[0]["backfilled_decision"]
            )

            appended_again = _record_missed_decisions(
                prospective_sessions=sessions,
                events=events,
                now_utc=datetime(
                    2026,
                    10,
                    2,
                    19,
                    0,
                    tzinfo=timezone.utc,
                ),
                journal_path=journal,
                contract_sha="test-contract",
            )
            self.assertEqual(
                appended_again,
                0,
            )

    def test_preboundary_run_does_not_touch_market_loader(self):
        contract = copy.deepcopy(load_contract())

        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            snapshot_root = temp / "snapshots"
            snapshot_root.mkdir()
            rows = []

            for fixed in contract["fixed_snapshots"]:
                candidate_id = fixed["candidate_id"]
                research_versions = {
                    "autonomous_ml_v1":
                        "stock_eagle_250_autonomous_ml_v1",
                    "autonomous_ml_v2":
                        "stock_eagle_250_autonomous_ml_v2_tail_aware",
                    "autonomous_ml_v3":
                        "stock_eagle_250_autonomous_ml_v3_benchmark_relative",
                }
                meta_count = (
                    8
                    if candidate_id == "autonomous_ml_v1"
                    else 12
                )
                payload = {
                    "candidate_id": candidate_id,
                    "research_version":
                        research_versions[candidate_id],
                    "feature_columns": ["f1"],
                    "meta_features": [
                        f"m{index}"
                        for index in range(meta_count)
                    ],
                    "training_cutoff_utc":
                        fixed["training_cutoff_utc"],
                    "meta_oos_cutoff_utc":
                        fixed["meta_oos_cutoff_utc"],
                    "models": {},
                }
                data = pickle.dumps(
                    payload,
                    protocol=5,
                )
                sha = _sha256_bytes(data)
                fixed["snapshot_sha256"] = sha
                (snapshot_root / f"{candidate_id}.pkl").write_bytes(
                    data
                )
                rows.append({
                    "candidate_id":
                        candidate_id,
                    "research_version":
                        research_versions[candidate_id],
                    "snapshot_sha256":
                        sha,
                    "learned_component_count":
                        fixed["learned_component_count"],
                    "meta_oos_training_sessions":
                        fixed["meta_oos_training_sessions"],
                    "training_cutoff_utc":
                        fixed["training_cutoff_utc"],
                    "meta_oos_cutoff_utc":
                        fixed["meta_oos_cutoff_utc"],
                    "feature_count": 1,
                    "meta_feature_count": meta_count,
                })

            manifest = _synthetic_manifest(
                contract,
                rows,
            )
            manifest_path = temp / "manifest.json"
            manifest_path.write_text(
                json.dumps(manifest),
                encoding="utf-8",
            )

            called = {"market": False}

            def forbidden_loader(_root):
                called["market"] = True
                raise AssertionError(
                    "market loader invoked before boundary"
                )

            result = run_once(
                now_utc=datetime(
                    2026,
                    9,
                    30,
                    20,
                    0,
                    tzinfo=timezone.utc,
                ),
                contract=contract,
                phase2_manifest_path=manifest_path,
                snapshot_root=snapshot_root,
                journal_path=temp / "journal.jsonl",
                status_path=temp / "status.json",
                spy_loader_fn=forbidden_loader,
            )

            self.assertEqual(
                result["status"],
                "WAITING_FOR_PROSPECTIVE_BOUNDARY",
            )
            self.assertFalse(called["market"])
            self.assertEqual(
                result["decision_batches"],
                0,
            )


if __name__ == "__main__":
    unittest.main()
