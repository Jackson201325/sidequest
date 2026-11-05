"""Per-ticket plans, attachments and screenshot evidence, outside source repositories."""
import json
import os
import re
import subprocess
from pathlib import Path
from sidequest import config

WORKFLOW = Path(__file__).resolve().parents[1]
UI = re.compile(r"^app/(views|javascript|assets|components|frontend)/|"
                r"\.(erb|haml|slim|scss|sass|css|jsx?|tsx?|vue)$")


def tickets_dir():
    return Path(os.environ.get("SIDEQUEST_TICKETS_DIR") or config.get('workspace', 'plans_dir') or config.STATE_DIR / 'tickets').expanduser()


def ticket_dir(key):
    return tickets_dir() / key.upper()


def plan_path(key):
    return ticket_dir(key) / "plan.md"


def attachments_dir(key):
    return ticket_dir(key) / "attachments"


def qa_dir(key):
    return ticket_dir(key) / "qa"


def review_qa_dir(key):
    return ticket_dir(key) / "qa-review"


def ui_files(paths):
    return sorted(p for p in paths if UI.search(p) and not p.startswith(("spec/", "test/", "vendor/")))


def read_manifest(key):
    try:
        data = json.loads((qa_dir(key) / "manifest.json").read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("shots"), list) else None


def _git(cwd, *args):
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    return p.returncode, p.stdout


def status(key, changed_ui, cwd="."):
    """{status: not needed|missing|stale|current, ...} for this branch's UI files."""
    if not changed_ui:
        return {"status": "not needed", "screenshots": []}
    folder = qa_dir(key) if key else None
    manifest = read_manifest(key) if key else None
    shots = [str(folder / s["file"]) for s in (manifest or {}).get("shots", [])
             if s.get("status") == "ok" and s.get("file") and (folder / s["file"]).is_file()]
    if not shots:
        return {"status": "missing", "dir": str(folder) if folder else None, "screenshots": []}
    result = {"status": "current", "dir": str(folder), "screenshots": shots, "commit": manifest.get("commit")}
    commit = str(manifest.get("commit") or "")
    code, _ = _git(cwd, "merge-base", "--is-ancestor", commit, "HEAD") if re.fullmatch(r"[0-9a-f]{7,40}", commit) else (1, "")
    if code != 0:
        result.update(status="stale", reason="captured on a commit that is not in this branch")
        return result
    _, out = _git(cwd, "diff", "--name-only", commit, "HEAD")
    since = ui_files(out.split())
    _, dirty = _git(cwd, "status", "--porcelain", "--untracked-files=all")
    dirty_ui = ui_files(line[3:].split(" -> ")[-1] for line in dirty.splitlines() if len(line) > 3)
    if since or dirty_ui or manifest.get("dirty"):
        result.update(status="stale", changed_since=sorted(set(since) | set(dirty_ui)),
                      reason="UI changed after the capture" if since or dirty_ui else "captured with uncommitted changes")
    return result
