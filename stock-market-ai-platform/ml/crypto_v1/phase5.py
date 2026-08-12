"""Crypto V1 Phase 5: read-only regime and attribution diagnostics.

This phase consumes frozen Phase 3 predictions, the frozen 7-day research
panel, and generated Phase 4 portfolio outputs. It performs no fitting,
retraining, retuning, strategy selection, promotion, live execution,
leverage, or derivatives.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.crypto_v1.config import MODEL_ROOT


PHASE3_ROOT = MODEL_ROOT / "phase3"
PHASE4_ROOT = MODEL_ROOT / "phase4"
PHASE5_ROOT = MODEL_ROOT / "phase5"

PRIMARY_HORIZON_DAYS = 7
PRIMARY_MODEL_ID = "momentum"
CONTROL_MODEL_IDS = ("hist_gradient_boosting", "random", "equal_score")
MODEL_IDS = (PRIMARY_MODEL_ID,) + CONTROL_MODEL_IDS
TOP_COUNTS = (3, 5)

REGIME_COLUMNS = [
    "split", "model_id", "strategy_id", "variant", "top_n",
    "cost_bps_round_trip", "btc_regime", "observation_count",
    "mean_net_return", "median_net_return", "positive_period_rate",
    "cumulative_return", "annualized_volatility", "worst_period_return",
    "best_period_return", "mean_turnover", "mean_gross_exposure",
]
RELATIVE_COLUMNS = [
    "split", "model_id", "strategy_id", "variant", "top_n",
    "cost_bps_round_trip", "observation_count",
    "strategy_cumulative_return", "btc_cumulative_return",
    "excess_cumulative_return_vs_btc", "mean_daily_excess_return_vs_btc",
    "excess_positive_period_rate", "tracking_error_annualized",
    "information_ratio_like", "up_capture_mean", "down_capture_mean",
]
DRAWDOWN_COLUMNS = [
    "split", "model_id", "strategy_id", "variant", "top_n",
    "cost_bps_round_trip", "episode_rank", "peak_timestamp_utc",
    "trough_timestamp_utc", "recovery_timestamp_utc", "drawdown",
    "days_peak_to_trough", "days_to_recovery",
]
ATTRIBUTION_COLUMNS = [
    "split", "model_id", "variant", "top_n", "product_id",
    "selection_count", "available_day_count", "selection_rate",
    "mean_btc_relative_forward_return", "median_btc_relative_forward_return",
    "positive_relative_return_rate", "sum_btc_relative_forward_return",
]
SPREAD_COLUMNS = [
    "split", "model_id", "top_n", "btc_regime", "day_count",
    "mean_top_relative_return", "mean_bottom_relative_return",
    "mean_top_minus_bottom_spread", "median_top_minus_bottom_spread",
    "positive_spread_rate",
]


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_columns(frame, required, label):
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise ValueError(f"{label} missing columns: " + ", ".join(missing))


def load_inputs(
    phase3_root=PHASE3_ROOT,
    phase4_root=PHASE4_ROOT,
    model_root=MODEL_ROOT,
):
    """Load immutable Phase 3/4 research artifacts."""
    phase3_root = Path(phase3_root)
    phase4_root = Path(phase4_root)
    model_root = Path(model_root)

    paths = {
        "phase3_predictions": phase3_root / "predictions.parquet",
        "phase3_manifest": phase3_root / "manifest.json",
        "research_panel_7d": model_root / "research_panel_7d.parquet",
        "phase4_manifest": phase4_root / "manifest.json",
        "phase4_portfolio_daily": phase4_root / "portfolio_daily.csv",
        "phase4_portfolio_metrics": phase4_root / "portfolio_metrics.csv",
    }

    missing = [str(path) for path in paths.values() if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing Phase 5 input(s): " + ", ".join(missing))

    predictions = pd.read_parquet(paths["phase3_predictions"])
    panel = pd.read_parquet(paths["research_panel_7d"])
    daily = pd.read_csv(paths["phase4_portfolio_daily"])
    metrics = pd.read_csv(paths["phase4_portfolio_metrics"])

    predictions["timestamp_utc"] = pd.to_datetime(
        predictions["timestamp_utc"], utc=True
    )
    panel["timestamp_utc"] = pd.to_datetime(panel["timestamp_utc"], utc=True)
    daily["timestamp_utc"] = pd.to_datetime(daily["timestamp_utc"], utc=True)

    _require_columns(
        predictions,
        {
            "timestamp_utc", "product_id",
            "actual_btc_relative_forward_return", "predicted_score",
            "fold_id", "split", "model_id", "horizon_days", "btc_regime",
        },
        "Phase 3 predictions",
    )
    _require_columns(
        panel,
        {"timestamp_utc", "product_id", "return_1d"},
        "7-day research panel",
    )
    _require_columns(
        daily,
        {
            "timestamp_utc", "split", "model_id", "strategy_id", "variant",
            "top_n", "cost_bps_round_trip", "is_rebalance", "turnover",
            "transaction_cost", "gross_return", "net_return",
            "gross_exposure", "net_exposure", "cash_weight", "equity",
        },
        "Phase 4 portfolio_daily",
    )
    _require_columns(
        metrics,
        {
            "split", "model_id", "strategy_id", "variant", "top_n",
            "cost_bps_round_trip", "ending_equity", "cumulative_return",
            "maximum_drawdown", "total_turnover", "number_of_rebalances",
        },
        "Phase 4 portfolio_metrics",
    )

    predictions = predictions[
        (predictions["horizon_days"] == PRIMARY_HORIZON_DAYS)
        & predictions["model_id"].isin(MODEL_IDS)
    ].copy()

    if predictions.empty:
        raise ValueError("No frozen 7-day Phase 3 candidate/control predictions found")

    return paths, predictions, panel, daily, metrics


def _daily_regime_map(predictions):
    """Return one frozen Phase 3 BTC regime per split/date."""
    frame = predictions[
        predictions["model_id"] == PRIMARY_MODEL_ID
    ][["split", "timestamp_utc", "btc_regime"]].drop_duplicates()

    counts = frame.groupby(
        ["split", "timestamp_utc"], sort=True
    )["btc_regime"].nunique(dropna=False)

    if (counts > 1).any():
        raise ValueError("Multiple Phase 3 BTC regimes found for one split/date")

    return frame.drop_duplicates(["split", "timestamp_utc"])


def regime_performance(daily, predictions):
    """Summarize realized Phase 4 performance by frozen BTC regime."""
    regimes = _daily_regime_map(predictions)
    frame = daily.merge(
        regimes,
        on=["split", "timestamp_utc"],
        how="left",
        validate="many_to_one",
    )
    frame["btc_regime"] = frame["btc_regime"].fillna("unknown")

    rows = []
    keys = [
        "split", "model_id", "strategy_id", "variant", "top_n",
        "cost_bps_round_trip", "btc_regime",
    ]

    for values, group in frame.groupby(keys, sort=True, dropna=False):
        values = values if isinstance(values, tuple) else (values,)
        net = pd.to_numeric(group["net_return"], errors="coerce").dropna()
        turnover = pd.to_numeric(
            group["turnover"], errors="coerce"
        ).fillna(0.0)
        exposure = pd.to_numeric(
            group["gross_exposure"], errors="coerce"
        ).dropna()

        rows.append(dict(zip(keys, values)) | {
            "observation_count": len(net),
            "mean_net_return": net.mean() if len(net) else np.nan,
            "median_net_return": net.median() if len(net) else np.nan,
            "positive_period_rate": net.gt(0).mean() if len(net) else np.nan,
            "cumulative_return": (
                float(np.prod(1.0 + net) - 1.0) if len(net) else np.nan
            ),
            "annualized_volatility": (
                float(net.std(ddof=1) * np.sqrt(365.0))
                if len(net) > 1 else np.nan
            ),
            "worst_period_return": net.min() if len(net) else np.nan,
            "best_period_return": net.max() if len(net) else np.nan,
            "mean_turnover": turnover.mean() if len(turnover) else np.nan,
            "mean_gross_exposure": exposure.mean() if len(exposure) else np.nan,
        })

    return pd.DataFrame(rows, columns=REGIME_COLUMNS)


def _btc_return_series(panel):
    btc = panel[
        panel["product_id"] == "BTC-USD"
    ][["timestamp_utc", "return_1d"]].copy()
    btc["return_1d"] = pd.to_numeric(btc["return_1d"], errors="coerce")
    return btc.drop_duplicates("timestamp_utc").rename(
        columns={"return_1d": "btc_return"}
    )


def relative_performance(daily, panel):
    """Compare realized Phase 4 paths with contemporaneous BTC returns."""
    frame = daily.merge(
        _btc_return_series(panel),
        on="timestamp_utc",
        how="left",
        validate="many_to_one",
    )

    rows = []
    keys = [
        "split", "model_id", "strategy_id", "variant", "top_n",
        "cost_bps_round_trip",
    ]

    for values, group in frame.groupby(keys, sort=True, dropna=False):
        values = values if isinstance(values, tuple) else (values,)
        pair = group[["net_return", "btc_return"]].apply(
            pd.to_numeric, errors="coerce"
        ).dropna()

        if pair.empty:
            row = dict(zip(keys, values))
            for column in RELATIVE_COLUMNS:
                if column not in row:
                    row[column] = 0 if column == "observation_count" else np.nan
            rows.append(row)
            continue

        strategy = pair["net_return"]
        btc = pair["btc_return"]
        excess = strategy - btc
        strategy_cumulative = float(np.prod(1.0 + strategy) - 1.0)
        btc_cumulative = float(np.prod(1.0 + btc) - 1.0)
        excess_std = excess.std(ddof=1)
        tracking = (
            float(excess_std * np.sqrt(365.0))
            if len(excess) > 1 else np.nan
        )
        information = (
            float(excess.mean() / excess_std * np.sqrt(365.0))
            if len(excess) > 1 and excess_std > 0 else np.nan
        )

        up = pair[btc > 0]
        down = pair[btc < 0]

        rows.append(dict(zip(keys, values)) | {
            "observation_count": len(pair),
            "strategy_cumulative_return": strategy_cumulative,
            "btc_cumulative_return": btc_cumulative,
            "excess_cumulative_return_vs_btc": (
                strategy_cumulative - btc_cumulative
            ),
            "mean_daily_excess_return_vs_btc": excess.mean(),
            "excess_positive_period_rate": excess.gt(0).mean(),
            "tracking_error_annualized": tracking,
            "information_ratio_like": information,
            "up_capture_mean": (
                up["net_return"].mean() / up["btc_return"].mean()
                if len(up) and up["btc_return"].mean() != 0 else np.nan
            ),
            "down_capture_mean": (
                down["net_return"].mean() / down["btc_return"].mean()
                if len(down) and down["btc_return"].mean() != 0 else np.nan
            ),
        })

    return pd.DataFrame(rows, columns=RELATIVE_COLUMNS)


def drawdown_episodes(daily, max_episodes=5):
    """Return deepest drawdown episodes for each frozen Phase 4 path."""
    rows = []
    keys = [
        "split", "model_id", "strategy_id", "variant", "top_n",
        "cost_bps_round_trip",
    ]

    for values, group in daily.groupby(keys, sort=True, dropna=False):
        values = values if isinstance(values, tuple) else (values,)
        group = group.sort_values("timestamp_utc").reset_index(drop=True)
        equity = pd.to_numeric(group["equity"], errors="coerce")

        if equity.isna().all():
            continue

        running_peak = equity.cummax()
        drawdown = equity / running_peak - 1.0

        episodes = []
        active = False
        peak_index = None

        for i, dd in enumerate(drawdown):
            if dd < -1e-15 and not active:
                active = True
                peak_index = max(0, i - 1)

            is_last = i == len(drawdown) - 1
            recovered = dd >= -1e-15

            if active and (recovered or is_last):
                end_index = i
                segment = drawdown.iloc[peak_index:end_index + 1]
                trough_index = int(segment.idxmin())

                peak_ts = group.loc[peak_index, "timestamp_utc"]
                trough_ts = group.loc[trough_index, "timestamp_utc"]
                recovery_ts = (
                    group.loc[end_index, "timestamp_utc"]
                    if drawdown.iloc[end_index] >= -1e-15
                    else pd.NaT
                )

                episodes.append({
                    "peak_timestamp_utc": peak_ts,
                    "trough_timestamp_utc": trough_ts,
                    "recovery_timestamp_utc": recovery_ts,
                    "drawdown": float(drawdown.iloc[trough_index]),
                    "days_peak_to_trough": int((trough_ts - peak_ts).days),
                    "days_to_recovery": (
                        int((recovery_ts - peak_ts).days)
                        if pd.notna(recovery_ts) else np.nan
                    ),
                })

                active = False
                peak_index = None

        episodes = sorted(
            episodes, key=lambda item: item["drawdown"]
        )[:max_episodes]

        for rank, episode in enumerate(episodes, start=1):
            rows.append(
                dict(zip(keys, values))
                | {"episode_rank": rank}
                | episode
            )

    return pd.DataFrame(rows, columns=DRAWDOWN_COLUMNS)


def _ranked_predictions(predictions):
    keys = [
        "horizon_days", "model_id", "fold_id", "split", "timestamp_utc"
    ]
    ranked = predictions.sort_values(
        keys + ["predicted_score", "product_id"],
        ascending=[True, True, True, True, True, False, True],
    ).copy()
    ranked["selection_rank"] = ranked.groupby(
        keys, sort=False
    ).cumcount() + 1
    return ranked


def asset_attribution(predictions):
    """Describe which assets drive frozen Top-N BTC-relative outcomes."""
    ranked = _ranked_predictions(predictions)
    rows = []

    for values, group in ranked.groupby(
        ["split", "model_id"], sort=True, dropna=False
    ):
        split, model_id = values
        available_days = group.groupby(
            "product_id"
        )["timestamp_utc"].nunique()

        for top_n in TOP_COUNTS:
            selected = group[group["selection_rank"] <= top_n]

            for product_id, asset in selected.groupby(
                "product_id", sort=True
            ):
                actual = pd.to_numeric(
                    asset["actual_btc_relative_forward_return"],
                    errors="coerce",
                ).dropna()
                denominator = int(available_days.get(product_id, 0))

                rows.append({
                    "split": split,
                    "model_id": model_id,
                    "variant": f"top_{top_n}_equal_weight",
                    "top_n": top_n,
                    "product_id": product_id,
                    "selection_count": len(asset),
                    "available_day_count": denominator,
                    "selection_rate": (
                        len(asset) / denominator if denominator else np.nan
                    ),
                    "mean_btc_relative_forward_return": (
                        actual.mean() if len(actual) else np.nan
                    ),
                    "median_btc_relative_forward_return": (
                        actual.median() if len(actual) else np.nan
                    ),
                    "positive_relative_return_rate": (
                        actual.gt(0).mean() if len(actual) else np.nan
                    ),
                    "sum_btc_relative_forward_return": (
                        actual.sum() if len(actual) else np.nan
                    ),
                })

    return pd.DataFrame(rows, columns=ATTRIBUTION_COLUMNS)


def spread_diagnostics(predictions):
    """Measure frozen Top-N minus Bottom-N BTC-relative spreads by regime."""
    ranked = _ranked_predictions(predictions)
    day_rows = []
    day_keys = [
        "split", "model_id", "fold_id", "timestamp_utc", "btc_regime"
    ]

    for values, day in ranked.groupby(
        day_keys, sort=True, dropna=False
    ):
        base = dict(zip(day_keys, values))
        actual = pd.to_numeric(
            day["actual_btc_relative_forward_return"],
            errors="coerce",
        )
        count = len(day)

        for top_n in TOP_COUNTS:
            n = min(top_n, count // 2)
            if n <= 0:
                continue

            top = actual.iloc[:n]
            bottom = actual.iloc[-n:]
            day_rows.append(base | {
                "top_n": top_n,
                "top_relative_return": top.mean(),
                "bottom_relative_return": bottom.mean(),
                "spread": top.mean() - bottom.mean(),
            })

    daily = pd.DataFrame(day_rows)
    rows = []

    for values, group in daily.groupby(
        ["split", "model_id", "top_n", "btc_regime"],
        sort=True,
        dropna=False,
    ):
        split, model_id, top_n, btc_regime = values
        spread = pd.to_numeric(
            group["spread"], errors="coerce"
        ).dropna()

        rows.append({
            "split": split,
            "model_id": model_id,
            "top_n": top_n,
            "btc_regime": btc_regime,
            "day_count": len(group),
            "mean_top_relative_return": group[
                "top_relative_return"
            ].mean(),
            "mean_bottom_relative_return": group[
                "bottom_relative_return"
            ].mean(),
            "mean_top_minus_bottom_spread": (
                spread.mean() if len(spread) else np.nan
            ),
            "median_top_minus_bottom_spread": (
                spread.median() if len(spread) else np.nan
            ),
            "positive_spread_rate": (
                spread.gt(0).mean() if len(spread) else np.nan
            ),
        })

    return pd.DataFrame(rows, columns=SPREAD_COLUMNS)


def _json_load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def run_phase5(
    phase3_root=PHASE3_ROOT,
    phase4_root=PHASE4_ROOT,
    model_root=MODEL_ROOT,
    output_root=PHASE5_ROOT,
):
    """Generate deterministic read-only Phase 5 diagnostics."""
    paths, predictions, panel, daily, metrics = load_inputs(
        phase3_root=phase3_root,
        phase4_root=phase4_root,
        model_root=model_root,
    )

    hashes_before = {
        name: _sha256(path) for name, path in paths.items()
    }

    frames = {
        "regime_performance": regime_performance(
            daily, predictions
        ),
        "relative_performance": relative_performance(
            daily, panel
        ),
        "drawdown_episodes": drawdown_episodes(daily),
        "asset_attribution": asset_attribution(predictions),
        "spread_diagnostics": spread_diagnostics(predictions),
    }

    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    output_paths = {
        name: output_root / f"{name}.csv"
        for name in frames
    }

    for name, path in output_paths.items():
        frames[name].to_csv(path, index=False)

    hashes_after = {
        name: _sha256(path) for name, path in paths.items()
    }

    if hashes_after != hashes_before:
        raise RuntimeError(
            "Frozen Phase 3/4 inputs changed during Phase 5"
        )

    manifest = {
        "phase": 5,
        "research_version": "crypto_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "objective": (
            "Explain whether frozen Phase 3 BTC-relative ranking evidence "
            "translates into Phase 4 absolute portfolio outcomes."
        ),
        "policy": (
            "read-only diagnostics only; no fitting, retraining, retuning, "
            "threshold selection, strategy selection, promotion, portfolio "
            "rule changes, live execution, leverage, or derivatives"
        ),
        "primary_strategy": {
            "horizon_days": PRIMARY_HORIZON_DAYS,
            "model_id": PRIMARY_MODEL_ID,
        },
        "controls": list(CONTROL_MODEL_IDS),
        "holdout_policy": (
            "Holdout is descriptive only. No Phase 5 result may be used "
            "to choose or tune a parameter or retroactively alter "
            "Phase 3/4 rules."
        ),
        "btc_regime_source": (
            "Frozen btc_regime already stamped in Phase 3 predictions. "
            "Phase 5 does not derive or tune a new regime classifier."
        ),
        "relative_return_convention": (
            "Phase 3 attribution/spread diagnostics use frozen "
            "actual_btc_relative_forward_return. Phase 4 realized "
            "relative diagnostics compare net portfolio return with "
            "contemporaneous BTC return_1d."
        ),
        "source_files": {
            name: {
                "path": str(path),
                "sha256": hashes_before[name],
            }
            for name, path in paths.items()
        },
        "source_row_counts": {
            "phase3_predictions_7d_candidate_controls": len(predictions),
            "research_panel_7d": len(panel),
            "phase4_portfolio_daily": len(daily),
            "phase4_portfolio_metrics": len(metrics),
        },
        "outputs": {
            name: str(path)
            for name, path in output_paths.items()
        },
        "output_row_counts": {
            name: len(frame)
            for name, frame in frames.items()
        },
        "phase3_manifest": _json_load(
            paths["phase3_manifest"]
        ),
        "phase4_manifest": _json_load(
            paths["phase4_manifest"]
        ),
    }

    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, default=str) + "\n",
        encoding="utf-8",
    )

    return manifest, frames


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase3-root", type=Path, default=PHASE3_ROOT
    )
    parser.add_argument(
        "--phase4-root", type=Path, default=PHASE4_ROOT
    )
    parser.add_argument(
        "--model-root", type=Path, default=MODEL_ROOT
    )
    parser.add_argument(
        "--output-root", type=Path, default=PHASE5_ROOT
    )
    args = parser.parse_args(argv)

    manifest, _ = run_phase5(
        phase3_root=args.phase3_root,
        phase4_root=args.phase4_root,
        model_root=args.model_root,
        output_root=args.output_root,
    )

    print(json.dumps({
        "phase": manifest["phase"],
        "policy": manifest["policy"],
        "output_row_counts": manifest["output_row_counts"],
        "outputs": manifest["outputs"],
    }, indent=2))


if __name__ == "__main__":
    main()
