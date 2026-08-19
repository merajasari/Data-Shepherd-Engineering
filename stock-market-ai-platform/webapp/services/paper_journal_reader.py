"""Read and summarize the append-only V4 paper-trading journal.

Read-only. Does not modify portfolio or journal state.
The parsed summary is cached by file mtime so repeated dashboard polls do not
re-read the entire journal. Equity history is compacted for presentation while
all summary metrics still use the complete journal.
"""

import json
from pathlib import Path

JOURNAL_PATH = Path("data/paper_trading/journal.jsonl")
MAX_HISTORY_POINTS = 300

_CACHE_MTIME_NS = None
_CACHE_SUMMARY = None


def _compact_history(rows, max_points=MAX_HISTORY_POINTS):
    if len(rows) <= max_points:
        return rows
    if max_points < 3:
        return [rows[0], rows[-1]]
    step = (len(rows) - 1) / (max_points - 1)
    indices = sorted({0, len(rows) - 1, *[round(i * step) for i in range(max_points)]})
    return [rows[i] for i in indices if 0 <= i < len(rows)]


def load_journal():
    if not JOURNAL_PATH.exists():
        return []
    rows = []
    with JOURNAL_PATH.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def max_drawdown(equities):
    if not equities:
        return 0.0
    peak = equities[0]
    worst = 0.0
    for equity in equities:
        peak = max(peak, equity)
        drawdown = equity / peak - 1.0
        worst = min(worst, drawdown)
    return worst


def _build_summary(rows):
    if not rows:
        return {
            "observation_count": 0,
            "start_timestamp": None,
            "end_timestamp": None,
            "starting_equity": None,
            "ending_equity": None,
            "forward_return": 0.0,
            "max_drawdown": 0.0,
            "rebalance_cycles": 0,
            "trade_action_count": 0,
            "equity_history": [],
        }

    equities = [float(row["equity"]) for row in rows]
    full_equity_history = [
        {"timestamp": row.get("timestamp"), "equity": float(row["equity"])}
        for row in rows
        if row.get("timestamp") is not None and row.get("equity") is not None
    ]
    equity_history = _compact_history(full_equity_history)

    trade_action_count = sum(len(row.get("trade_actions", [])) for row in rows)
    rebalance_cycles = sum(bool(row.get("trade_actions", [])) for row in rows)
    starting_equity = equities[0]
    ending_equity = equities[-1]
    forward_return = ending_equity / starting_equity - 1.0 if starting_equity else 0.0

    benchmark_rows = [row for row in rows if row.get("benchmark_price") is not None]
    if benchmark_rows:
        benchmark_start_price = float(benchmark_rows[0]["benchmark_price"])
        benchmark_end_price = float(benchmark_rows[-1]["benchmark_price"])
        benchmark_return = benchmark_end_price / benchmark_start_price - 1.0
    else:
        benchmark_start_price = None
        benchmark_end_price = None
        benchmark_return = 0.0

    return {
        "observation_count": len(rows),
        "start_timestamp": rows[0].get("timestamp"),
        "end_timestamp": rows[-1].get("timestamp"),
        "starting_equity": starting_equity,
        "ending_equity": ending_equity,
        "forward_return": forward_return,
        "max_drawdown": max_drawdown(equities),
        "rebalance_cycles": rebalance_cycles,
        "trade_action_count": trade_action_count,
        "latest_top_five": rows[-1].get("top_five_symbols", []),
        "latest_trade_count": rows[-1].get("trade_count", 0),
        "benchmark_observation_count": len(benchmark_rows),
        "benchmark_symbol": benchmark_rows[-1].get("benchmark_symbol") if benchmark_rows else None,
        "benchmark_start_price": benchmark_start_price,
        "benchmark_end_price": benchmark_end_price,
        "benchmark_return": benchmark_return,
        "excess_return": forward_return - benchmark_return,
        "equity_history": equity_history,
        "equity_history_full_count": len(full_equity_history),
        "equity_history_compacted": len(full_equity_history) > len(equity_history),
    }


def summarize_journal():
    global _CACHE_MTIME_NS, _CACHE_SUMMARY

    if not JOURNAL_PATH.exists():
        _CACHE_MTIME_NS = None
        _CACHE_SUMMARY = _build_summary([])
        return _CACHE_SUMMARY

    try:
        mtime_ns = JOURNAL_PATH.stat().st_mtime_ns
    except OSError:
        return _build_summary([])

    if _CACHE_SUMMARY is not None and _CACHE_MTIME_NS == mtime_ns:
        return _CACHE_SUMMARY

    summary = _build_summary(load_journal())
    _CACHE_MTIME_NS = mtime_ns
    _CACHE_SUMMARY = summary
    return _CACHE_SUMMARY
