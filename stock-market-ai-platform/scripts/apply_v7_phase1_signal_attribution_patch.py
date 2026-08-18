"""Apply isolated Stock V7 Phase 1 signal-attribution research track."""

from pathlib import Path

ROOT = Path("ml/v7")
INIT = ROOT / "__init__.py"
CONFIG = ROOT / "config.py"
PHASE1 = ROOT / "phase1.py"


def main():
    ROOT.mkdir(parents=True, exist_ok=True)

    INIT.write_text(
        '"""Stock V7 signal-attribution research track."""\n\nRESEARCH_VERSION = "v7"\n',
        encoding="utf-8",
    )
    print("[APPLY] ml/v7/__init__.py")

    CONFIG.write_text(
        '''"""Stock V7 research contract.\n\nV7 begins after V6 development-policy search was explicitly closed. V7 may use\nall information available before its own future holdout, but must not inspect or\nscore observations on or after that holdout boundary while designing/selecting\nmodels or portfolio policies.\n"""\n\nfrom pathlib import Path\nimport pandas as pd\n\nRESEARCH_VERSION = "v7"\nBENCHMARK_SYMBOL = "SPY"\nPRIMARY_HORIZON_DAYS = 5\nFUTURE_HOLDOUT_START_UTC = pd.Timestamp("2026-09-01", tz="UTC")\n\nSOURCE_PANEL = Path("data/model/v6/phase1/research_panel.parquet")\nV6_CONCENTRATION = Path("data/model/v6/phase6/concentration.csv")\nOUTPUT_ROOT = Path("data/model/v7/phase1")\nPANEL_PATH = OUTPUT_ROOT / "research_panel.parquet"\nFEATURE_IC_PATH = OUTPUT_ROOT / "feature_ic_summary.csv"\nSYMBOL_PROFILE_PATH = OUTPUT_ROOT / "symbol_profiles.csv"\nCONCENTRATED_NAME_PATH = OUTPUT_ROOT / "concentrated_name_diagnostics.csv"\nMANIFEST_PATH = OUTPUT_ROOT / "manifest.json"\n\nFEATURE_COLUMNS = (\n    "daily_return",\n    "return_2d",\n    "return_3d",\n    "return_5d",\n    "return_10d",\n    "return_20d",\n    "return_60d",\n    "price_vs_sma_7",\n    "price_vs_sma_20",\n    "price_vs_sma_50",\n    "price_vs_sma_200",\n    "sma_7_vs_sma_20",\n    "sma_20_vs_sma_50",\n    "sma_50_vs_sma_200",\n    "intraday_range",\n    "open_close_range",\n    "volume_ratio",\n    "volume_change_5d",\n    "volatility_5d",\n    "volatility_20d",\n    "volatility_ratio_5_20",\n    "trend_20_50",\n    "trend_50_200",\n    "distance_from_20d_high",\n    "distance_from_20d_low",\n    "rsi_centered",\n)\n''',
        encoding="utf-8",
    )
    print("[APPLY] ml/v7/config.py")

    PHASE1.write_text(
        r'''"""Stock V7 Phase 1: all-history signal attribution and persistence audit.

Purpose
-------
V6 showed economically useful development ranking behavior but repeated-name
concentration. V7 starts a new research track rather than continuing to tune V6.
Phase 1 asks *why* certain stocks/features are persistently attractive before any
V7 model is fit.

This phase:
* Uses the full 100-stock cross-sectional research panel available before V7's
  own future holdout.
* Reuses the already-audited V6 Phase 1 panel only as raw research input; V6
  models/policies are not changed.
* Computes daily cross-sectional Spearman IC for every registered feature versus
  the 5-session SPY-relative target.
* Builds per-symbol realized-target and feature-percentile profiles.
* If V6 Phase 6 concentration diagnostics exist, profiles the names that were
  most frequently selected by the fixed sector-cap-3 reference policy.
* Defines a new untouched future holdout beginning 2026-09-01.

No V7 model fitting, model selection, portfolio simulation, candidate freeze,
holdout scoring, paper-state mutation, or brokerage orders occur in Phase 1.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.v7.config import (
    CONCENTRATED_NAME_PATH,
    FEATURE_COLUMNS,
    FEATURE_IC_PATH,
    FUTURE_HOLDOUT_START_UTC,
    MANIFEST_PATH,
    OUTPUT_ROOT,
    PANEL_PATH,
    PRIMARY_HORIZON_DAYS,
    SOURCE_PANEL,
    SYMBOL_PROFILE_PATH,
    V6_CONCENTRATION,
)

TARGET = f"forward_relative_return_{PRIMARY_HORIZON_DAYS}d"
REFERENCE_POLICY = "sector_cap_3_reference"


def _load_panel() -> pd.DataFrame:
    if not SOURCE_PANEL.exists():
        raise FileNotFoundError(f"Missing audited V6 research panel: {SOURCE_PANEL}")

    panel = pd.read_parquet(SOURCE_PANEL).copy()
    panel["timestamp_utc"] = pd.to_datetime(panel["timestamp_utc"], utc=True)
    panel = panel[panel["timestamp_utc"] < FUTURE_HOLDOUT_START_UTC].copy()

    required = {"timestamp_utc", "symbol", "sector", TARGET, *FEATURE_COLUMNS}
    missing = sorted(required - set(panel.columns))
    if missing:
        raise ValueError("V7 source panel missing columns: " + ", ".join(missing))

    if panel.duplicated(["timestamp_utc", "symbol"]).any():
        raise RuntimeError("Duplicate timestamp/symbol rows in V7 source panel")

    counts = panel.groupby("timestamp_utc")["symbol"].nunique()
    if counts.min() != 100 or counts.max() != 100:
        raise RuntimeError("V7 requires exactly 100 candidates on every research date")

    return panel.sort_values(["timestamp_utc", "symbol"]).reset_index(drop=True)


def _daily_spearman(frame: pd.DataFrame, feature: str) -> pd.DataFrame:
    rows = []
    for ts, day in frame.groupby("timestamp_utc", sort=True):
        x = day[[feature, TARGET]].replace([np.inf, -np.inf], np.nan).dropna()
        if len(x) < 20 or x[feature].nunique() < 2 or x[TARGET].nunique() < 2:
            continue
        ic = x[feature].rank(method="average").corr(
            x[TARGET].rank(method="average"), method="pearson"
        )
        rows.append({"timestamp_utc": ts, "feature": feature, "ic": float(ic)})
    return pd.DataFrame(rows)


def _feature_ic_summary(panel: pd.DataFrame) -> pd.DataFrame:
    all_rows = []
    for feature in FEATURE_COLUMNS:
        daily = _daily_spearman(panel, feature)
        if daily.empty:
            all_rows.append({
                "feature": feature,
                "days": 0,
                "mean_ic": np.nan,
                "median_ic": np.nan,
                "ic_hit_rate": np.nan,
                "mean_abs_ic": np.nan,
            })
            continue
        all_rows.append({
            "feature": feature,
            "days": int(len(daily)),
            "mean_ic": float(daily["ic"].mean()),
            "median_ic": float(daily["ic"].median()),
            "ic_hit_rate": float((daily["ic"] > 0).mean()),
            "mean_abs_ic": float(daily["ic"].abs().mean()),
        })
    out = pd.DataFrame(all_rows)
    out["abs_mean_ic"] = out["mean_ic"].abs()
    return out.sort_values(["abs_mean_ic", "mean_abs_ic"], ascending=False).reset_index(drop=True)


def _with_daily_feature_percentiles(panel: pd.DataFrame) -> pd.DataFrame:
    out = panel.copy()
    for feature in FEATURE_COLUMNS:
        out[f"pct__{feature}"] = out.groupby("timestamp_utc")[feature].rank(
            method="average", pct=True
        )
    return out


def _symbol_profiles(panel_pct: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for symbol, group in panel_pct.groupby("symbol", sort=True):
        target = group[TARGET].replace([np.inf, -np.inf], np.nan).dropna()
        row = {
            "symbol": symbol,
            "sector": group["sector"].iloc[0],
            "observations": int(len(group)),
            "labeled_observations": int(len(target)),
            "mean_relative_target": float(target.mean()) if len(target) else np.nan,
            "median_relative_target": float(target.median()) if len(target) else np.nan,
            "positive_relative_target_fraction": float((target > 0).mean()) if len(target) else np.nan,
        }
        for feature in FEATURE_COLUMNS:
            s = group[f"pct__{feature}"].dropna()
            row[f"mean_pct__{feature}"] = float(s.mean()) if len(s) else np.nan
        rows.append(row)
    return pd.DataFrame(rows).sort_values("mean_relative_target", ascending=False).reset_index(drop=True)


def _concentrated_names() -> list[str]:
    if not V6_CONCENTRATION.exists():
        return []
    c = pd.read_csv(V6_CONCENTRATION)
    required = {"policy_id", "dimension", "key", "selection_period_fraction"}
    if not required.issubset(c.columns):
        return []
    x = c[
        (c["policy_id"] == REFERENCE_POLICY)
        & (c["dimension"] == "symbol")
    ].copy()
    x = x.sort_values("selection_period_fraction", ascending=False).head(10)
    return x["key"].astype(str).tolist()


def _concentrated_name_diagnostics(panel_pct: pd.DataFrame, profiles: pd.DataFrame) -> pd.DataFrame:
    names = _concentrated_names()
    if not names:
        return pd.DataFrame(columns=["symbol", "reason"])

    universe_feature_means = {
        feature: float(panel_pct[f"pct__{feature}"].mean())
        for feature in FEATURE_COLUMNS
    }
    rows = []
    p = profiles.set_index("symbol")
    for symbol in names:
        if symbol not in p.index:
            continue
        group = panel_pct[panel_pct["symbol"] == symbol]
        row = {
            "symbol": symbol,
            "sector": p.loc[symbol, "sector"],
            "mean_relative_target": float(p.loc[symbol, "mean_relative_target"]),
            "positive_relative_target_fraction": float(
                p.loc[symbol, "positive_relative_target_fraction"]
            ),
        }
        deviations = []
        for feature in FEATURE_COLUMNS:
            mean_pct = float(group[f"pct__{feature}"].mean())
            deviation = mean_pct - universe_feature_means[feature]
            deviations.append((feature, deviation, mean_pct))
        deviations.sort(key=lambda x: abs(x[1]), reverse=True)
        for i, (feature, deviation, mean_pct) in enumerate(deviations[:8], start=1):
            row[f"driver_{i}"] = feature
            row[f"driver_{i}_mean_percentile"] = mean_pct
            row[f"driver_{i}_deviation"] = deviation
        rows.append(row)
    return pd.DataFrame(rows)


def main():
    panel = _load_panel()

    # Retain all pre-holdout rows. Unlabeled final rows are useful as feature
    # observations but are never used in target-based diagnostics.
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(PANEL_PATH, index=False)

    feature_ic = _feature_ic_summary(panel)
    feature_ic.to_csv(FEATURE_IC_PATH, index=False)

    panel_pct = _with_daily_feature_percentiles(panel)
    profiles = _symbol_profiles(panel_pct)
    profiles.to_csv(SYMBOL_PROFILE_PATH, index=False)

    concentrated = _concentrated_name_diagnostics(panel_pct, profiles)
    concentrated.to_csv(CONCENTRATED_NAME_PATH, index=False)

    labeled = panel[panel[TARGET].notna()].copy()
    fully_featured = panel[list(FEATURE_COLUMNS)].notna().all(axis=1)
    complete_dates = (
        panel.assign(_complete=fully_featured)
        .groupby("timestamp_utc")["_complete"]
        .sum()
    )
    complete_dates = complete_dates[complete_dates.eq(100)]

    manifest = {
        "research_version": "v7",
        "phase": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "stage": "all_history_signal_attribution_and_persistence_audit",
        "objective": "Explain persistent cross-sectional stock attractiveness before fitting any V7 model.",
        "candidate_count": 100,
        "benchmark_symbol": "SPY",
        "benchmark_is_investable_candidate": False,
        "primary_target": TARGET,
        "feature_count": len(FEATURE_COLUMNS),
        "panel_rows": int(len(panel)),
        "shared_dates": int(panel["timestamp_utc"].nunique()),
        "labeled_rows": int(len(labeled)),
        "date_range": {
            "start": panel["timestamp_utc"].min().isoformat(),
            "end": panel["timestamp_utc"].max().isoformat(),
        },
        "fully_feature_complete_100_stock_dates": int(len(complete_dates)),
        "future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "future_holdout_scored": False,
        "v6_development_search_closed": True,
        "v6_outputs_used_only_for_motivation_and_concentration_name_identification": True,
        "concentrated_reference_names": _concentrated_names(),
        "top_feature_ic": feature_ic.head(10).to_dict(orient="records"),
        "outputs": {
            "panel": str(PANEL_PATH),
            "feature_ic_summary": str(FEATURE_IC_PATH),
            "symbol_profiles": str(SYMBOL_PROFILE_PATH),
            "concentrated_name_diagnostics": str(CONCENTRATED_NAME_PATH),
        },
        "research_safety": {
            "v4_modified": False,
            "v5_modified": False,
            "v6_modified": False,
            "paper_portfolio_modified": False,
            "paper_journal_modified": False,
            "crypto_tracks_modified": False,
            "model_fitting": False,
            "model_selection": False,
            "portfolio_simulation": False,
            "threshold_tuning": False,
            "candidate_frozen": False,
            "future_holdout_scored": False,
            "brokerage_orders": False,
        },
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print("STOCK V7 PHASE 1")
    print("=" * 100)
    print("Objective: explain persistent signal before fitting V7 models")
    print(f"Candidates: {manifest['candidate_count']} + SPY benchmark context")
    print(f"Panel rows: {manifest['panel_rows']:,}")
    print(f"Shared dates: {manifest['shared_dates']:,}")
    print(f"Date range: {manifest['date_range']['start']} -> {manifest['date_range']['end']}")
    print(f"Labeled rows: {manifest['labeled_rows']:,}")
    print(f"Future holdout begins: {manifest['future_holdout_start_utc']}")
    print("Future holdout scored: False")
    print()
    print("===== TOP FEATURE CROSS-SECTIONAL IC =====")
    print(feature_ic.head(15).to_string(index=False))
    print()
    print("===== V6 CONCENTRATED-NAME DIAGNOSTICS =====")
    if concentrated.empty:
        print("No V6 concentration file available; Phase 1 continued without name-specific diagnostics.")
    else:
        cols = [
            "symbol",
            "sector",
            "mean_relative_target",
            "positive_relative_target_fraction",
            "driver_1",
            "driver_1_mean_percentile",
            "driver_2",
            "driver_2_mean_percentile",
            "driver_3",
            "driver_3_mean_percentile",
        ]
        print(concentrated[cols].to_string(index=False))
    print()
    print("No V7 model fit. No portfolio simulation. No holdout score. No brokerage orders.")


if __name__ == "__main__":
    main()
''',
        encoding="utf-8",
    )
    print("[APPLY] ml/v7/phase1.py")
    print()
    print("Stock V7 Phase 1 signal-attribution patch complete.")
    print("New future holdout begins 2026-09-01; all currently available pre-holdout data may be used for V7 development.")
    print("Phase 1 performs attribution/persistence diagnostics only: no model fit, portfolio simulation, freeze, or orders.")


if __name__ == "__main__":
    main()
