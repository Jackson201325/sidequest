"""Find the checkout that holds a ticket's work, from `git worktree list --porcelain` and branch names."""
import re

KEY = re.compile(r"[A-Z][A-Z0-9_]*-[0-9]+", re.I)


def parse_worktrees(porcelain):
    """[(path, branch or None)]; the first entry is the main checkout."""
    entries, path, branch = [], None, None
    for line in porcelain.splitlines() + [""]:
        if line.startswith("worktree "):
            path, branch = line[9:], None
        elif line.startswith("branch refs/heads/"):
            branch = line[18:]
        elif not line and path is not None:
            entries.append((path, branch))
            path = None
    return entries


def matcher(target):
    """Branch predicate: a ticket key matches `prefix/KEY` or `prefix/KEY-slug` (so DEMO-6 skips DEMO-61); anything else is an exact branch name."""
    if KEY.fullmatch(target):
        pattern = re.compile(r"(?:^|/)" + re.escape(target.upper()) + r"(?:-|$)")
        return lambda branch: not branch.startswith("backup/") and bool(pattern.search(branch))
    return lambda branch: branch == target


def lookup(target, porcelain, branches):
    """State of the work: worktree, main-checkout, branch-only or none. `branches` are local and remote-tracking names without `origin/`."""
    matches = matcher(target)
    entries = parse_worktrees(porcelain)
    for index, (path, branch) in enumerate(entries):
        if branch and matches(branch):
            return {"state": "main-checkout" if index == 0 else "worktree", "path": path, "branch": branch}
    for branch in sorted(set(branches)):
        if matches(branch):
            return {"state": "branch-only", "branch": branch}
    return {"state": "none"}
