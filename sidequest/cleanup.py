"""Remove worktrees whose PR merged, only when nothing can be lost.

A worktree (never the main checkout) on a merged PR's branch is removed only when: you are not in it,
busy(path) gives no reason (app booked, agent working), it has no uncommitted or untracked changes,
the merged head commit is here and holds every commit of the branch, you agreed (confirm), and
GitHub, asked now, still reports the PR merged with that head. Then its window closes, the worktree
is removed without --force, and its local branch is deleted.
"""
from pathlib import Path
import subprocess

from sidequest.ticket_keys import branch_keys
from sidequest.worktrees import parse_worktrees


def _git(path, *args):
    return subprocess.run(['git', '-C', str(path), *args], capture_output=True, text=True)


def _row(kind, name, text):
    return kind.ljust(8) + ' ' + name.ljust(8) + ' ' + text


def window_name(branch):
    keys = branch_keys(branch)
    return keys[0] if keys else branch.replace('/', '-')


def clean(repository, merged_prs, cwd, busy, live_pr, confirm, close_window, dry_run=False):
    """(lines, problems). merged_prs: [{number, branch, head_oid}], newest first."""
    merged = {}
    for pr in merged_prs:
        merged.setdefault(pr.get('branch'), pr)
    listed = _git(repository, 'worktree', 'list', '--porcelain').stdout
    here = str(Path(cwd).resolve()) if cwd else ''
    lines, problems = [], 0
    for path, branch in parse_worktrees(listed)[1:]:
        pr = merged.get(branch)
        if not branch or not pr:
            continue
        name, number, head = window_name(branch), pr.get('number'), pr.get('head_oid') or ''
        merged_text = 'PR #' + str(number) + ' merged'

        def keep(reason):
            lines.append(_row('kept', name, merged_text + ', but ' + reason))

        root = str(Path(path).resolve())
        if here == root or here.startswith(root + '/'):
            keep('you are in it')
            continue
        reason = busy(path)
        if reason:
            keep(reason)
            continue
        if _git(path, 'status', '--porcelain', '--untracked-files=all').stdout.strip():
            keep('it has uncommitted or untracked changes')
            continue
        if not head or _git(repository, 'cat-file', '-e', head + '^{commit}').returncode:
            keep('its head commit is not fetched here')
            continue
        if _git(repository, 'merge-base', '--is-ancestor', 'refs/heads/' + branch, head).returncode:
            keep(branch + " has commits that weren't in it")
            continue
        if dry_run:
            lines.append(_row('would', name, 'remove (' + merged_text + ')'))
            continue
        if not confirm({'name': name, 'path': path, 'branch': branch, 'number': number}):
            lines.append(_row('kept', name, merged_text + '; you chose to keep it'))
            continue
        state = live_pr(number)
        if state is None:
            keep('GitHub could not be asked about PR #' + str(number))
            continue
        if state.get('state') != 'MERGED':
            keep('GitHub no longer reports PR #' + str(number) + ' as merged')
            continue
        if state.get('head_oid') != head:
            keep('its head on GitHub is not the merged head we know')
            continue
        close_window(name)
        removed = _git(repository, 'worktree', 'remove', path)
        if removed.returncode:
            problems += 1
            detail = [line for line in removed.stderr.splitlines() if line.strip()]
            lines.append(_row('failed', name, 'git worktree remove: ' + (detail[-1] if detail else 'failed')))
            continue
        _git(repository, 'branch', '-D', branch)
        lines.append(_row('removed', name, merged_text + '; worktree and local branch removed'))
    return lines, problems
