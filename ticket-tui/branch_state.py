"""Local branch state per worktree: unpushed and uncommitted work, distance from the base, QA evidence.

Local git only, no remote calls. "behind main" uses the last fetched base ref (workspace.base_ref).
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sidequest import config, qa  # noqa: E402


def _git(path, *args):
    p = subprocess.run(["git", *args], cwd=path, capture_output=True, text=True, timeout=20)
    return p.returncode, p.stdout


def _count(path, spec):
    code, out = _git(path, "rev-list", "--count", spec)
    return int(out.strip()) if code == 0 and out.strip().isdigit() else None


def branch_state(path, key, base=None):
    base = base or config.base_ref()
    if not Path(path).is_dir():
        return {"error": "worktree folder not found"}
    try:
        code, dirty = _git(path, "status", "--porcelain", "--untracked-files=all")
        if code != 0:
            return {"error": "not a git worktree"}
        upstream = _git(path, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")[0] == 0
        unpushed = _count(path, "@{upstream}..HEAD" if upstream else base + "..HEAD")
        behind = _count(path, "HEAD.." + base)
        _, changed = _git(path, "diff", "--name-only", base + "...HEAD")
        dirty_paths = [line[3:].split(" -> ")[-1] for line in dirty.splitlines() if len(line) > 3]
        ui = qa.ui_files(set(changed.split()) | set(dirty_paths))
        evidence = qa.status(key, ui, cwd=path)
    except (OSError, subprocess.SubprocessError):
        return {"error": "git failed"}
    return {"uncommitted": len(dirty_paths), "unpushed": unpushed, "upstream": upstream, "behind": behind,
            "ui_files": ui, "qa": evidence["status"], "qa_reason": evidence.get("reason", "")}


def collect(worktrees):
    """{key: state} for {key: path}. Runs in a background thread."""
    return {key: branch_state(path, key) for key, path in worktrees.items() if path}


def summary(state):
    if not state or state.get("error"):
        return "Local state unavailable"
    parts = []
    if state.get("unpushed"):
        n = state["unpushed"]
        parts.append(f"{n} commit{'s' if n != 1 else ''} " + ("unpushed" if state.get("upstream") else "not pushed"))
    if state.get("uncommitted"):
        parts.append(f"{state['uncommitted']} uncommitted")
    if state.get("behind"):
        parts.append(f"{state['behind']} behind main")
    if state.get("qa") in ("missing", "stale", "current"):
        parts.append(f"QA shots {state['qa']}")
    if not parts:
        return "Local clean · up to date with main"
    return "Local " + " · ".join(parts)


def qa_hint(ticket, state):
    """A next step for my own tickets whose UI changes lack current QA screenshots."""
    if not state or ticket.lane != "Needs me" or state.get("qa") not in ("missing", "stale"):
        return ""
    return f"QA shots {state['qa']}: Space s → QA locally"
