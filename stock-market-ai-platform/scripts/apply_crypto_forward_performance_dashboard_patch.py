#!/usr/bin/env python3
"""Apply the dormant Sep 1+ forward-performance dashboard patch.

Presentation/read-only change only. The patch reads existing Shared V2 and XRP
Phase 7 forward artifacts. It never fits a model, changes policy state, writes a
forward journal, backfills observations, or places orders.
"""
from pathlib import Path

SERVICE = Path("webapp/services/crypto_dashboard_service.py")
TEMPLATE = Path("webapp/templates/crypto.html")

service = SERVICE.read_text(encoding="utf-8")
template = TEMPLATE.read_text(encoding="utf-8")

FUNCTIONS = r'''

def _equity_drawdown(values):
    clean = [float(x) for x in values if pd.notna(x)]
    if not clean:
        return None
    series = pd.Series([1.0] + clean, dtype=float)
    return float((series / series.cummax() - 1.0).min())


def _shared_v2_forward_performance():
    holdout = pd.Timestamp("2026-09-01T00:00:00Z")
    now = pd.Timestamp.now(tz="UTC")
    journal = _read_csv(V2_JOURNAL_PATH)
    base = {
        "name": "Shared Crypto V2",
        "holdout_start_utc": holdout.isoformat(),
        "cost_bps": 5.0,
        "brokerage_orders": False,
    }
    if now < holdout:
        return {**base, "status": "AWAITING_FUTURE_OBSERVATIONS", "decision_count": 0, "realized_count": 0, "pending_count": 0, "switch_count": 0, "candidate_equity": 1.0, "candidate_return": 0.0, "candidate_max_drawdown": None, "benchmark_label": "Always BTC", "benchmark_equity": 1.0, "benchmark_return": 0.0, "benchmark_max_drawdown": None, "latest_realized_utc": None}
    if journal.empty or "decision_timestamp_utc" not in journal:
        return {**base, "status": "AWAITING_FUTURE_OBSERVATIONS", "decision_count": 0, "realized_count": 0, "pending_count": 0, "switch_count": 0, "candidate_equity": 1.0, "candidate_return": 0.0, "candidate_max_drawdown": None, "benchmark_label": "Always BTC", "benchmark_equity": 1.0, "benchmark_return": 0.0, "benchmark_max_drawdown": None, "latest_realized_utc": None}
    frame = journal.copy()
    frame["decision_timestamp_utc"] = pd.to_datetime(frame["decision_timestamp_utc"], utc=True, errors="coerce")
    frame = frame[frame["decision_timestamp_utc"] >= holdout].sort_values("decision_timestamp_utc")
    realized = frame[frame.get("status", pd.Series(index=frame.index, dtype=str)).eq("REALIZED")].copy()
    decision_count = len(frame)
    realized_count = len(realized)
    pending_count = max(0, decision_count - realized_count)
    switch_count = int(pd.to_numeric(frame.get("sleeve_switch", pd.Series(index=frame.index, dtype=float)), errors="coerce").fillna(0).sum())
    if realized.empty:
        return {**base, "status": "AWAITING_FUTURE_OBSERVATIONS", "decision_count": decision_count, "realized_count": 0, "pending_count": pending_count, "switch_count": switch_count, "candidate_equity": 1.0, "candidate_return": 0.0, "candidate_max_drawdown": None, "benchmark_label": "Always BTC", "benchmark_equity": 1.0, "benchmark_return": 0.0, "benchmark_max_drawdown": None, "latest_realized_utc": None}
    candidate_path = pd.to_numeric(realized["equity"], errors="coerce").dropna()
    candidate_equity = float(candidate_path.iloc[-1]) if len(candidate_path) else 1.0
    btc_returns = pd.to_numeric(realized["btc_realized_return_1h"], errors="coerce").dropna()
    btc_path = (1.0 + btc_returns).cumprod()
    benchmark_equity = float(btc_path.iloc[-1]) if len(btc_path) else 1.0
    latest_realized = realized["realized_through_utc"].dropna().iloc[-1] if "realized_through_utc" in realized and realized["realized_through_utc"].notna().any() else realized["decision_timestamp_utc"].iloc[-1].isoformat()
    return {**base, "status": "FORWARD_EVALUATION_ACTIVE", "decision_count": decision_count, "realized_count": realized_count, "pending_count": pending_count, "switch_count": switch_count, "candidate_equity": candidate_equity, "candidate_return": candidate_equity - 1.0, "candidate_max_drawdown": _equity_drawdown(candidate_path.tolist()), "benchmark_label": "Always BTC", "benchmark_equity": benchmark_equity, "benchmark_return": benchmark_equity - 1.0, "benchmark_max_drawdown": _equity_drawdown(btc_path.tolist()), "latest_realized_utc": str(latest_realized)}


def _xrp_phase7_forward_performance():
    holdout = pd.Timestamp("2026-09-01T00:00:00Z")
    now = pd.Timestamp.now(tz="UTC")
    summary = _read_json(XRP_PHASE7_SUMMARY_PATH)
    base = {
        "name": "XRP V1 Phase 7",
        "holdout_start_utc": holdout.isoformat(),
        "cost_bps": 5.0,
        "brokerage_orders": False,
    }
    if now < holdout or not summary or int(summary.get("valid_realization_count", 0) or 0) == 0:
        return {**base, "status": "AWAITING_FUTURE_OBSERVATIONS", "decision_count": int(summary.get("decision_count", 0) or 0) if summary else 0, "realized_count": int(summary.get("valid_realization_count", 0) or 0) if summary else 0, "invalid_count": int(summary.get("invalid_realization_count", 0) or 0) if summary else 0, "pending_count": int(summary.get("pending_realization_count", 0) or 0) if summary else 0, "switch_count": int(summary.get("state_switch_count", 0) or 0) if summary else 0, "candidate_equity": 1.0, "candidate_return": 0.0, "candidate_max_drawdown": None, "benchmark_label": "Always BTC", "benchmark_equity": 1.0, "benchmark_return": 0.0, "benchmark_max_drawdown": None, "latest_realized_utc": None}
    candidate_equity = float(summary.get("equity_5bps", 1.0))
    benchmark_equity = float(summary.get("always_btc_equity", 1.0))
    return {**base, "status": "FORWARD_EVALUATION_ACTIVE", "decision_count": int(summary.get("decision_count", 0) or 0), "realized_count": int(summary.get("valid_realization_count", 0) or 0), "invalid_count": int(summary.get("invalid_realization_count", 0) or 0), "pending_count": int(summary.get("pending_realization_count", 0) or 0), "switch_count": int(summary.get("state_switch_count", 0) or 0), "candidate_equity": candidate_equity, "candidate_return": candidate_equity - 1.0, "candidate_max_drawdown": summary.get("max_drawdown_5bps"), "benchmark_label": "Always BTC", "benchmark_equity": benchmark_equity, "benchmark_return": benchmark_equity - 1.0, "benchmark_max_drawdown": summary.get("always_btc_max_drawdown"), "latest_realized_utc": summary.get("last_realized_decision_utc")}


def _future_forward_performance():
    return {
        "holdout_start_utc": "2026-09-01T00:00:00+00:00",
        "shared_v2": _shared_v2_forward_performance(),
        "xrp_phase7": _xrp_phase7_forward_performance(),
        "note": "Untouched Sep 1+ paper-evaluation evidence only. No historical backfill, no tuning, and no real brokerage orders.",
    }
'''

