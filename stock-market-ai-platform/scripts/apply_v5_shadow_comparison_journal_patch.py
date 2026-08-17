"""Apply the append-only V4 vs V5 vs SPY shadow comparison journal."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FILES = {
    ROOT / "webapp/services/v5_shadow_comparison_journal_service.py": '''"""Append-only V4 vs V5 vs SPY diagnostic comparison journal."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from webapp.services.v5_shadow_portfolio_service import get_v5_shadow_comparison

JOURNAL_DIR = Path("data/paper_trading/v5_shadow")
JOURNAL_PATH = JOURNAL_DIR / "comparison_journal.jsonl"


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _quote_fingerprint(positions):
    payload = [
        {
            "symbol": row.get("symbol"),
            "current_price": row.get("current_price"),
            "quote_timestamp": row.get("quote_timestamp"),
            "price_source": row.get("price_source"),
        }
        for row in sorted(positions, key=lambda x: str(x.get("symbol")))
    ]
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _read_last_observation():
    if not JOURNAL_PATH.exists():
        return None
    last = None
    for line in JOURNAL_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            last = json.loads(line)
        except json.JSONDecodeError:
            continue
    return last


def build_comparison_observation():
    c = get_v5_shadow_comparison()
    positions = list(c.get("positions") or [])
    top_five = c.get("top_five") or []
    if top_five and isinstance(top_five[0], dict):
        top_five_symbols = [str(row.get("symbol")) for row in top_five]
    else:
        top_five_symbols = [str(symbol) for symbol in top_five]

    return {
        "timestamp_utc": _utc_now(),
        "journal_type": "V4_V5_SPY_DIAGNOSTIC_COMPARISON",
        "comparison_scope": "NON_OFFICIAL_DIAGNOSTIC",
        "shadow_started_at_utc": c.get("created_at_utc"),
        "v5_decision_timestamp_utc": c.get("decision_timestamp_utc"),
        "official_v5_holdout_start_utc": c.get("holdout_start_utc"),
        "v5_shadow_equity": c.get("v5_shadow_equity"),
        "v5_shadow_pnl": c.get("v5_shadow_pnl"),
        "v5_shadow_return_pct": c.get("v5_shadow_return_pct"),
        "v4_current_equity": c.get("v4_current_equity"),
        "v4_baseline_equity": c.get("v4_baseline_equity"),
        "v4_normalized_equity": c.get("v4_normalized_equity"),
        "v4_since_shadow_return_pct": c.get("v4_since_shadow_return_pct"),
        "spy_normalized_equity": c.get("spy_normalized_equity"),
        "spy_since_shadow_return_pct": c.get("spy_since_shadow_return_pct"),
        "v5_vs_v4_pct_points": c.get("v5_vs_v4_pct_points"),
        "v5_vs_spy_pct_points": c.get("v5_vs_spy_pct_points"),
        "modeled_v5_entry_friction": c.get("entry_friction"),
        "v5_top_five": top_five_symbols,
        "positions": [
            {
                "symbol": row.get("symbol"),
                "current_price": row.get("current_price"),
                "market_value": row.get("market_value"),
                "net_pnl": row.get("net_pnl"),
                "price_source": row.get("price_source"),
                "quote_timestamp": row.get("quote_timestamp"),
            }
            for row in positions
        ],
        "quote_fingerprint": _quote_fingerprint(positions),
        "official_holdout_journal_written": False,
        "official_holdout_excluded": True,
        "brokerage_orders": False,
    }


def append_comparison_observation(skip_duplicate_quotes=True):
    observation = build_comparison_observation()
    last = _read_last_observation()
    if skip_duplicate_quotes and last and last.get("quote_fingerprint") == observation.get("quote_fingerprint"):
        return {
            "status": "skipped_duplicate_quotes",
            "journal_path": str(JOURNAL_PATH),
            "timestamp_utc": observation["timestamp_utc"],
        }

    JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
    with JOURNAL_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(observation, sort_keys=True) + "\\n")

    return {
        "status": "appended",
        "journal_path": str(JOURNAL_PATH),
        "timestamp_utc": observation["timestamp_utc"],
        "v5_shadow_equity": observation["v5_shadow_equity"],
        "v4_normalized_equity": observation["v4_normalized_equity"],
        "spy_normalized_equity": observation["spy_normalized_equity"],
        "v5_vs_v4_pct_points": observation["v5_vs_v4_pct_points"],
        "v5_vs_spy_pct_points": observation["v5_vs_spy_pct_points"],
    }
