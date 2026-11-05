#!/usr/bin/env python3
"""sidequest-data worktree DEMO-### | BRANCH [--json]: where is this ticket's work? Local git only.

States: worktree (its own folder), main-checkout (the main checkout is on its branch),
branch-only (a local or origin branch exists, no worktree), none.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sidequest.worktrees import lookup
from sidequest import config


def git(*args):
    repo = os.environ.get("SIDEQUEST_REPO") or config.get("workspace", "repository") or "."
    p = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if p.returncode != 0:
        if "not a git repository" in p.stderr:
            raise SystemExit("sidequest-data: not a git repository (run inside a checkout, or set SIDEQUEST_REPO)")
        raise SystemExit("sidequest-data: git %s failed: %s" % (" ".join(args), p.stderr.strip()))
    return p.stdout


def main():
    parser = argparse.ArgumentParser(prog="sidequest-data worktree")
    parser.add_argument("target", help="ticket key (DEMO-123) or an exact branch name")
    parser.add_argument("--json", action="store_true")
    options = parser.parse_args()
    porcelain = git("worktree", "list", "--porcelain")
    names = git("for-each-ref", "--format=%(refname)", "refs/heads", "refs/remotes/origin").splitlines()
    branches = [n[11:] if n.startswith("refs/heads/") else n[20:] for n in names
                if n.startswith("refs/heads/") or n.startswith("refs/remotes/origin/")]
    found = lookup(options.target, porcelain, [b for b in branches if b != "HEAD"])
    if options.json:
        print(json.dumps(found, ensure_ascii=False))
        return 0
    print("%s: %s" % (options.target.upper() if options.target.upper().startswith(("DEMO-", "OPS-")) else options.target, found["state"]))
    for field in ("path", "branch"):
        if field in found:
            print(field.upper() + " " + found[field])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
