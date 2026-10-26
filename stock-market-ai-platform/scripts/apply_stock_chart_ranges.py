"""Apply the stock chart UI changes while preserving unrelated VM edits."""
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
import os
import shutil
import subprocess
import tempfile

BASE = "f544504e9a8de1b69993ec79df71756e1b25c926"
HEAD = "3c641641e676b9bc25edb934a9a6b4f9b5b4c7c0"
FILES = (
    "v8_stream_health_visual.js",
    "v10_cycle3_accelerated_v2_dashboard.js",
    "model_research_tabs.js",
    "v4_equity_chart.js",
)
root = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip())
prepared = []
for name in FILES:
    relative = "stock-market-ai-platform/webapp/static/js/" + name
    path = root / relative
    before = subprocess.check_output(["git", "show", BASE + ":" + relative], text=True)
    after = subprocess.check_output(["git", "show", HEAD + ":" + relative], text=True)
    original = path.read_text()
    merged = original
    a, b = before.splitlines(True), after.splitlines(True)
    for tag, i, j, k, l in reversed(SequenceMatcher(None, a, b, autojunk=False).get_opcodes()):
        if tag == "equal":
            continue
        old, new = "".join(a[i:j]), "".join(b[k:l])
        if not old:
            anchor = a[i] if i < len(a) else None
            if not anchor or merged.count(anchor) != 1:
                raise SystemExit("Ambiguous insertion in " + name + "; no files written.")
            merged = merged.replace(anchor, new + anchor, 1)
        else:
            if merged.count(old) != 1:
                raise SystemExit("Unexpected or already updated source in " + name + "; no files written.")
            merged = merged.replace(old, new, 1)
    prepared.append((path, original, merged))
with tempfile.TemporaryDirectory(prefix="stock-ui-check-") as directory:
    if shutil.which("node"):
        for path, _, merged in prepared:
            check = Path(directory) / path.name
            check.write_text(merged)
            subprocess.run(["node", "--check", str(check)], check=True)
backup = Path.home() / "dse-operations-backups" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
backup.mkdir(parents=True, exist_ok=True)
for path, original, merged in prepared:
    (backup / path.name).write_text(original)
    temporary = path.with_name(path.name + ".replacement")
    temporary.write_text(merged)
    temporary.chmod(path.stat().st_mode & 0o777)
    os.replace(temporary, path)
print("Applied four UI updates. Backup:", backup)
