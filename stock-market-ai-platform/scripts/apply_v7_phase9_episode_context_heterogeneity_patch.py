"""Apply isolated Stock V7 Phase 9 episode-context heterogeneity diagnostics."""

from pathlib import Path

PHASE9 = Path("ml/v7/phase9.py")


def main():
    PHASE9.parent.mkdir(parents=True, exist_ok=True)
    PHASE9.write_text(r'''"""Stock V7 Phase 9: fixed episode-context heterogeneity diagnostics.

Purpose
-------
Phase 8 showed that the aggregate Phase-7 breadth coefficient is not dominated
by any single decline episode, but the sign of the adjusted breadth coefficient
is inconsistent across eligible episodes. Phase 9 does not attempt to repair
that failed gate. It asks whether the sign/magnitude heterogeneity is associated
with a small fixed set of decision-time market context variables.

Scientific contract
-------------------
* Reuse the fixed Phase-7 decline condition: SPY trailing 20-session return <= -5%.
* Reuse the fixed Phase-8 episode assignment.
* No new threshold search, no state selection, and no portfolio simulation.
* Context variables are continuous and observed at the decision close.
* Interaction models are pre-registered one-variable-at-a-time diagnostics.
* Episode-level summaries use the first qualifying session's context only.
* Phase-8 failure remains permanent evidence; Phase 9 cannot overwrite it.
* The 2026-09-01+ holdout remains sealed.

Research safety
---------------
No model selection, portfolio policy tuning, candidate freeze, holdout scoring,
paper-state mutation, crypto changes, or brokerage orders.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.v7.config import FUTURE_HOLDOUT_START_UTC
from ml.v7.phase7 import _ols
from ml.v7.phase8 import _assign_episodes
from ml.v7.phase7 import _build_daily

PHASE = 9
OUTPUT_ROOT = Path("data/model/v7/phase9")
DAILY_PATH = OUTPUT_ROOT / "daily_context_panel.csv"
INTERACTION_PATH = OUTPUT_ROOT / "interaction_summary.csv"
EPISODE_CONTEXT_PATH = OUTPUT_ROOT / "episode_context_summary.csv"
ELIGIBLE_EPISODE_PATH = OUTPUT_ROOT / "eligible_episode_context.csv"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"
SPY_FEATURE_PATH = Path("data/features/stocks/SPY/SPY_features.parquet")
MIN_EPISODE_DAYS = 8

# Fixed before Phase 9 results are inspected. No context threshold is optimized.
CONTEXT_SPECS = {
    "SPY_5D_RETURN": "spy_return_5d",
    "SPY_20D_DECLINE_DEPTH": "spy_decline_depth_beyond_5pct",
    "SPY_DISTANCE_FROM_20D_LOW": "spy_distance_from_20d_low",
    "SPY_20D_VOLATILITY": "spy_volatility_20d",
}


def _load_spy_context():
    if not SPY_FEATURE_PATH.exists():
        raise FileNotFoundError(f"Missing SPY features: {SPY_FEATURE_PATH}")
    spy = pd.read_parquet(SPY_FEATURE_PATH).copy()
    ts_col = "timestamp_utc" if "timestamp_utc" in spy.columns else "timestamp"
    spy["timestamp_utc"] = pd.to_datetime(spy[ts_col], utc=True)
    spy = spy.sort_values("timestamp_utc").drop_duplicates("timestamp_utc", keep="last")

    required = {"timestamp_utc", "close", "return_5d", "return_20d", "daily_return"}
    missing = sorted(required - set(spy.columns))
    if missing:
        raise ValueError("SPY Phase 9 context missing columns: " + ", ".join(missing))

    close = pd.to_numeric(spy["close"], errors="coerce")
    daily_return = pd.to_numeric(spy["daily_return"], errors="coerce")
    low20 = close.rolling(20, min_periods=20).min()

    out = pd.DataFrame({
        "timestamp_utc": spy["timestamp_utc"],
        "spy_return_5d_ctx": pd.to_numeric(spy["return_5d"], errors="coerce"),
        "spy_return_20d_ctx2": pd.to_numeric(spy["return_20d"], errors="coerce"),
        "spy_distance_from_20d_low": close / low20 - 1.0,
        "spy_volatility_20d": daily_return.rolling(20, min_periods=20).std(ddof=0),
    })
    out["spy_decline_depth_beyond_5pct"] = -(out["spy_return_20d_ctx2"] + 0.05)
    return out


def _build_context_panel():
    daily = _assign_episodes(_build_daily())
    daily = daily.merge(
        _load_spy_context(), on="timestamp_utc", how="left", validate="one_to_one"
    )
    # Reuse Phase-7 context field as the canonical 5-day return so that the
    # baseline model exactly matches the earlier specification.
    daily["spy_return_5d"] = pd.to_numeric(daily["spy_return_5d"], errors="coerce")
    return daily.sort_values("timestamp_utc").reset_index(drop=True)


def _zscore(s):
    s = pd.Series(s, dtype=float)
    sd = float(s.std(ddof=0))
    if not np.isfinite(sd) or sd <= 1e-12:
        return pd.Series(np.nan, index=s.index)
    return (s - float(s.mean())) / sd


def _interaction_summary(daily):
    rows = []
    base_cols = [
        "full_confounder_residual_ic",
        "breadth_5d_centered",
        "spy_return_5d",
        "spy_return_20d_ctx",
    ]

    for context_id, context_col in CONTEXT_SPECS.items():
        cols = base_cols + [context_col]
        g = daily[cols].replace([np.inf, -np.inf], np.nan).dropna().copy()
        if len(g) < 30:
            rows.append({
                "context_id": context_id,
                "context_column": context_col,
                "days": int(len(g)),
                "eligible": False,
            })
            continue

        z_context = _zscore(g[context_col])
        z_breadth = _zscore(g["breadth_5d_centered"])
        interaction = z_context * z_breadth

        fit = _ols(
            g["full_confounder_residual_ic"].to_numpy(float),
            np.column_stack([
                g["breadth_5d_centered"].to_numpy(float),
                g["spy_return_5d"].to_numpy(float),
                g["spy_return_20d_ctx"].to_numpy(float),
                z_context.to_numpy(float),
                interaction.to_numpy(float),
            ]),
            ["breadth", "spy5", "spy20", "context_z", "breadth_x_context_z"],
        )
        rows.append({
            "context_id": context_id,
            "context_column": context_col,
            "days": int(len(g)),
            "eligible": True,
            "coef_breadth": fit["coef_breadth"],
            "t_breadth": fit["t_breadth"],
            "coef_context_z": fit["coef_context_z"],
            "t_context_z": fit["t_context_z"],
            "coef_breadth_x_context_z": fit["coef_breadth_x_context_z"],
            "t_breadth_x_context_z": fit["t_breadth_x_context_z"],
            "r2": fit["r2"],
        })

    return pd.DataFrame(rows)


def _episode_context(daily):
    rows = []
    for episode_id, g in daily.groupby("episode_id", sort=True):
        g = g.sort_values("timestamp_utc").copy()
        first = g.iloc[0]
        fit = None
        if len(g) >= MIN_EPISODE_DAYS:
            fit = _ols(
                g["full_confounder_residual_ic"].to_numpy(float),
                np.column_stack([
                    g["breadth_5d_centered"].to_numpy(float),
                    g["spy_return_5d"].to_numpy(float),
                    g["spy_return_20d_ctx"].to_numpy(float),
                ]),
                ["breadth", "spy5", "spy20"],
            )
        row = {
            "episode_id": episode_id,
            "start": g["timestamp_utc"].min().isoformat(),
            "end": g["timestamp_utc"].max().isoformat(),
            "days": int(len(g)),
            "eligible_episode": bool(len(g) >= MIN_EPISODE_DAYS),
            "breadth_coef_adjusted": fit["coef_breadth"] if fit else np.nan,
            "breadth_t_adjusted": fit["t_breadth"] if fit else np.nan,
            "first_day_breadth": float(first["breadth_5d_positive_fraction"]),
            "first_day_spy_return_5d": float(first["spy_return_5d"]),
            "first_day_spy_return_20d": float(first["spy_return_20d_ctx"]),
            "first_day_decline_depth_beyond_5pct": float(first["spy_decline_depth_beyond_5pct"]),
            "first_day_distance_from_20d_low": float(first["spy_distance_from_20d_low"]),
            "first_day_spy_volatility_20d": float(first["spy_volatility_20d"]),
        }
        rows.append(row)
    return pd.DataFrame(rows)


def _eligible_episode_correlations(episodes):
    g = episodes[episodes["eligible_episode"] == True].copy()
    rows = []
    context_cols = {
        "FIRST_DAY_BREADTH": "first_day_breadth",
        "FIRST_DAY_SPY_5D_RETURN": "first_day_spy_return_5d",
        "FIRST_DAY_DECLINE_DEPTH": "first_day_decline_depth_beyond_5pct",
        "FIRST_DAY_DISTANCE_FROM_20D_LOW": "first_day_distance_from_20d_low",
        "FIRST_DAY_SPY_VOLATILITY_20D": "first_day_spy_volatility_20d",
    }
    for context_id, col in context_cols.items():
        x = g[["breadth_coef_adjusted", col]].dropna()
        rows.append({
            "context_id": context_id,
            "eligible_episodes": int(len(x)),
            "pearson_with_episode_breadth_coef": float(x[col].corr(x["breadth_coef_adjusted"], method="pearson")) if len(x) >= 3 else np.nan,
            "spearman_with_episode_breadth_coef": float(x[col].corr(x["breadth_coef_adjusted"], method="spearman")) if len(x) >= 3 else np.nan,
        })
    return pd.DataFrame(rows)


def main():
    daily = _build_context_panel()
    interactions = _interaction_summary(daily)
    episodes = _episode_context(daily)
    eligible_context = _eligible_episode_correlations(episodes)

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    daily.to_csv(DAILY_PATH, index=False)
    interactions.to_csv(INTERACTION_PATH, index=False)
    episodes.to_csv(EPISODE_CONTEXT_PATH, index=False)
    eligible_context.to_csv(ELIGIBLE_EPISODE_PATH, index=False)

    eligible_interactions = interactions[interactions.get("eligible", False) == True].copy()
    positive_interactions = int((eligible_interactions["coef_breadth_x_context_z"] > 0).sum()) if len(eligible_interactions) else 0
    negative_interactions = int((eligible_interactions["coef_breadth_x_context_z"] < 0).sum()) if len(eligible_interactions) else 0

    manifest = {
        "research_version": "v7",
        "phase": PHASE,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "stage": "development_only_episode_context_heterogeneity_diagnostics",
        "objective": (
            "Explain Phase-8 episode-to-episode sign heterogeneity using a fixed set of "
            "continuous decision-time market context variables without optimizing a trading rule."
        ),
        "phase8_failure_preserved": True,
        "episode_definition_reused_from_phase8": True,
        "min_episode_days": MIN_EPISODE_DAYS,
        "context_specs": CONTEXT_SPECS,
        "context_threshold_optimization": False,
        "interaction_model_policy": (
            "one context at a time: residual_ic ~ breadth + SPY5 + SPY20 + z(context) + z(breadth)*z(context)"
        ),
        "episode_context_policy": "first qualifying session values only",
        "eligible_interaction_models": int(len(eligible_interactions)),
        "positive_interaction_count": positive_interactions,
        "negative_interaction_count": negative_interactions,
        "context_selected": None,
        "candidate_frozen": False,
        "portfolio_simulation": False,
        "future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "future_holdout_scored": False,
        "research_safety": {
            "v4_modified": False,
            "v5_modified": False,
            "v6_modified": False,
            "paper_portfolio_modified": False,
            "paper_journal_modified": False,
            "crypto_tracks_modified": False,
            "model_selection": False,
            "portfolio_simulation": False,
            "portfolio_policy_tuning": False,
            "threshold_optimization": False,
            "context_selected": False,
            "candidate_frozen": False,
            "future_holdout_scored": False,
            "brokerage_orders": False,
        },
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print("STOCK V7 PHASE 9")
    print("=" * 104)
    print("Fixed episode-context heterogeneity diagnostics")
    print("Phase-8 failure is preserved; no context threshold or trading rule is selected")
    print()
    print("===== CONTINUOUS INTERACTION SUMMARY =====")
    print(interactions.to_string(index=False))
    print()
    print("===== EPISODE FIRST-DAY CONTEXT =====")
    print(episodes.to_string(index=False))
    print()
    print("===== ELIGIBLE-EPISODE CONTEXT CORRELATIONS =====")
    print(eligible_context.to_string(index=False))
    print()
    print("No portfolio simulation. No context selection. No candidate freeze. No holdout score. No orders.")


if __name__ == "__main__":
    main()
''', encoding="utf-8")

    print("[APPLY] ml/v7/phase9.py")
    print()
    print("Stock V7 Phase 9 episode-context heterogeneity patch complete.")
    print("Fixed continuous context interactions + first-day episode diagnostics only.")
    print("Phase-8 failure remains recorded; the 2026-09-01+ holdout stays sealed.")


if __name__ == "__main__":
    main()
