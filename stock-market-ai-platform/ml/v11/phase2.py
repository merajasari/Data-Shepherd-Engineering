"""V11 Phase 2: development-only gap and liquidity signal diagnostics.

Evaluates only the six signals frozen in the Phase-2 registry. Every signal is
residualized cross-sectionally against all frozen V8/V9 controls and all six
closed Phase-1 signals. No signal is selected and no portfolio is simulated.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.v11 import phase1
from ml.v11.phase2_registry import (
    DISCOVERY_RULES,
    FUTURE_HOLDOUT_START_UTC,
    ORTHOGONALIZATION_CONTROLS,
    REGISTRY_PATH,
    RESEARCH_VERSION,
    SIGNALS,
    build_registry,
)

PHASE = 2
OUTPUT_ROOT = Path("data/model/v11/phase2/diagnostics")
PANEL_PATH = OUTPUT_ROOT / "signal_panel.parquet"
DAILY_IC_PATH = OUTPUT_ROOT / "daily_orthogonal_ic.parquet"
SUMMARY_PATH = OUTPUT_ROOT / "signal_summary.csv"
YEAR_PATH = OUTPUT_ROOT / "year_stability.csv"
REGIME_PATH = OUTPUT_ROOT / "regime_stability.csv"
MULTIPLE_TESTING_PATH = OUTPUT_ROOT / "multiple_testing_results.csv"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"

SIGNAL_IDS = tuple(signal["signal_id"] for signal in SIGNALS)
MIN_ASSETS = int(DISCOVERY_RULES["minimum_cross_sectional_assets"])
MINIMUM_MEAN_IC = float(DISCOVERY_RULES["minimum_mean_orthogonal_ic"])
MINIMUM_POSITIVE_YEAR_RATE = float(
    DISCOVERY_RULES["minimum_positive_year_rate"]
)
MINIMUM_REGIME_MEAN_IC = float(
    DISCOVERY_RULES["minimum_regime_mean_ic"]
)


def _verify_contract():
    expected = build_registry()
    if not REGISTRY_PATH.exists():
        raise FileNotFoundError(
            f"Missing frozen V11 Phase-2 registry: {REGISTRY_PATH}"
        )
    actual = json.loads(REGISTRY_PATH.read_text())
    if actual != expected:
        raise RuntimeError("V11 Phase-2 registry differs from frozen contract")
    return actual


def _add_phase2_base_signals(frame):
    output = frame.copy()
    previous_close = output["close"].shift(1)
    overnight_gap = output["open"] / previous_close - 1.0
    intraday_return = output["close"] / output["open"] - 1.0
    dollar_volume = output["close"] * output["volume"]

    output["overnight_gap_reversal_1"] = -overnight_gap
    output["overnight_gap_continuation_5"] = overnight_gap.rolling(
        5, min_periods=5
    ).mean()
    output["intraday_pressure_5"] = intraday_return.rolling(
        5, min_periods=5
    ).mean()

    dollar_volume_5 = dollar_volume.rolling(5, min_periods=5).mean()
    dollar_volume_60 = dollar_volume.rolling(60, min_periods=60).mean()
    ratio = dollar_volume_5 / dollar_volume_60.replace(0, np.nan)
    output["abnormal_dollar_volume_5_60"] = np.log(
        ratio.where(ratio > 0)
    )

    impact = (
        output["return_1d"].abs()
        / dollar_volume.replace(0, np.nan)
    )
    impact_5 = impact.rolling(5, min_periods=5).mean()
    impact_20 = impact.rolling(20, min_periods=20).mean()
    output["amihud_liquidity_improvement_5_20"] = -1.0 * (
        impact_5 / impact_20.replace(0, np.nan) - 1.0
    )

    signed_dollar_volume = np.sign(intraday_return) * dollar_volume
    output["signed_dollar_volume_pressure_20"] = (
        signed_dollar_volume.rolling(20, min_periods=20).sum()
        / dollar_volume.rolling(20, min_periods=20).sum().replace(0, np.nan)
    )
    return output


def build_panel():
    files = phase1._feature_files()
    base = {
        symbol: _add_phase2_base_signals(
            phase1._base_frame(path, symbol)
        )
        for symbol, path in files.items()
    }
    spy = base["SPY"]
    frames = [
        phase1._symbol_panel(frame, spy)
        for symbol, frame in base.items()
        if symbol != "SPY"
    ]
    panel = pd.concat(frames, ignore_index=True)
    panel = panel[
        panel["timestamp_utc"] < FUTURE_HOLDOUT_START_UTC
    ].copy()
    if panel.empty:
        raise RuntimeError("V11 Phase-2 development panel is empty")
    if panel["timestamp_utc"].max() >= FUTURE_HOLDOUT_START_UTC:
        raise RuntimeError("V11 Phase-2 panel reaches the future holdout")
    missing = sorted(
        (set(SIGNAL_IDS) | set(ORTHOGONALIZATION_CONTROLS))
        - set(panel.columns)
    )
    if missing:
        raise RuntimeError(f"V11 Phase-2 panel is missing columns: {missing}")
    return panel


def build_daily_ic(panel):
    rows = []
    control_columns = list(ORTHOGONALIZATION_CONTROLS)
    for timestamp, day in panel.groupby("timestamp_utc", sort=True):
        controls = day[control_columns]
        target = day["forward_relative_return_5d"]
        for signal_id in SIGNAL_IDS:
            residual = phase1._residualize(day[signal_id], controls)
            valid = pd.DataFrame(
                {"signal": residual, "target": target}
            ).replace([np.inf, -np.inf], np.nan).dropna()
            ic = (
                float(
                    valid["signal"].corr(
                        valid["target"],
                        method="spearman",
                    )
                )
                if len(valid) >= MIN_ASSETS
                and valid["signal"].nunique() > 1
                and valid["target"].nunique() > 1
                else np.nan
            )
            rows.append(
                {
                    "timestamp_utc": timestamp,
                    "signal_id": signal_id,
                    "asset_count": int(len(valid)),
                    "orthogonal_ic": ic,
                }
            )
    return pd.DataFrame(rows)


def build_year_stability(daily):
    return phase1.build_year_stability(daily)


def build_regime_stability(daily, panel):
    regime = (
        panel[
            [
                "timestamp_utc",
                "spy_close",
                "spy_volatility_20d",
            ]
        ]
        .drop_duplicates("timestamp_utc")
        .sort_values("timestamp_utc")
        .reset_index(drop=True)
    )
    regime["spy_sma200"] = regime["spy_close"].rolling(
        200, min_periods=200
    ).mean()
    known_trend = regime["spy_sma200"].notna()
    regime["trend_regime"] = np.select(
        [
            known_trend & (regime["spy_close"] >= regime["spy_sma200"]),
            known_trend & (regime["spy_close"] < regime["spy_sma200"]),
        ],
        ["SPY_ABOVE_SMA200", "SPY_BELOW_SMA200"],
        default=None,
    )
    median_volatility = float(regime["spy_volatility_20d"].median())
    regime["volatility_regime"] = np.where(
        regime["spy_volatility_20d"] >= median_volatility,
        "HIGH_SPY_VOLATILITY",
        "LOW_SPY_VOLATILITY",
    )
    merged = daily.merge(regime, on="timestamp_utc", how="left")
    rows = []
    for column in ("trend_regime", "volatility_regime"):
        valid_regime = merged.dropna(subset=[column])
        for (signal_id, label), group in valid_regime.groupby(
            ["signal_id", column],
            sort=True,
        ):
            values = group["orthogonal_ic"].dropna()
            rows.append(
                {
                    "signal_id": signal_id,
                    "regime_type": column,
                    "regime": label,
                    "days": int(len(values)),
                    "mean_orthogonal_ic": (
                        float(values.mean()) if len(values) else np.nan
                    ),
                    "median_orthogonal_ic": (
                        float(values.median()) if len(values) else np.nan
                    ),
                    "ic_hit_rate": (
                        float((values > 0).mean()) if len(values) else np.nan
                    ),
                }
            )
    return pd.DataFrame(rows)


def build_summary(daily, years, regimes):
    summary = phase1.build_summary(daily).drop(
        columns=["passes_discovery_threshold"]
    )
    summary["fdr_pass"] = summary["fdr_q_value"] <= 0.05
    summary["mean_ic_pass"] = (
        summary["mean_orthogonal_ic"] >= MINIMUM_MEAN_IC
    )

    positive_year_rate = (
        years.assign(
            positive=years["mean_orthogonal_ic"] > 0
        )
        .groupby("signal_id", observed=True)["positive"]
        .mean()
    )
    minimum_regime_ic = regimes.groupby(
        "signal_id", observed=True
    )["mean_orthogonal_ic"].min()

    summary["positive_year_rate"] = summary["signal_id"].map(
        positive_year_rate
    )
    summary["positive_year_rate_pass"] = (
        summary["positive_year_rate"] >= MINIMUM_POSITIVE_YEAR_RATE
    )
    summary["minimum_regime_mean_ic"] = summary["signal_id"].map(
        minimum_regime_ic
    )
    summary["regime_stability_pass"] = (
        summary["minimum_regime_mean_ic"] >= MINIMUM_REGIME_MEAN_IC
    )
    summary["passes_discovery_threshold"] = summary[
        [
            "fdr_pass",
            "mean_ic_pass",
            "positive_year_rate_pass",
            "regime_stability_pass",
        ]
    ].all(axis=1)
    return summary.sort_values(
        ["passes_discovery_threshold", "mean_orthogonal_ic"],
        ascending=[False, False],
    ).reset_index(drop=True)


def main():
    contract = _verify_contract()
    panel = build_panel()
    daily = build_daily_ic(panel)
    years = build_year_stability(daily)
    regimes = build_regime_stability(daily, panel)
    summary = build_summary(daily, years, regimes)

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(PANEL_PATH, index=False)
    daily.to_parquet(DAILY_IC_PATH, index=False)
    summary.to_csv(SUMMARY_PATH, index=False)
    years.to_csv(YEAR_PATH, index=False)
    regimes.to_csv(REGIME_PATH, index=False)
    summary[
        [
            "signal_id",
            "raw_p_value",
            "fdr_q_value",
            "fdr_pass",
            "mean_ic_pass",
            "positive_year_rate_pass",
            "regime_stability_pass",
            "passes_discovery_threshold",
        ]
    ].to_csv(MULTIPLE_TESTING_PATH, index=False)

    passing = summary[summary["passes_discovery_threshold"]]
    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": PHASE,
        "stage": "development_only_gap_liquidity_signal_diagnostics",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "phase2_contract_sha256": contract["contract_sha256"],
        "signal_count": len(SIGNAL_IDS),
        "orthogonalization_control_count": len(
            ORTHOGONALIZATION_CONTROLS
        ),
        "panel_rows": int(len(panel)),
        "candidate_count": int(panel["symbol"].nunique()),
        "date_start_utc": panel["timestamp_utc"].min().isoformat(),
        "date_end_utc": panel["timestamp_utc"].max().isoformat(),
        "signals_passing_all_gates": passing["signal_id"].tolist(),
        "passing_signal_count": int(len(passing)),
        "signal_selected": False,
        "future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "future_holdout_scored": False,
        "model_fitted": False,
        "portfolio_simulated": False,
        "candidate_frozen": False,
        "candidate_promoted": False,
        "v8_modified": False,
        "v8_holdout_scored": False,
        "v9_results_modified": False,
        "production_modified": False,
        "brokerage_orders": False,
    }
    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )

    print("STOCK V11 PHASE 2: GAP AND LIQUIDITY SIGNAL DIAGNOSTICS")
    print("=" * 104)
    print(
        f"Panel: {manifest['panel_rows']:,} rows | "
        f"{manifest['candidate_count']} stocks"
    )
    print(
        f"Dates: {manifest['date_start_utc']} -> "
        f"{manifest['date_end_utc']}"
    )
    print(summary.to_string(index=False))
    print(
        "Signals passing every preregistered gate: "
        + (
            ", ".join(manifest["signals_passing_all_gates"])
            if manifest["passing_signal_count"]
            else "NONE"
        )
    )
    print(
        "No signal selection, fitting, portfolio simulation, holdout scoring, "
        "production mutation, or brokerage orders."
    )


if __name__ == "__main__":
    main()
