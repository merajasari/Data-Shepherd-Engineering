"""Apply the Forward Evaluation Readiness card to the crypto dashboard.

This is an idempotent source patcher used because the readiness publisher is a
new operational companion service. It changes presentation only; frozen model,
policy, inference, and evaluation code are untouched.
"""
from pathlib import Path

SERVICE = Path("webapp/services/crypto_dashboard_service.py")
TEMPLATE = Path("webapp/templates/crypto.html")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        print(f"[SKIP] {label}: already applied")
        return text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one patch anchor, found {count}")
    print(f"[APPLY] {label}")
    return text.replace(old, new, 1)


def patch_service() -> None:
    text = SERVICE.read_text(encoding="utf-8")
    text = replace_once(
        text,
        'XRP_PHASE7_SUMMARY_PATH = XRP_PHASE7_ROOT / "forward_summary.json"\n',
        'XRP_PHASE7_SUMMARY_PATH = XRP_PHASE7_ROOT / "forward_summary.json"\nREADINESS_STATUS_PATH = Path("data/live/crypto_readiness/readiness_status.json")\n',
        "readiness status path",
    )

    marker = '\ndef _read_predictions():\n'
    readiness_fn = '''\ndef _forward_evaluation_readiness():\n    payload = _read_json(READINESS_STATUS_PATH)\n    if not payload:\n        return {\n            "available": False,\n            "status": "UNAVAILABLE",\n            "ready": False,\n            "message": "Forward-evaluation readiness snapshot is not available yet.",\n        }\n\n    heartbeat = _heartbeat_time(READINESS_STATUS_PATH, payload)\n    age_minutes = None\n    stale = False\n    if heartbeat is not None:\n        age_minutes = max(0.0, (datetime.now(timezone.utc) - heartbeat).total_seconds() / 60.0)\n        stale = age_minutes > 30\n\n    source_status = str(payload.get("status", "NOT_READY_FOR_FORWARD_EVALUATION"))\n    display_status = "STALE" if stale else source_status\n    failures = payload.get("failures") or []\n    return {\n        "available": True,\n        "status": display_status,\n        "source_status": source_status,\n        "ready": bool(payload.get("ready", False)) and not stale,\n        "generated_at_utc": payload.get("generated_at_utc"),\n        "age_minutes": round(age_minutes, 1) if age_minutes is not None else None,\n        "stale_after_minutes": 30,\n        "holdout_start_utc": payload.get("holdout_start_utc"),\n        "pre_holdout": payload.get("pre_holdout"),\n        "passed_checks": int(payload.get("passed_checks", 0) or 0),\n        "total_checks": int(payload.get("total_checks", 0) or 0),\n        "failed_checks": int(payload.get("failed_checks", 0) or 0),\n        "failures": failures[:5],\n        "brokerage_orders": bool(payload.get("brokerage_orders", False)),\n        "message": (\n            "Latest canonical readiness audit passed every check."\n            if payload.get("ready") and not stale\n            else "Readiness requires attention; review failed checks or refresh the audit snapshot."\n        ),\n    }\n\n'''
    text = replace_once(text, marker, readiness_fn + marker, "readiness payload loader")

    text = replace_once(
        text,
        '    operational_health = _operational_health()\n\n    common = {\n',
        '    operational_health = _operational_health()\n    forward_evaluation_readiness = _forward_evaluation_readiness()\n\n    common = {\n',
        "readiness payload construction",
    )
    text = replace_once(
        text,
        '        "operational_health": operational_health,\n',
        '        "operational_health": operational_health,\n        "forward_evaluation_readiness": forward_evaluation_readiness,\n',
        "readiness payload exposure",
    )
    SERVICE.write_text(text, encoding="utf-8")


def patch_template() -> None:
    text = TEMPLATE.read_text(encoding="utf-8")
    anchor = '{% set live=crypto.live_v2 %}'
    block = '''{% set readiness=crypto.forward_evaluation_readiness %}\n<section class="card" style="margin-bottom:22px"><div class="label">FORWARD EVALUATION READINESS</div><h2>Sep 1 Readiness Gate</h2><p class="muted">Latest canonical audit snapshot for Shared V2 + XRP Phase 7. This card is observability only and cannot change a frozen model, policy, journal, or brokerage setting.</p>{% if readiness.available %}<div class="mode">{{ readiness.status }}</div><div class="grid metrics" style="margin-top:18px"><div class="metric"><span>CHECKS PASSED</span><strong class="{{ 'positive' if readiness.ready else 'negative' }}">{{ readiness.passed_checks }}/{{ readiness.total_checks }}</strong></div><div class="metric"><span>FAILED CHECKS</span><strong class="{{ 'positive' if readiness.failed_checks == 0 else 'negative' }}">{{ readiness.failed_checks }}</strong></div><div class="metric"><span>SNAPSHOT UTC</span><strong style="font-size:1rem">{{ readiness.generated_at_utc or '—' }}</strong></div><div class="metric"><span>SNAPSHOT AGE</span><strong>{{ '{:.1f} min'.format(readiness.age_minutes) if readiness.age_minutes is not none else '—' }}</strong></div><div class="metric"><span>HOLDOUT START</span><strong style="font-size:1rem">{{ readiness.holdout_start_utc or '—' }}</strong></div><div class="metric"><span>REAL ORDERS</span><strong class="positive">NO</strong></div></div><p class="{{ 'positive' if readiness.ready else 'muted' }}" style="margin-top:16px"><strong>{{ readiness.message }}</strong></p>{% if readiness.failures %}<div class="warning">{% for failure in readiness.failures %}<div><strong>{{ failure.name }}</strong>: {{ failure.detail }}</div>{% endfor %}</div>{% endif %}{% else %}<div class="warning">{{ readiness.message }}</div>{% endif %}</section>\n{% set live=crypto.live_v2 %}'''
    text = replace_once(text, anchor, block, "forward evaluation readiness card")
    TEMPLATE.write_text(text, encoding="utf-8")


def main() -> None:
    patch_service()
    patch_template()
    print("Forward Evaluation Readiness dashboard patch complete.")


if __name__ == "__main__":
    main()