''',
    ROOT / "ml/run_v5_shadow_comparison_journal.py": '''"""Append one read-only V4 vs V5 vs SPY comparison observation."""

import json
from webapp.services.v5_shadow_comparison_journal_service import append_comparison_observation


def main():
    result = append_comparison_observation(skip_duplicate_quotes=True)
    print("V4 / V5 / SPY SHADOW COMPARISON JOURNAL")
    print("=" * 72)
    print(json.dumps(result, indent=2, sort_keys=True))
    print("Diagnostic only. Official Sep 1+ V5 holdout remains untouched.")
    print("No V4 state changes and no brokerage orders.")


if __name__ == "__main__":
    main()
''',
    ROOT / "scripts/install_v5_shadow_comparison_journal_launchagent.sh": '''#!/bin/zsh
set -euo pipefail
PROJECT_ROOT="${HOME}/Data-Shepherd-Engineering/stock-market-ai-platform"
PYTHON="${PROJECT_ROOT}/.venv/bin/python"
if [[ ! -x "${PYTHON}" ]]; then PYTHON="$(command -v python3)"; fi
LABEL="com.datashepherd.v5shadowcomparisonjournal"
PLIST="${HOME}/Library/LaunchAgents/${LABEL}.plist"
LOG_DIR="${HOME}/Library/Logs/DataShepherd"
STDOUT_LOG="${LOG_DIR}/v5shadowcomparisonjournal.out.log"
STDERR_LOG="${LOG_DIR}/v5shadowcomparisonjournal.err.log"
mkdir -p "${LOG_DIR}" "${HOME}/Library/LaunchAgents"
cd "${PROJECT_ROOT}"
"${PYTHON}" -m ml.run_v5_shadow_comparison_journal
cat > "${PLIST}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>${LABEL}</string>
<key>ProgramArguments</key><array><string>${PYTHON}</string><string>-m</string><string>ml.run_v5_shadow_comparison_journal</string></array>
<key>WorkingDirectory</key><string>${PROJECT_ROOT}</string>
<key>RunAtLoad</key><true/>
<key>StartInterval</key><integer>3600</integer>
<key>StandardOutPath</key><string>${STDOUT_LOG}</string>
<key>StandardErrorPath</key><string>${STDERR_LOG}</string>
</dict></plist>
EOF
plutil -lint "${PLIST}"
launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "${PLIST}"
launchctl kickstart -k "gui/$(id -u)/${LABEL}" || true
sleep 1
echo "===== V5 SHADOW COMPARISON JOURNAL ====="
launchctl print "gui/$(id -u)/${LABEL}" 2>/dev/null | grep -E 'state =|runs =|pid =|last exit code' || true
echo
echo "Journal: ${PROJECT_ROOT}/data/paper_trading/v5_shadow/comparison_journal.jsonl"
echo "Cadence: hourly; unchanged quote snapshots are skipped"
echo "Boundary: diagnostic only; official Sep 1+ V5 holdout journal is untouched"
''',
}

for path, content in FILES.items():
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"[APPLY] {path.relative_to(ROOT)}")

(ROOT / "scripts/install_v5_shadow_comparison_journal_launchagent.sh").chmod(0o755)
print()
print("V4/V5/SPY append-only comparison journal patch complete.")
print("Hourly snapshots are isolated from the official V5 holdout journal.")
print("Duplicate unchanged quote snapshots are skipped.")
print("No frozen models, V4 portfolio state, holdout evidence, or brokerage settings are changed.")
