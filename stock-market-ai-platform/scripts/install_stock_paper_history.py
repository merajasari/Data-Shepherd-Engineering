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
HEAD = "60c876bf903a42e4be26d7e041fb44bef94eb343"
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
        prepared.append((path, merge(path.read_text(), source(BASE, relative), source(HEAD, relative), name)))
    for relative in NEW:
        path = root / PREFIX / relative
        if path.exists():
            raise SystemExit("New file already exists; stopped before writes: " + str(path))
        text = source(HEAD, relative)
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
