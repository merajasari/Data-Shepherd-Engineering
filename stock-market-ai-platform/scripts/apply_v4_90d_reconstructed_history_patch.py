"""Add a leakage-safe 90-day reconstructed V4 portfolio history.

The generated history is explicitly diagnostic/reconstructed and is kept
separate from the genuine paper-trading journal.  Historical V4 selections
come from the existing expanding-window walk-forward V4 signal generator;
portfolio execution uses next-session opens, a permanent 60% SPY core, a
40% V4 sleeve (five 8% names), and the same 10 bps entry/exit friction used
by the live paper portfolio.
"""

from pathlib import Path


APP = Path("webapp/app.py")
TEMPLATE = Path("webapp/templates/index.html")
SERVICE = Path("webapp/services/v4_reconstructed_history_service.py")
RUNNER = Path("ml/run_v4_90d_reconstruction.py")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"Cannot apply {label}: expected text not found")
    print(f"[APPLY] {label}")
    return text.replace(old, new, 1)


def main() -> None:
    SERVICE.write_text('''"""Read-only loader for reconstructed V4 90-day equity history."""\n\nimport json\nfrom pathlib import Path\n\nPATH = Path("data/paper_trading/v4_reconstructed_90d.json")\n\ndef get_v4_reconstructed_90d_history():\n    if not PATH.exists():\n        return []\n    try:\n        payload = json.loads(PATH.read_text(encoding="utf-8"))\n    except (OSError, json.JSONDecodeError):\n        return []\n    rows = payload.get("history", [])\n    return [\n        {\n            **row,\n            "reconstructed": True,\n            "history_type": "RECONSTRUCTED_90D",\n        }\n        for row in rows\n        if row.get("timestamp") is not None and row.get("equity") is not None\n    ]\n''', encoding="utf-8")
    print("[APPLY] V4 reconstructed history reader")

    RUNNER.write_text('''"""Build a 90-day reconstructed V4 portfolio equity curve.\n\nThis is historical simulation only.  It never writes the genuine paper\nportfolio state or genuine paper journal.  Historical V4 selections are\nwalk-forward/out-of-sample and each signal is executed at the next session\nopen to avoid same-session look-ahead.\n"""\n\nfrom __future__ import annotations\n\nimport json\nfrom datetime import timedelta\nfrom pathlib import Path\n\nimport numpy as np\nimport pandas as pd\n\nfrom ml.backtest_portfolio_v4 import (\n    load_v4_data,\n    generate_walk_forward_signals,\n)\n\nimport sys\nsys.path.append("data-ingestion")\nfrom symbols import SYMBOLS\n\nSTARTING_EQUITY = 100_000.0\nCORE_WEIGHT = 0.60\nV4_WEIGHT = 0.08\nENTRY_COST = 0.001\nEXIT_COST = 0.001\nDAYS = 90\nOUT = Path("data/paper_trading/v4_reconstructed_90d.json")\nSTATE = Path("data/paper_trading/portfolio.json")\n\n\ndef load_prices(symbols):\n    frames = {}\n    for symbol in symbols:\n        p = Path(f"data/features/stocks/{symbol}/{symbol}_features.parquet")\n        if not p.exists():\n            raise FileNotFoundError(f"Missing feature history: {p}")\n        df = pd.read_parquet(p, columns=["timestamp_utc", "open", "close"])\n        df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)\n        frames[symbol] = df.set_index("timestamp_utc").sort_index()\n    return frames\n\n\ndef px(frames, symbol, ts, field):\n    try:\n        value = float(frames[symbol].at[pd.Timestamp(ts), field])\n    except Exception:\n        return None\n    return value if np.isfinite(value) and value > 0 else None\n\n\ndef main():\n    X, y, symbols, timestamps, open_prices = load_v4_data()\n    signals, unique_dates = generate_walk_forward_signals(X, y, symbols, timestamps)\n    dates = [pd.Timestamp(x).tz_convert("UTC") if pd.Timestamp(x).tzinfo else pd.Timestamp(x).tz_localize("UTC") for x in unique_dates]\n    latest = max(dates)\n    requested_start = latest - pd.Timedelta(days=DAYS)\n\n    by_signal = {}\n    for row in signals:\n        ts = pd.Timestamp(row["signal_timestamp"])\n        ts = ts.tz_convert("UTC") if ts.tzinfo else ts.tz_localize("UTC")\n        by_signal.setdefault(ts, []).append(row)\n    for ts in by_signal:\n        by_signal[ts] = sorted(by_signal[ts], key=lambda r: r["probability"], reverse=True)[:5]\n\n    frames = load_prices(list(SYMBOLS) + ["SPY"])\n\n    paper_start = None\n    if STATE.exists():\n        try:\n            state = json.loads(STATE.read_text(encoding="utf-8"))\n            raw = state.get("strategy_started_at") or state.get("created_at")\n            if raw:\n                paper_start = pd.Timestamp(raw)\n                paper_start = paper_start.tz_convert("UTC") if paper_start.tzinfo else paper_start.tz_localize("UTC")\n        except Exception:\n            paper_start = None\n\n    eligible_dates = [d for d in dates if d >= requested_start and (paper_start is None or d < paper_start)]\n    if len(eligible_dates) < 2:\n        raise RuntimeError("Not enough pre-paper dates inside requested 90-day window")\n\n    previous = {dates[i]: dates[i-1] for i in range(1, len(dates))}\n    first = None\n    first_target = None\n    for d in eligible_dates:\n        sig = by_signal.get(previous.get(d), [])\n        target = [r["symbol"] for r in sig][:5]\n        needed = ["SPY", *target]\n        if len(target) == 5 and all(px(frames, s, d, "open") for s in needed):\n            first, first_target = d, target\n            break\n    if first is None:\n        raise RuntimeError("Could not find a valid reconstructed start session")\n\n    cash = STARTING_EQUITY\n    positions = {}\n    trades = 0\n    friction = 0.0\n\n    def buy(symbol, sleeve, budget, d):\n        nonlocal cash, trades, friction\n        price = px(frames, symbol, d, "open")\n        if price is None or budget <= 0:\n            return\n        effective = price * (1.0 + ENTRY_COST)\n        shares = budget / effective\n        used = shares * effective\n        fee = shares * price * ENTRY_COST\n        cash -= used\n        friction += fee\n        trades += 1\n        positions[symbol] = {"shares": shares, "sleeve": sleeve}\n\n    buy("SPY", "core", STARTING_EQUITY * CORE_WEIGHT, first)\n    for symbol in first_target:\n        buy(symbol, "v4", STARTING_EQUITY * V4_WEIGHT, first)\n\n    history = []\n\n    for d in [x for x in eligible_dates if x >= first]:\n        prev = previous.get(d)\n        sig = by_signal.get(prev, [])\n        target = [r["symbol"] for r in sig][:5]\n\n        if len(target) == 5 and d != first:\n            current_v4 = {s for s,p in positions.items() if p["sleeve"] == "v4"}\n            target_set = set(target)\n            for symbol in sorted(current_v4 - target_set):\n                price = px(frames, symbol, d, "open")\n                if price is None:\n                    continue\n                pos = positions.pop(symbol)\n                gross = pos["shares"] * price\n                fee = gross * EXIT_COST\n                cash += gross - fee\n                friction += fee\n                trades += 1\n\n            open_equity = cash\n            for symbol, pos in positions.items():\n                price = px(frames, symbol, d, "open")\n                if price is not None:\n                    open_equity += pos["shares"] * price\n\n            current_v4 = {s for s,p in positions.items() if p["sleeve"] == "v4"}\n            for symbol in target:\n                if symbol in current_v4:\n                    continue\n                budget = min(open_equity * V4_WEIGHT, cash)\n                buy(symbol, "v4", budget, d)\n\n        close_equity = cash\n        valid = True\n        for symbol, pos in positions.items():\n            price = px(frames, symbol, d, "close")\n            if price is None:\n                valid = False\n                break\n            close_equity += pos["shares"] * price\n        if not valid:\n            continue\n\n        history.append({\n            "timestamp": d.isoformat(),\n            "equity": round(close_equity, 2),\n            "reconstructed": True,\n            "history_type": "RECONSTRUCTED_90D",\n            "top_five": target if len(target) == 5 else None,\n        })\n\n    if not history:\n        raise RuntimeError("No reconstructed equity observations produced")\n\n    payload = {\n        "history_type": "RECONSTRUCTED_90D",\n        "simulation_only": True,\n        "genuine_paper_journal_modified": False,\n        "brokerage_orders": False,\n        "requested_calendar_days": DAYS,\n        "start": history[0]["timestamp"],\n        "end": history[-1]["timestamp"],\n        "observations": len(history),\n        "starting_equity": STARTING_EQUITY,\n        "ending_equity": history[-1]["equity"],\n        "total_return_pct": round((history[-1]["equity"] / STARTING_EQUITY - 1.0) * 100.0, 4),\n        "trade_actions": trades,\n        "modeled_friction": round(friction, 2),\n        "method": "walk-forward V4 signal on session t; execute changes at t+1 open; 60% permanent SPY core; five 8% V4 names; 10 bps entry/exit friction",\n        "paper_start_boundary": paper_start.isoformat() if paper_start is not None else None,\n        "history": history,\n    }\n    OUT.parent.mkdir(parents=True, exist_ok=True)\n    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")\n\n    print("V4 90-DAY RECONSTRUCTED HISTORY")\n    print("=" * 72)\n    print("Start:", payload["start"])\n    print("End:", payload["end"])\n    print("Observations:", payload["observations"])\n    print("Ending equity:", f'${payload["ending_equity"]:,.2f}')\n    print("Return:", f'{payload["total_return_pct"]:+.4f}%')\n    print("Trade actions:", payload["trade_actions"])\n    print("Modeled friction:", f'${payload["modeled_friction"]:,.2f}')\n    print("Paper boundary:", payload["paper_start_boundary"])\n    print()\n    print("RECONSTRUCTED/SIMULATION ONLY. Genuine paper journal unchanged. No brokerage orders.")\n\nif __name__ == "__main__":\n    main()\n''', encoding="utf-8")
    print("[APPLY] V4 90-day walk-forward reconstruction runner")

    text = APP.read_text(encoding="utf-8")
    text = replace_once(
        text,
        'from webapp.services.v4_realtime_equity_journal_service import get_v4_realtime_equity_history  # noqa: E402\n',
        'from webapp.services.v4_realtime_equity_journal_service import get_v4_realtime_equity_history  # noqa: E402\nfrom webapp.services.v4_reconstructed_history_service import get_v4_reconstructed_90d_history  # noqa: E402\n',
        "app import for V4 reconstructed history",
    )
    text = replace_once(
        text,
        '    history = list(forward.get("equity_history", []))\n    history.extend(get_v4_realtime_equity_history())\n    history.sort(key=lambda row: str(row.get("timestamp") or ""))\n    chart_history = [\n        {\n            "timestamp": forward.get("start_timestamp"),\n',
        '    reconstructed = get_v4_reconstructed_90d_history()\n    history = list(reconstructed)\n    history.extend(forward.get("equity_history", []))\n    history.extend(get_v4_realtime_equity_history())\n    history.sort(key=lambda row: str(row.get("timestamp") or ""))\n    reconstructed_start = reconstructed[0].get("timestamp") if reconstructed else forward.get("start_timestamp")\n    chart_history = [\n        {\n            "timestamp": reconstructed_start,\n',
        "prepend reconstructed history to V4 chart",
    )
    APP.write_text(text, encoding="utf-8")

    text = TEMPLATE.read_text(encoding="utf-8")
    old = "Recorded V4 journal equity plus a live read-only current mark-to-market point."
    new = "90-day reconstructed V4 history, followed by recorded paper-journal equity and a live read-only current mark-to-market point."
    if old in text:
        text = text.replace(old, new, 1)
        print("[APPLY] V4 chart 90-day history description")
    else:
        print("[SKIP] V4 chart description text not found")
    TEMPLATE.write_text(text, encoding="utf-8")

    print()
    print("V4 90-day reconstructed history patch complete.")
    print("Run ml/run_v4_90d_reconstruction.py to build the local history artifact.")
    print("Historical simulation remains explicitly separate from genuine paper observations.")


if __name__ == "__main__":
    main()
