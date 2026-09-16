"""Guarded, resumable execution of dry-run-approved GDELT discovery queries."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

import pandas as pd

DEFAULT_SQL_ROOT = Path("data/research/news/gdelt/sql")
DEFAULT_ESTIMATES = Path("data/research/news/gdelt/dry_run_estimates.csv")
DEFAULT_RAW_ROOT = Path("data/research/news/gdelt/raw")
DEFAULT_MAX_TOTAL_BYTES = int(0.80 * 1024 ** 4)
BILLING_INCREMENT_BYTES = 1024 ** 2
REQUIRED_EXPORT_COLUMNS = {
    "DATE", "SourceCommonName", "DocumentIdentifier", "V2Organizations", "V2Tone", "asset_ids"
}


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_csv(path):
    frame = pd.read_csv(path)
    missing = sorted(REQUIRED_EXPORT_COLUMNS - set(frame.columns))
    if missing:
        raise ValueError(f"{Path(path).name} missing columns: " + ", ".join(missing))
    if frame.empty:
        return 0
    parsed = frame["asset_ids"].map(json.loads)
    if parsed.map(lambda value: not isinstance(value, list) or not value).any():
        raise ValueError(f"{Path(path).name} contains invalid asset_ids")
    return int(len(frame))


def load_approved_plan(sql_root=DEFAULT_SQL_ROOT, estimates_path=DEFAULT_ESTIMATES,
                       max_total_bytes=DEFAULT_MAX_TOTAL_BYTES):
    sql_root, estimates_path = Path(sql_root), Path(estimates_path)
    estimates = pd.read_csv(estimates_path)
    required = {"query_file", "estimated_bytes"}
    if not required.issubset(estimates.columns):
        raise ValueError("Dry-run estimates are missing required columns")
    if estimates["query_file"].duplicated().any() or (estimates["estimated_bytes"] <= 0).any():
        raise ValueError("Dry-run estimates contain duplicate queries or invalid bytes")
    estimates["billing_cap_bytes"] = (
        ((estimates["estimated_bytes"].astype(int) + BILLING_INCREMENT_BYTES - 1)
         // BILLING_INCREMENT_BYTES) * BILLING_INCREMENT_BYTES)
    total = int(estimates["billing_cap_bytes"].sum())
    if total > int(max_total_bytes):
        raise ValueError(f"Estimated {total} bytes exceeds safety budget {int(max_total_bytes)}")
    rows = []
    for item in estimates.sort_values("query_file").itertuples(index=False):
        sql_path = sql_root / item.query_file
        if not sql_path.exists():
            raise FileNotFoundError(sql_path)
        rows.append({"query_file": item.query_file, "sql_path": sql_path,
                     "estimated_bytes": int(item.estimated_bytes),
                     "billing_cap_bytes": int(item.billing_cap_bytes),
                     "sql_sha256": _sha256(sql_path)})
    return rows, total


def execute(project_id, sql_root=DEFAULT_SQL_ROOT, estimates_path=DEFAULT_ESTIMATES,
            raw_root=DEFAULT_RAW_ROOT, max_total_bytes=DEFAULT_MAX_TOTAL_BYTES,
            runner=subprocess.run, progress=print):
    plan, total = load_approved_plan(sql_root, estimates_path, max_total_bytes)
    raw_root = Path(raw_root)
    raw_root.mkdir(parents=True, exist_ok=True)
    completed, skipped, total_rows, outputs = 0, 0, 0, []
    for number, item in enumerate(plan, start=1):
        output_path = raw_root / item["query_file"].replace(".sql", ".csv")
        if output_path.exists():
            rows = _validate_csv(output_path)
            skipped += 1
            total_rows += rows
            outputs.append({**item, "output": str(output_path), "rows": rows,
                            "output_sha256": _sha256(output_path), "status": "reused"})
            progress(f"[{number}/{len(plan)}] {output_path.name}: reused ({rows:,} rows)")
            continue
        progress(f"[{number}/{len(plan)}] {output_path.name}: executing guarded query")
        command = ["bq", "query", f"--project_id={project_id}", "--use_legacy_sql=false",
                   "--format=csv", "--max_rows=10000000",
                   f"--maximum_bytes_billed={item['billing_cap_bytes']}"]
        result = runner(command, input=item["sql_path"].read_text(encoding="utf-8"),
                        text=True, capture_output=True, check=False)
        if result.returncode:
            details = "\n".join(part.strip() for part in (result.stdout, result.stderr)
                                if part and part.strip())
            raise RuntimeError(
                f"Extraction failed for {item['query_file']} "
                f"(bq exit {result.returncode}): {details or 'no diagnostic output'}")
        part_path = output_path.with_suffix(".csv.part")
        part_path.write_text(result.stdout, encoding="utf-8")
        rows = _validate_csv(part_path)
        part_path.replace(output_path)
        completed += 1
        total_rows += rows
        outputs.append({**item, "output": str(output_path), "rows": rows,
                        "output_sha256": _sha256(output_path), "status": "downloaded"})
        progress(f"[{number}/{len(plan)}] {output_path.name}: saved ({rows:,} rows)")
    manifest = {
        "stage": "gdelt_guarded_monthly_extraction",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "project_id": project_id, "approved_estimated_bytes": total,
        "safety_budget_bytes": int(max_total_bytes), "query_count": len(plan),
        "downloaded_queries": completed, "reused_queries": skipped,
        "total_rows": total_rows, "outputs": outputs,
        "safety": {"per_query_maximum_bytes_billed": True, "resumable": True,
                   "brokerage_orders": False, "model_artifacts_modified": False},
    }
    manifest_path = raw_root.parent / "extraction_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--sql-root", type=Path, default=DEFAULT_SQL_ROOT)
    parser.add_argument("--estimates", type=Path, default=DEFAULT_ESTIMATES)
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument("--max-total-bytes", type=int, default=DEFAULT_MAX_TOTAL_BYTES)
    parser.add_argument("--execute", action="store_true",
                        help="Required acknowledgement that guarded BigQuery jobs may run")
    args = parser.parse_args(argv)
    if not args.execute:
        raise SystemExit("Refusing to run without explicit --execute")
    manifest = execute(args.project_id, args.sql_root, args.estimates,
                       args.raw_root, args.max_total_bytes)
    print(json.dumps({key: manifest[key] for key in (
        "stage", "approved_estimated_bytes", "safety_budget_bytes", "query_count",
        "downloaded_queries", "reused_queries", "total_rows", "safety")}, indent=2))


if __name__ == "__main__":
    main()
