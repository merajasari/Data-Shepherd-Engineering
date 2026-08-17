#!/usr/bin/env python3
"""Apply the Shared Crypto V2 forward-journal dtype hardening fix.

Pandas may infer an all-empty ``realized_through_utc`` CSV column as float64.
Forward realization later writes an ISO-8601 string into that column, which is
rejected by current pandas versions.  Force that journal column to object dtype
on read so the persisted CSV schema can safely transition pending rows to
realized rows without changing the frozen model or execution policy.
"""
from pathlib import Path

PATH = Path("ml/crypto_15m_v2/forward_service.py")
OLD = '''def _read_journal() -> pd.DataFrame:\n    df = pd.read_csv(JOURNAL_PATH)\n    if len(df):\n        df["decision_timestamp_utc"] = pd.to_datetime(df["decision_timestamp_utc"], utc=True)\n    return df\n'''
NEW = '''def _read_journal() -> pd.DataFrame:\n    df = pd.read_csv(JOURNAL_PATH)\n    # An all-empty CSV column is otherwise inferred as float64 by pandas.\n    # Realization writes an ISO-8601 timestamp here, so keep it string-capable.\n    if "realized_through_utc" in df.columns:\n        df["realized_through_utc"] = df["realized_through_utc"].astype("object")\n    if len(df):\n        df["decision_timestamp_utc"] = pd.to_datetime(df["decision_timestamp_utc"], utc=True)\n    return df\n'''

text = PATH.read_text(encoding="utf-8")
if NEW in text:
    print("[SKIP] Shared V2 journal dtype fix already applied")
elif OLD not in text:
    raise SystemExit("Expected _read_journal block not found; refusing unsafe patch")
else:
    PATH.write_text(text.replace(OLD, NEW, 1), encoding="utf-8")
    print(f"[APPLY] Shared V2 journal dtype fix: {PATH}")
