"""Install observed-equity history without overwriting unrelated dashboard edits."""
import ast
from datetime import datetime, timezone
from difflib import SequenceMatcher
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

BASE = "27c49fffa94b42fd34d96203adec7d6f125005a2"
HEAD = "16945ddcc65942208fdf1544eb131fd582151c25"
INDIVIDUAL_BASE = "2262ce9d69f5411e9d12d4e81877d70c546a6ff7"
AXIS_BASE = "4b74679e77ea6861d887ad4cfcb8892e81e93506"
HOVER_BASE = "9362c37cc2f545f0b1019ea2b7ff2a445c9120a4"
HISTORY_BASE = "60c876bf903a42e4be26d7e041fb44bef94eb343"
PREFIX = "stock-market-ai-platform/"
JS = ("v8_stream_health_visual.js", "v10_cycle3_accelerated_v2_dashboard.js")
NEW = ("scripts/record_stock_paper_equity.py",
       "deploy/systemd/datashepherd-paper-equity-history.service",
       "deploy/systemd/datashepherd-paper-equity-history.timer")


def merge(original, before, after, name):
    a, b = before.splitlines(True), after.splitlines(True)
    result = original
    for tag, i, j, k, l in reversed(SequenceMatcher(None, a, b, autojunk=False).get_opcodes()):
        if tag == "equal":
            continue
        old, new = "".join(a[i:j]), "".join(b[k:l])
        if not old:
            for width in range(1, 41):
                anchor = "".join(a[i:i+width])
                if anchor and result.count(anchor) == 1:
                    result = result.replace(anchor, new + anchor, 1)
                    break
            else:
                raise ValueError("Ambiguous insertion in " + name)
        else:
            if result.count(old) != 1:
                raise ValueError("Unexpected or already modified source in " + name)
            result = result.replace(old, new, 1)
    return result


def main():
    if os.uname().nodename != "datashepherdengineeringvnic":
        raise SystemExit("Run on the Ubuntu VM.")
    root = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip())
    def source(ref, path):
        return subprocess.check_output(["git", "show", ref + ":" + PREFIX + path], text=True)
    prepared = []
    for name in JS:
        relative = "webapp/static/js/" + name
        path = root / PREFIX / relative
        current = path.read_text()
        if "function pickPaperSeries" in current and (name.startswith("v8") or "function pointsWithBoundaryContext" in current):
            prepared.append((path, current))
            continue
        base_ref = (INDIVIDUAL_BASE if "function pickPaperSeries" in current
                    else AXIS_BASE if "paper-performance-tooltip-style" in current and "minX+60000" in current
                    else HOVER_BASE if "paper-performance-tooltip-style" in current
                    else HISTORY_BASE if "loadPaperHistory" in current else BASE)
        before, after = source(base_ref, relative), source(HEAD, relative)
        if name.startswith("v8"):
            # This entire handler is intentionally replaced; keep unrelated layout edits.
            start = "    chartStage.onpointermove=event=>{"
            end = "    if(window.ResizeObserver)"
            if current.count(start) != 1 or current.count(end) != 1:
                raise SystemExit("Unexpected V8 hover structure; no files written.")
            a, b = current.index(start), current.index(end)
            x, y = before.index(start), before.index(end)
            current = current[:a] + before[x:y] + current[b:]
        prepared.append((path, merge(current, before, after, name)))
    for relative in NEW:
        path = root / PREFIX / relative
        text = source(HEAD, relative)
        if path.exists() and path.read_text() != text:
            raise SystemExit("Existing recorder file differs; stopped before writes: " + str(path))
        if relative.endswith(".py"):
            ast.parse(text)
        prepared.append((path, text))
    with tempfile.TemporaryDirectory(prefix="paper-history-check-") as directory:
        if shutil.which("node"):
            for path, text in prepared:
                if path.suffix == ".js":
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
    for suffix in ("service", "timer"):
        name = "datashepherd-paper-equity-history." + suffix
        target = Path("/etc/systemd/system") / name
        if target.exists():
            subprocess.run(["sudo", "cp", str(target), str(backup / name)], check=True)
        source_path = root / PREFIX / "deploy/systemd" / name
        subprocess.run(["sudo", "install", "-m", "0644", str(source_path), str(target)], check=True)
    subprocess.run(["sudo", "systemctl", "daemon-reload"], check=True)
    subprocess.run(["sudo", "systemctl", "enable", "--now", "datashepherd-paper-equity-history.timer"], check=True)
    print("Installed. Backup:", backup, flush=True)
    subprocess.run(["sudo", "systemctl", "start", "datashepherd-paper-equity-history.service"], check=True)
    subprocess.run(["systemctl", "list-timers", "--no-pager", "--full", "datashepherd-paper-equity-history.timer"], check=True)
    subprocess.run(["sudo", "journalctl", "-u", "datashepherd-paper-equity-history.service", "-n", "10", "--no-pager"], check=True)


if __name__ == "__main__":
    main()
