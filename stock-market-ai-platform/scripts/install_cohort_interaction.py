"""Install V10/V14 cohort charts, preserving unrelated dashboard and service edits."""
import ast
from datetime import datetime, timezone
from difflib import SequenceMatcher
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

BASE = "c7638524a5920c85390fd3d7c46fe31763f60022"
HEAD = "9f8dcb72567af5ad1ad157635fe96272468b7b7c"
PREFIX = "stock-market-ai-platform/"
MODIFIED = (
    "webapp/services/v10_cycle3_accelerated_v2_service.py",
    "webapp/services/v14_ml_ai_service.py",
    "webapp/static/js/v10_cycle3_accelerated_v2_dashboard.js",
    "webapp/static/js/v14_ml_ai_dashboard.js",
)
NEW = ("webapp/services/cohort_interaction_projection.py", "webapp/static/js/stock_cohort_interaction.js")


def merge(current, before, after):
    a, b = before.splitlines(True), after.splitlines(True)
    for tag, i, j, k, l in reversed(SequenceMatcher(None, a, b, autojunk=False).get_opcodes()):
        if tag == "equal":
            continue
        old, new = "".join(a[i:j]), "".join(b[k:l])
        if old:
            if current.count(old) != 1:
                raise ValueError("Unexpected source; stopped before writing files.")
            current = current.replace(old, new, 1)
        else:
            for width in range(1, 41):
                anchor = "".join(a[i:i+width])
                if anchor and current.count(anchor) == 1:
                    current = current.replace(anchor, new + anchor, 1)
                    break
            else:
                raise ValueError("Ambiguous source; stopped before writing files.")
    return current


def main():
    if os.uname().nodename != "datashepherdengineeringvnic":
        raise SystemExit("Run on the Ubuntu VM.")
    root = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip())
    def source(ref, relative):
        return subprocess.check_output(["git", "show", ref + ":" + PREFIX + relative], text=True)
    prepared = []
    for relative in MODIFIED:
        path = root / PREFIX / relative
        current = path.read_text()
        marker = "function publishCohortInteraction" if path.suffix == ".js" else '"cohort_event_history": project_cohort_events(events)'
        updated = current if marker in current else merge(current, source(BASE, relative), source(HEAD, relative))
        prepared.append((path, updated))
    for relative in NEW:
        path = root / PREFIX / relative
        updated = source(HEAD, relative)
        if path.exists() and path.read_text() != updated:
            raise SystemExit("Existing cohort component differs; no files written: " + str(path))
        prepared.append((path, updated))
    with tempfile.TemporaryDirectory(prefix="cohort-ui-check-") as directory:
        for path, text in prepared:
            if path.suffix == ".py":
                ast.parse(text)
            elif shutil.which("node"):
                check = Path(directory) / path.name
                check.write_text(text)
                subprocess.run(["node", "--check", str(check)], check=True)
    backup = Path.home() / "dse-operations-backups" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup.mkdir(parents=True, exist_ok=True)
    for path, text in prepared:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            shutil.copy2(path, backup / path.name)
        temporary = path.with_name(path.name + ".replacement")
        temporary.write_text(text)
        temporary.chmod(path.stat().st_mode & 0o777 if path.exists() else 0o644)
        os.replace(temporary, path)
    print("Installed V10/V14 cohort charts. Backup:", backup, flush=True)
    subprocess.run(["sudo", "systemctl", "restart", "datashepherd-web.service"], check=True)
    print("Web restart completed. Hard-refresh the dashboard.", flush=True)


if __name__ == "__main__":
    main()
