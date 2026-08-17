#!/usr/bin/env python3
"""Apply landing-page header sizing and dormant post-boundary forward summary.

This patch is presentation/read-only only. It does not modify frozen model,
policy, execution, or journal-writing logic.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STOCK = ROOT / "webapp/templates/index.html"
CRYPTO = ROOT / "webapp/templates/crypto.html"
SERVICE = ROOT / "webapp/services/crypto_dashboard_service.py"

HEADER_CSS = r'''
/* Match landing-page brand/header sizing exactly. */
header{gap:30px;padding:45px 0 30px}
.brand{gap:22px;min-width:0}
.brand>a{display:block;flex:0 0 auto}
.brand img{display:block;width:220px;height:125px;object-fit:contain;border-radius:16px;transform:scale(1.55);transform-origin:center center;filter:drop-shadow(0 0 18px rgba(54,216,255,.16))}
.brand>div{min-width:0}
.brand .eyebrow{font-size:.75rem}
.brand h1{margin:8px 0;font-size:clamp(2.1rem,4vw,3.7rem)}
.brand .muted{font-size:1.05rem}
@media(max-width:650px){
  header{align-items:flex-start;flex-direction:column}
  .brand{width:100%;align-items:flex-start;flex-direction:column;gap:14px}
  .brand img{width:185px;height:105px}
  .actions{width:100%}
}
'''.strip()

VALIDATION_CODE = r'''

FORWARD_VALIDATION_MIN_REALIZATIONS = 30


def _forward_validation_track(track):
    realized = int(track.get("realized_count", 0) or 0)
    remaining = max(0, FORWARD_VALIDATION_MIN_REALIZATIONS - realized)
    base = {
        "name": track.get("name"),
        "minimum_realizations": FORWARD_VALIDATION_MIN_REALIZATIONS,
        "realized_count": realized,
        "observations_remaining": remaining,
        "brokerage_orders": False,
    }
    if realized < FORWARD_VALIDATION_MIN_REALIZATIONS:
        return {
            **base,
            "status": "AWAITING_MINIMUM_FUTURE_SAMPLE",
            "assessment_ready": False,
            "assessment": None,
            "candidate_return": track.get("candidate_return", 0.0),
            "benchmark_return": track.get("benchmark_return", 0.0),
            "excess_return": None,
            "candidate_max_drawdown": track.get("candidate_max_drawdown"),
            "benchmark_max_drawdown": track.get("benchmark_max_drawdown"),
            "drawdown_comparison": "NOT_AVAILABLE",
        }

    candidate_return = float(track.get("candidate_return", 0.0) or 0.0)
    benchmark_return = float(track.get("benchmark_return", 0.0) or 0.0)
    excess = candidate_return - benchmark_return
    tolerance = 1e-12
    if excess > tolerance:
        assessment = "OUTPERFORMING_BENCHMARK"
    elif excess < -tolerance:
        assessment = "UNDERPERFORMING_BENCHMARK"
    else:
        assessment = "MATCHING_BENCHMARK"

    candidate_dd = track.get("candidate_max_drawdown")
    benchmark_dd = track.get("benchmark_max_drawdown")
    if candidate_dd is None or benchmark_dd is None:
        dd_comparison = "NOT_AVAILABLE"
    elif float(candidate_dd) > float(benchmark_dd) + tolerance:
        dd_comparison = "BETTER_THAN_BENCHMARK"
    elif float(candidate_dd) < float(benchmark_dd) - tolerance:
        dd_comparison = "WORSE_THAN_BENCHMARK"
    else:
        dd_comparison = "MATCHING_BENCHMARK"

    return {
        **base,
        "status": "FORWARD_SAMPLE_ASSESSMENT_AVAILABLE",
        "assessment_ready": True,
        "assessment": assessment,
        "candidate_return": candidate_return,
        "benchmark_return": benchmark_return,
        "excess_return": excess,
        "candidate_max_drawdown": candidate_dd,
        "benchmark_max_drawdown": benchmark_dd,
        "drawdown_comparison": dd_comparison,
    }


def _forward_validation_summary(forward_performance):
    return {
        "minimum_realizations": FORWARD_VALIDATION_MIN_REALIZATIONS,
        "shared_v2": _forward_validation_track(forward_performance["shared_v2"]),
        "xrp_phase7": _forward_validation_track(forward_performance["xrp_phase7"]),
        "note": "Fixed 30-realization gate using untouched Sep 1+ evidence only. This is descriptive forward assessment, not model selection, threshold tuning, or a promotion decision.",
    }
'''.rstrip()

VALIDATION_TEMPLATE = r'''
{% set val=crypto.forward_validation_summary %}
<section class="card" style="margin-bottom:22px"><div class="label">POST-BOUNDARY FORWARD VALIDATION SUMMARY</div><h2>Fixed Future-Sample Assessment</h2><p class="muted">Each frozen track must accumulate {{ val.minimum_realizations }} genuine future realizations before a descriptive candidate-vs-BTC assessment is shown. The gate was fixed before these observations exist.</p><div class="grid" style="grid-template-columns:repeat(2,1fr);margin-top:18px">{% for track in [val.shared_v2,val.xrp_phase7] %}<div class="card"><div class="label">{{ track.name }}</div><h3 class="{{ 'positive' if track.assessment == 'OUTPERFORMING_BENCHMARK' else 'negative' if track.assessment == 'UNDERPERFORMING_BENCHMARK' else '' }}" {% if not track.assessment_ready %}style="color:var(--gold)"{% endif %}>{{ track.assessment if track.assessment_ready else track.status }}</h3><div class="grid" style="grid-template-columns:repeat(2,1fr);gap:12px"><div class="metric"><span>REALIZED SAMPLE</span><strong>{{ track.realized_count }}/{{ track.minimum_realizations }}</strong></div><div class="metric"><span>OBSERVATIONS REMAINING</span><strong>{{ track.observations_remaining }}</strong></div><div class="metric"><span>CANDIDATE RETURN</span><strong>{{ '{:+.2f}%'.format(track.candidate_return*100) }}</strong></div><div class="metric"><span>BTC RETURN</span><strong>{{ '{:+.2f}%'.format(track.benchmark_return*100) }}</strong></div><div class="metric"><span>EXCESS VS BTC</span><strong>{{ '{:+.2f}%'.format(track.excess_return*100) if track.excess_return is not none else '—' }}</strong></div><div class="metric"><span>DRAWDOWN VS BTC</span><strong style="font-size:1rem">{{ track.drawdown_comparison if track.assessment_ready else '—' }}</strong></div></div>{% if track.assessment_ready %}<p style="margin-top:14px"><strong>Candidate max drawdown:</strong> {{ '{:.2f}%'.format(track.candidate_max_drawdown*100) if track.candidate_max_drawdown is not none else '—' }}</p><p><strong>BTC max drawdown:</strong> {{ '{:.2f}%'.format(track.benchmark_max_drawdown*100) if track.benchmark_max_drawdown is not none else '—' }}</p>{% else %}<p class="muted" style="margin-top:14px">No forward assessment is produced until the fixed minimum sample is reached.</p>{% endif %}<p><strong>Real orders:</strong> <span class="positive">NO</span></p></div>{% endfor %}</div><div class="warning" style="margin-top:16px">{{ val.note }}</div></section>
'''.strip()


def add_header_css(path: Path):
    text = path.read_text(encoding="utf-8")
    if "Match landing-page brand/header sizing exactly." in text:
        print(f"[SKIP] header already matched: {path.relative_to(ROOT)}")
        return
    marker = "</style>"
    if marker not in text:
        raise RuntimeError(f"Missing </style> in {path}")
    text = text.replace(marker, "\n" + HEADER_CSS + "\n" + marker, 1)
    path.write_text(text, encoding="utf-8")
    print(f"[APPLY] landing header sizing: {path.relative_to(ROOT)}")


def patch_service():
    text = SERVICE.read_text(encoding="utf-8")
    if "def _forward_validation_summary(" not in text:
        anchor = "\ndef _development_research_tracks():"
        if anchor not in text:
            raise RuntimeError("Could not locate development research anchor")
        text = text.replace(anchor, VALIDATION_CODE + "\n\n" + anchor, 1)
        print("[APPLY] forward validation functions")
    else:
        print("[SKIP] forward validation functions already present")

    old = "    future_forward_performance = _future_forward_performance()\n"
    new = old + "    forward_validation_summary = _forward_validation_summary(future_forward_performance)\n"
    if "forward_validation_summary = _forward_validation_summary" not in text:
        if old not in text:
            raise RuntimeError("Could not locate future-forward construction")
        text = text.replace(old, new, 1)
        print("[APPLY] forward validation payload construction")

    old = '        "future_forward_performance": future_forward_performance,\n'
    new = old + '        "forward_validation_summary": forward_validation_summary,\n'
    if '"forward_validation_summary": forward_validation_summary' not in text:
        if old not in text:
            raise RuntimeError("Could not locate future-forward payload exposure")
        text = text.replace(old, new, 1)
        print("[APPLY] forward validation payload exposure")

    SERVICE.write_text(text, encoding="utf-8")


def patch_crypto_template():
    text = CRYPTO.read_text(encoding="utf-8")
    if "POST-BOUNDARY FORWARD VALIDATION SUMMARY" in text:
        print("[SKIP] validation summary card already present")
        return
    anchor = "{% set live=crypto.live_v2 %}"
    if anchor not in text:
        raise RuntimeError("Could not locate live V2 template anchor")
    text = text.replace(anchor, VALIDATION_TEMPLATE + "\n" + anchor, 1)
    CRYPTO.write_text(text, encoding="utf-8")
    print("[APPLY] forward validation summary card")


def main():
    add_header_css(STOCK)
    add_header_css(CRYPTO)
    patch_service()
    patch_crypto_template()
    print("Dashboard header + forward validation patch complete.")


if __name__ == "__main__":
    main()
