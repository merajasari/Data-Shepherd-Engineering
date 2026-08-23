"""Dedicated causal and no-brokerage invariants for frozen V8 operations.

The tests are deterministic, read-only, and use synthetic in-memory market
frames. They never read holdout outcomes, write production evidence, or place
brokerage orders.
"""
from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pandas as pd

from ml.v8.holdout_runner import _rank_for_date

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROTECTED_RUNTIME_FILES = [
    PROJECT_ROOT / "ml/v8/holdout_runner.py",
    PROJECT_ROOT / "ml/v8/eod_guard.py",
    PROJECT_ROOT / "ml/v8/eod_orchestrator.py",
    PROJECT_ROOT / "ml/v8/scheduled_entrypoint.py",
    PROJECT_ROOT / "ml/v8/operational_monitor.py",
]

FORBIDDEN_IMPORT_ROOTS = {
    "alpaca",
    "alpaca_trade_api",
    "ibapi",
    "ib_insync",
    "robin_stocks",
    "robinhood",
}
FORBIDDEN_CALL_NAMES = {
    "buy",
    "cancel_order",
    "create_order",
    "execute_order",
    "order_buy",
    "order_sell",
    "place_order",
    "sell",
    "submit_order",
    "transmit_order",
}


def _synthetic_market():
    dates = pd.date_range("2026-01-02", periods=90, freq="B", tz="UTC")
    decision_ts = dates[70]
    spy_ret = pd.Series(
        0.0004 + 0.006 * np.sin(np.arange(len(dates)) / 7.0),
        index=dates,
        dtype=float,
    )
    spy_close = 100.0 * (1.0 + spy_ret).cumprod()
    frames = {
        "SPY": pd.DataFrame(
            {
                "close": spy_close,
                "ret1": spy_ret,
                "volatility_20d": spy_ret.rolling(20, min_periods=20).std(),
                "distance_from_low_20d": spy_close / spy_close.rolling(20, min_periods=20).min() - 1.0,
            },
            index=dates,
        )
    }

    symbols = [f"S{i:03d}" for i in range(100)]
    for index, symbol in enumerate(symbols):
        phase = index / 11.0
        ret = pd.Series(
            0.0002
            + (index - 49.5) * 0.000003
            + 0.004 * np.sin(np.arange(len(dates)) / 5.0 + phase)
            + 0.35 * spy_ret.to_numpy(),
            index=dates,
            dtype=float,
        )
        close = (70.0 + index) * (1.0 + ret).cumprod()
        frames[symbol] = pd.DataFrame(
            {
                "close": close,
                "ret1": ret,
                "volatility_20d": ret.rolling(20, min_periods=20).std(),
                "distance_from_low_20d": close / close.rolling(20, min_periods=20).min() - 1.0,
            },
            index=dates,
        )
    return symbols, frames, decision_ts


def test_post_decision_data_cannot_change_ranking():
    symbols, original, decision_ts = _synthetic_market()
    perturbed = {symbol: frame.copy(deep=True) for symbol, frame in original.items()}

    future_mask = perturbed["SPY"].index > decision_ts
    for index, symbol in enumerate(["SPY", *symbols]):
        frame = perturbed[symbol]
        scale = 10.0 + index
        frame.loc[future_mask, "ret1"] = scale
        frame.loc[future_mask, "volatility_20d"] = scale * 2.0
        frame.loc[future_mask, "distance_from_low_20d"] = scale * 3.0
        frame.loc[future_mask, "close"] = scale * 1000.0

    before = _rank_for_date(decision_ts, symbols, original)
    after = _rank_for_date(decision_ts, symbols, perturbed)

    if before["symbol"].tolist() != after["symbol"].tolist():
        raise AssertionError("Post-decision observations changed the V8 ranking order")
    if not np.allclose(
        before["orthogonal_signal"].to_numpy(),
        after["orthogonal_signal"].to_numpy(),
        rtol=0.0,
        atol=1e-12,
    ):
        raise AssertionError("Post-decision observations changed V8 decision scores")


def _dotted_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def test_protected_runtime_has_no_brokerage_interface():
    violations = []
    for path in PROTECTED_RUNTIME_FILES:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".", 1)[0]
                    if root in FORBIDDEN_IMPORT_ROOTS:
                        violations.append(f"{path.name}:{node.lineno}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                root = (node.module or "").split(".", 1)[0]
                if root in FORBIDDEN_IMPORT_ROOTS:
                    violations.append(f"{path.name}:{node.lineno}: from {node.module}")
            elif isinstance(node, ast.Call):
                dotted = _dotted_name(node.func)
                final_name = dotted.rsplit(".", 1)[-1]
                if final_name in FORBIDDEN_CALL_NAMES:
                    violations.append(f"{path.name}:{node.lineno}: call {dotted}")

    if violations:
        raise AssertionError(
            "Brokerage/order interface detected in protected V8 runtime:\n  - "
            + "\n  - ".join(violations)
        )


def main():
    print("V8 HOLDOUT DEDICATED INVARIANT TESTS")
    print("=" * 88)

    test_post_decision_data_cannot_change_ranking()
    print("[PASS] Post-decision data cannot change an existing V8 decision ranking")

    test_protected_runtime_has_no_brokerage_interface()
    print("[PASS] Protected V8 runtime imports/calls no brokerage order interface")

    print("Look-ahead leakage: NOT DETECTED")
    print("Brokerage interface: ABSENT")
    print("Production evidence modified: NO")
    print("Brokerage orders: OFF")
    print("Status: PASSED")


if __name__ == "__main__":
    main()
