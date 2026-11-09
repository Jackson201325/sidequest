"""Keep worktree branches current after a fetch, never pushing and never leaving a half-done merge.

For each worktree: a branch takes new commits from its own origin branch (fast-forward only); a
branch never pushed is rebased onto the base; a pushed branch behind the base is listed, or gets
the base merged in when asked. Local main follows origin/main when no worktree has it. A worktree is
skipped when a merge/rebase is in progress, when `busy(path)` gives a reason (app booked, agent
working), or when its branch diverged from its origin branch. Uncommitted work is autostashed; a
failed rebase or merge is aborted so the worktree is left as it was.
"""
from pathlib import Path
import subprocess

from sidequest.ticket_keys import branch_keys
from sidequest.worktrees import parse_worktrees

IN_PROGRESS = ('MERGE_HEAD', 'REBASE_HEAD', 'CHERRY_PICK_HEAD', 'rebase-merge', 'rebase-apply')
AUTOSTASH_CONFLICT = 'autostash resulted in conflicts'


def _git(path, *args):
    return subprocess.run(['git', '-C', str(path), *args], capture_output=True, text=True)


def _out(path, *args):
    result = _git(path, *args)
    return result.stdout.strip() if result.returncode == 0 else ''


def _name(branch, index):
    keys = branch_keys(branch)
    name = keys[0] if keys else branch.replace('/', '-')
    return 'Main (' + name + ')' if index == 0 and branch != 'main' else name


def _row(kind, name, text):
    return kind.ljust(8) + ' ' + name.ljust(8) + ' ' + text


def _failure(output):
    files = [line.rsplit(' in ', 1)[1] for line in output.splitlines() if line.startswith('CONFLICT') and ' in ' in line]
    lines = [line for line in output.splitlines() if line.strip()]
    return 'conflicts in ' + ', '.join(files) if files else (lines[-1] if lines else 'git failed')


def _in_progress(path):
    for name in IN_PROGRESS:
        found = _out(path, 'rev-parse', '--git-path', name)
        if found and (Path(path) / found if not Path(found).is_absolute() else Path(found)).exists():
            return True
    return False


def update_all(repository, base='origin/main', merge_base=False, busy=None, dry_run=False):
    """(lines, problems): one line per change, skip or failure; problems counts what needs attention."""
    busy = busy or (lambda path: '')
    base_branch = base.split('/', 1)[1] if base.startswith('origin/') else base
    worktrees = parse_worktrees(_out(repository, 'worktree', 'list', '--porcelain'))
    lines, problems, behind_base = [], 0, []

    # Local main when no worktree has it: fast-forward the ref atomically, never over its own commits.
    if base_branch not in [branch for _, branch in worktrees]:
        old = _out(repository, 'rev-parse', '-q', '--verify', 'refs/heads/' + base_branch)
        behind = int(_out(repository, 'rev-list', '--count', base_branch + '..' + base) or 0) if old else 0
        if behind:
            if _git(repository, 'merge-base', '--is-ancestor', base_branch, base).returncode != 0:
                lines.append(_row('skipped', base_branch, "local " + base_branch + " has commits that aren't on " + base))
            elif dry_run:
                lines.append(_row('would', base_branch, 'fast-forward to ' + base + ' (+' + str(behind) + ')'))
            elif _git(repository, 'update-ref', '-m', 'sidequest up: fast-forward to ' + base,
                      'refs/heads/' + base_branch, 'refs/remotes/' + base, old).returncode == 0:
                lines.append(_row('updated', base_branch, 'fast-forwarded to ' + base + ' (+' + str(behind) + ')'))

    for index, (path, branch) in enumerate(worktrees):
        if not branch:
            continue
        name = _name(branch, index)
        reason = 'a merge/rebase is in progress' if _in_progress(path) else busy(str(path))
        if reason:
            lines.append(_row('skipped', name, reason))
            continue

        # a. the branch's own origin branch has new commits
        upstream = _out(path, 'rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}')
        if branch == base_branch:
            upstream = upstream or base
        elif upstream == base:
            upstream = ''  # tracking the base is not the branch's own origin branch; step b handles the base
        if upstream:
            counts = (_out(path, 'rev-list', '--left-right', '--count', upstream + '...HEAD') or '0 0').split()
            behind, ahead = int(counts[0]), int(counts[1])
            if behind and ahead:
                problems += 1
                lines.append(_row('skipped', name, 'diverged from ' + upstream + ' (' + str(ahead) + ' local / ' +
                                  str(behind) + ' remote commits): not touched, sort it out by hand'))
                continue
            if behind and dry_run:
                lines.append(_row('would', name, 'pull ' + str(behind) + ' from ' + upstream))
            elif behind:
                ran = _git(path, 'merge', '--ff-only', '--autostash', upstream)
                if ran.returncode:
                    problems += 1
                    lines.append(_row('failed', name, 'could not fast-forward to ' + upstream + ': ' + _failure(ran.stderr + ran.stdout)))
                    continue
                lines.append(_row('updated', name, 'pulled ' + str(behind) + ' from ' + upstream))
                if AUTOSTASH_CONFLICT in ran.stdout + ran.stderr:
                    lines.append(_row('note', name, "your uncommitted changes conflicted; they're safe in git stash"))

        # b. the base moved on
        behind = int(_out(path, 'rev-list', '--count', 'HEAD..' + base) or 0)
        if not behind or branch == base_branch:
            continue
        pushed = bool(upstream or _out(path, 'rev-parse', '-q', '--verify', 'refs/remotes/origin/' + branch))
        if not pushed:
            if dry_run:
                lines.append(_row('would', name, 'rebase onto ' + base + ' (+' + str(behind) + ')'))
                continue
            ran = _git(path, 'rebase', '--autostash', base)
            if ran.returncode:
                _git(path, 'rebase', '--abort')
                problems += 1
                lines.append(_row('failed', name, 'rebase onto ' + base + ' failed (' + _failure(ran.stdout + ran.stderr) +
                                  '); aborted, left as it was'))
                continue
            lines.append(_row('rebased', name, 'onto ' + base + ' (+' + str(behind) + '; not pushed yet)'))
        elif merge_base:
            if dry_run:
                lines.append(_row('would', name, 'merge ' + base + ' (+' + str(behind) + ')'))
                continue
            ran = _git(path, 'merge', '--no-edit', '--autostash', base)
            if ran.returncode:
                _git(path, 'merge', '--abort')
                problems += 1
                lines.append(_row('failed', name, 'merging ' + base + ' failed (' + _failure(ran.stdout + ran.stderr) +
                                  '); aborted, left as it was'))
                continue
            lines.append(_row('merged', name, base + ' (+' + str(behind) + '); not pushed: git push when ready'))
        else:
            behind_base.append(name + ' (' + str(behind) + ')')
            continue
        if AUTOSTASH_CONFLICT in ran.stdout + ran.stderr:
            lines.append(_row('note', name, "your uncommitted changes conflicted; they're safe in git stash"))
    for item in behind_base:
        lines.append('behind   ' + item + '; sidequest up --update merges ' + base + ' in')
    return lines, problems