if "def _future_forward_performance():" not in service:
    marker = "\ndef _development_research_tracks():\n"
    if marker not in service:
        raise SystemExit("Could not find service insertion marker")
    service = service.replace(marker, FUNCTIONS + marker, 1)
    print("[APPLY] forward performance loaders")
else:
    print("[SKIP] forward performance loaders already present")

old = "    forward_evaluation_readiness = _forward_evaluation_readiness()\n"
new = old + "    future_forward_performance = _future_forward_performance()\n"
if "future_forward_performance = _future_forward_performance()" not in service:
    if old not in service:
        raise SystemExit("Could not find payload construction marker")
    service = service.replace(old, new, 1)
    print("[APPLY] forward performance payload construction")
else:
    print("[SKIP] forward performance payload construction already present")

old = '        "forward_evaluation_readiness": forward_evaluation_readiness,\n'
new = old + '        "future_forward_performance": future_forward_performance,\n'
if '"future_forward_performance": future_forward_performance' not in service:
    if old not in service:
        raise SystemExit("Could not find payload exposure marker")
    service = service.replace(old, new, 1)
    print("[APPLY] forward performance payload exposure")
else:
    print("[SKIP] forward performance payload exposure already present")

CARD = r'''{% set fp=crypto.future_forward_performance %}
<section class="card" style="margin-bottom:22px"><div class="label">UNTOUCHED FORWARD PERFORMANCE</div><h2>Sep 1+ Paper Evaluation</h2><p class="muted">This section is intentionally dormant before the future boundary. It reads only genuine Sep 1+ Shared V2 journal realizations and XRP Phase 7 realization summaries. Development results never populate these cards.</p><div class="grid" style="grid-template-columns:repeat(2,1fr);margin-top:18px">{% for track in [fp.shared_v2,fp.xrp_phase7] %}<div class="card"><div class="label">{{ track.name }}</div><h3 class="{{ 'positive' if track.status == 'FORWARD_EVALUATION_ACTIVE' else '' }}" {% if track.status == 'AWAITING_FUTURE_OBSERVATIONS' %}style="color:var(--gold)"{% endif %}>{{ track.status }}</h3><div class="grid" style="grid-template-columns:repeat(2,1fr);gap:12px"><div class="metric"><span>REALIZED</span><strong>{{ track.realized_count }}</strong></div><div class="metric"><span>PENDING</span><strong>{{ track.pending_count }}</strong></div><div class="metric"><span>SWITCHES</span><strong>{{ track.switch_count }}</strong></div><div class="metric"><span>COST</span><strong>{{ '{:.0f} bps'.format(track.cost_bps) }}</strong></div><div class="metric"><span>CANDIDATE EQUITY</span><strong class="{{ 'positive' if track.candidate_equity >= 1 else 'negative' }}">{{ '{:.4f}x'.format(track.candidate_equity) }}</strong></div><div class="metric"><span>{{ track.benchmark_label|upper }}</span><strong>{{ '{:.4f}x'.format(track.benchmark_equity) }}</strong></div><div class="metric"><span>CANDIDATE RETURN</span><strong>{{ '{:+.2f}%'.format(track.candidate_return*100) }}</strong></div><div class="metric"><span>BENCHMARK RETURN</span><strong>{{ '{:+.2f}%'.format(track.benchmark_return*100) }}</strong></div></div><p style="margin-top:14px"><strong>Candidate max drawdown:</strong> {{ '{:.2f}%'.format(track.candidate_max_drawdown*100) if track.candidate_max_drawdown is not none else '—' }}</p><p><strong>Benchmark max drawdown:</strong> {{ '{:.2f}%'.format(track.benchmark_max_drawdown*100) if track.benchmark_max_drawdown is not none else '—' }}</p><p><strong>Latest realized:</strong> <span class="muted">{{ track.latest_realized_utc or '—' }}</span></p>{% if track.invalid_count is defined %}<p><strong>Invalid data-gap realizations:</strong> {{ track.invalid_count }}</p>{% endif %}<p><strong>Real orders:</strong> <span class="positive">NO</span></p></div>{% endfor %}</div><div class="warning" style="margin-top:16px">{{ fp.note }}</div></section>
'''

if "UNTOUCHED FORWARD PERFORMANCE" not in template:
    marker = "{% set live=crypto.live_v2 %}\n"
    if marker not in template:
        raise SystemExit("Could not find template insertion marker")
    template = template.replace(marker, CARD + marker, 1)
    print("[APPLY] untouched forward performance section")
else:
    print("[SKIP] untouched forward performance section already present")

SERVICE.write_text(service, encoding="utf-8")
TEMPLATE.write_text(template, encoding="utf-8")
print("Untouched forward-performance dashboard patch complete.")
