"""Run git for the personal helpers."""

import subprocess


def git(*args, check=True, tool="sidequest-data"):
    p = subprocess.run(["git"] + list(args), capture_output=True, text=True)
    if check and p.returncode != 0:
        raise SystemExit("%s: git %s failed: %s" % (tool, " ".join(args), p.stderr.strip()))
    return p.stdout


def base_remote(base, remotes):
    """The remote to fetch for a base ref: its first part when that names a remote, else origin."""
    first = base.split("/", 1)[0]
    return first if "/" in base and first in remotes else "origin"
