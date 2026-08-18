"""Apply isolated Stock V7 Phase 8 event-level robustness diagnostics."""

from pathlib import Path

PHASE8 = Path("ml/v7/phase8.py")


def main():
    PHASE8.parent.mkdir(parents=True, exist_ok=True)
    PHASE8.write_text(r'''"""Stock V7 Phase 8: event-level robustness of the breadth effect.

Purpose
-------
Phase 7 found that continuous 5-session breadth retained a positive adjusted
relationship with the fully-confounder-controlled volatility residual after
prior SPY 20-session declines of at least 5%, but most usable observations were
clustered in a few chronological periods.

Phase 8 does not search thresholds or construct a portfolio. It asks whether the
Phase-7 breadth result recurs across distinct market-decline episodes rather
than being dominated by one prolonged episode.

Episode definition
------------------
A decline episode is a maximal consecutive run of SPY trading sessions for which
the already-fixed Phase-7 condition holds: SPY trailing 20-session return <= -5%.
No gap-merging parameter is optimized. If the condition stops for one trading
session, the next qualifying session begins a new episode.

Research safety
---------------
Development diagnostics only. The 2026-09-01+ holdout remains sealed. No model
selection, threshold optimization, portfolio simulation, candidate freeze,
state mutation, or brokerage orders.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.v7.config import FUTURE_HOLDOUT_START_UTC
from ml.v7.phase7 import _build_daily, _ols

PHASE = 8
OUTPUT_ROOT = Path("data/model/v7/phase8")
EPISODE_PATH = OUTPUT_ROOT / "episode_summary.csv"
LOEO_PATH = OUTPUT_ROOT / "leave_one_episode_out.csv"
DAILY_PATH = OUTPUT_ROOT / "daily_episode_map.csv"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"
SPY_FEATURE_PATH = Path("data/features/stocks/SPY/SPY_features.parquet")
MIN_EPISODE_DAYS = 8


def _spy_session_index():
    spy = pd.read_parquet(SPY_FEATURE_PATH).copy()
    ts_col = "timestamp_utc" if "timestamp_utc" in spy.columns else "timestamp"
    spy["timestamp_utc"] = pd.to_datetime(spy[ts_col], utc=True)
    spy = spy.sort_values("timestamp_utc").drop_duplicates("timestamp_utc", keep="last")
    spy = spy[spy["timestamp_utc"] < FUTURE_HOLDOUT_START_UTC].copy()
    spy["session_index"] = np.arange(len(spy), dtype=int)
    return spy[["timestamp_utc", "session_index"]]


def _assign_episodes(daily):
    x = daily.merge(_spy_session_index(), on="timestamp_utc", how="left", validate="one_to_one")
    if x["session_index"].isna().any():
        raise RuntimeError("Missing SPY session index while assigning V7 Phase 8 episodes")
    x = x.sort_values("timestamp_utc").reset_index(drop=True)
    new_episode = x["session_index"].diff().fillna(1).ne(1)
    x["episode_number"] = new_episode.cumsum().astype(int) + 1
    x["episode_id"] = x["episode_number"].map(lambda n: f"episode_{n:02d}")
    return x


def _fit_adjusted(g):
    if len(g) < MIN_EPISODE_DAYS:
        return None
    fit = _ols(
        g["full_confounder_residual_ic"].to_numpy(float),
        np.column_stack([
            g["breadth_5d_centered"].to_numpy(float),
            g["spy_return_5d"].to_numpy(float),
            g["spy_return_20d_ctx"].to_numpy(float),
        ]),
        ["breadth", "spy5", "spy20"],
    )
    return fit


def _episode_summary(daily):
    rows = []
    total_days = len(daily)
    for episode_id, g in daily.groupby("episode_id", sort=True):
        g = g.sort_values("timestamp_utc")
        fit = _fit_adjusted(g)
        rows.append({
            "episode_id": episode_id,
            "start": g["timestamp_utc"].min().isoformat(),
            "end": g["timestamp_utc"].max().isoformat(),
            "days": int(len(g)),
            "observation_fraction": float(len(g) / total_days) if total_days else np.nan,
            "mean_breadth": float(g["breadth_5d_positive_fraction"].mean()),
            "mean_residual_ic": float(g["full_confounder_residual_ic"].mean()),
            "residual_ic_hit_rate": float((g["full_confounder_residual_ic"] > 0).mean()),
            "eligible_episode": bool(len(g) >= MIN_EPISODE_DAYS),
            "breadth_coef_adjusted": fit["coef_breadth"] if fit else np.nan,
            "breadth_t_adjusted": fit["t_breadth"] if fit else np.nan,
            "r2_adjusted": fit["r2"] if fit else np.nan,
        })
    return pd.DataFrame(rows)


def _leave_one_episode_out(daily, episodes):
    rows = []
    for episode_id in episodes["episode_id"]:
        g = daily[daily["episode_id"] != episode_id].copy()
        fit = _fit_adjusted(g)
        removed = episodes[episodes["episode_id"] == episode_id].iloc[0]
        rows.append({
            "removed_episode_id": episode_id,
            "removed_days": int(removed["days"]),
            "remaining_days": int(len(g)),
            "breadth_coef_adjusted": fit["coef_breadth"] if fit else np.nan,
            "breadth_t_adjusted": fit["t_breadth"] if fit else np.nan,
            "r2_adjusted": fit["r2"] if fit else np.nan,
        })
    return pd.DataFrame(rows)


def main():
    daily = _assign_episodes(_build_daily())
    episodes = _episode_summary(daily)
    loeo = _leave_one_episode_out(daily, episodes)

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    daily.to_csv(DAILY_PATH, index=False)
    episodes.to_csv(EPISODE_PATH, index=False)
    loeo.to_csv(LOEO_PATH, index=False)

    eligible = episodes[episodes["eligible_episode"] == True].copy()
    positive_episode_fraction = (
        float((eligible["breadth_coef_adjusted"] > 0).mean()) if len(eligible) else np.nan
    )
    max_episode_fraction = float(episodes["observation_fraction"].max()) if len(episodes) else np.nan
    positive_loeo_fraction = (
        float((loeo["breadth_coef_adjusted"] > 0).mean()) if len(loeo) else np.nan
    )

    overall_fit = _fit_adjusted(daily)
    gates = {
        "at_least_three_distinct_decline_episodes": bool(len(episodes) >= 3),
        "at_least_three_eligible_episodes": bool(len(eligible) >= 3),
        "positive_eligible_episode_fraction_at_least_two_thirds": bool(
            np.isfinite(positive_episode_fraction) and positive_episode_fraction >= 2/3
        ),
        "no_single_episode_exceeds_half_of_observations": bool(
            np.isfinite(max_episode_fraction) and max_episode_fraction <= 0.50
        ),
        "leave_one_episode_out_positive_fraction_at_least_two_thirds": bool(
            np.isfinite(positive_loeo_fraction) and positive_loeo_fraction >= 2/3
        ),
        "overall_adjusted_breadth_coefficient_positive": bool(
            overall_fit is not None and overall_fit["coef_breadth"] > 0
        ),
    }

    manifest = {
        "research_version": "v7",
        "phase": PHASE,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "stage": "development_only_event_level_breadth_robustness",
        "objective": (
            "Determine whether the Phase-7 adjusted breadth relationship recurs across "
            "distinct prior-SPY-decline episodes rather than being dominated by one prolonged episode."
        ),
        "episode_definition": (
            "maximal consecutive SPY trading-session run satisfying the fixed Phase-7 "
            "condition spy_return_20d <= -0.05; no gap merging or episode threshold tuning"
        ),
        "min_episode_days": MIN_EPISODE_DAYS,
        "total_decline_regime_days": int(len(daily)),
        "total_episodes": int(len(episodes)),
        "eligible_episodes": int(len(eligible)),
        "positive_eligible_episode_fraction": positive_episode_fraction,
        "max_episode_observation_fraction": max_episode_fraction,
        "leave_one_episode_out_positive_fraction": positive_loeo_fraction,
        "overall_adjusted_breadth_coefficient": float(overall_fit["coef_breadth"]) if overall_fit else np.nan,
        "overall_adjusted_breadth_t": float(overall_fit["t_breadth"]) if overall_fit else np.nan,
        "robustness_gates": gates,
        "all_robustness_gates_passed": bool(all(gates.values())),
        "future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "future_holdout_scored": False,
        "candidate_frozen": False,
        "portfolio_simulation": False,
        "research_safety": {
            "v4_modified": False, "v5_modified": False, "v6_modified": False,
            "paper_portfolio_modified": False, "paper_journal_modified": False,
            "crypto_tracks_modified": False, "model_selection": False,
            "portfolio_simulation": False, "portfolio_policy_tuning": False,
            "threshold_optimization": False, "candidate_frozen": False,
            "future_holdout_scored": False, "brokerage_orders": False,
        },
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print("STOCK V7 PHASE 8")
    print("=" * 104)
    print("Event-level robustness of the continuous breadth effect")
    print("Episodes are maximal consecutive runs of the fixed SPY <= -5% 20-session condition")
    print()
    print("===== EPISODE SUMMARY =====")
    print(episodes.to_string(index=False))
    print()
    print("===== LEAVE-ONE-EPISODE-OUT =====")
    print(loeo.to_string(index=False))
    print()
    print("===== ROBUSTNESS GATES =====")
    for key, passed in gates.items():
        print(key, "PASS" if passed else "FAIL")
    print("ALL GATES:", "PASS" if all(gates.values()) else "FAIL")
    print()
    print("No portfolio simulation. No candidate freeze. No holdout score. No orders.")


if __name__ == "__main__":
    main()
''', encoding="utf-8")

    print("[APPLY] ml/v7/phase8.py")
    print()
    print("Stock V7 Phase 8 event-level robustness patch complete.")
    print("Distinct decline episodes + leave-one-episode-out diagnostics only.")
    print("The 2026-09-01+ holdout remains sealed. No portfolio simulation, freeze, or orders.")


if __name__ == "__main__":
    main()
