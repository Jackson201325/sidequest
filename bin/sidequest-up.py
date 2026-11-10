#!/usr/bin/env python3
"""sidequest up [-n] [-u] [-r] [--all] [--dry-run]: prepare this project's worktrees from Jira and GitHub.

Collects the sync data (tickets by sync.tickets_jql, your open PRs, merged PRs) and fetches origin,
then creates a worktree for each sync ticket and each of your open PRs that has none: an existing
branch is reused (local, then origin), a new one is fix/ for a Bug and feature/ otherwise, and
workspace.copy_files are copied in. Tickets with a merged PR are skipped. Then the tmux session
(workspace.tmux_session; with workspace.terminal herdr, a Herdr workspace of that name with one tab per
window) gets one window per worktree, in the order the tickets were assigned to you,
plus workspace.windows; windows are reused and moved, never closed. workspace.on_up commands run
last, and the session is attached (or switched to inside tmux). Nothing is removed or pushed. --dry-run prints the plan and changes no Git state or windows; --offline uses the last
collected data and does not fetch (-n). -r closes the tmux session first, which stops what runs in
its windows, and builds it again. After a successful fetch, branches are updated: each takes new
commits from its own origin branch (fast-forward), main follows origin/main, a branch never pushed is
rebased onto the base, and a pushed branch behind the base is listed (--update merges the base in).
A worktree is skipped while a merge/rebase is in progress, the app is booked for it, an agent works
in it, or its branch diverged; a failed rebase or merge is aborted. Nothing is ever pushed.
First, worktrees whose PR merged are removed (sync.cleanup: ask asks per worktree in a terminal,
on removes, off skips; --cleanup considers them when off, --yes answers yes) only when you are not
in it, nothing is booked or running there, it has no uncommitted or untracked changes, every commit
is in the merged head, and GitHub, asked at that moment, still reports the PR merged with that head.
--when-due syncs only when the last sync is older than sync.every_minutes; before that it attaches to
the open session, or builds it without network. --all does this for every project in turn, each in its own tmux session, then attaches to the first.
The `sessions` setting names personal sessions (tmux sessions, or Herdr workspaces; for example dotfiles) with workspace.windows-style
windows; each run builds them too, without network, and never mixes them with the project's session.
Exit 0: done; 1: something was blocked or failed (listed);
2: usage or settings.
"""
import argparse
import os
from pathlib import Path
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sidequest.project_flag import take

take(sys.argv)


def up_all(argv):
    """--all: run `sidequest up` for every profile in turn (detached), then attach to the first session."""
    from sidequest import config, overview
    if os.environ.get('SIDEQUEST_PROJECT'):
        print('sidequest up: --all prepares every project; leave out --project', file=sys.stderr)
        return 2
    rows = overview.project_rows(run=lambda argv: (1, ''))
    if not rows:
        print('sidequest up: no projects yet; adopt one with sidequest-data project init NAME --repo PATH', file=sys.stderr)
        return 2
    args = [arg for arg in argv if arg != '--all']
    worst = 0
    for row in rows:
        print('== ' + row['name'] + ' ==', flush=True)
        env = dict(os.environ, SIDEQUEST_PROJECT=row['name'], SIDEQUEST_UP_SESSIONS='off')
        code = subprocess.run([sys.executable, str(Path(__file__).resolve().with_name('sidequest')), 'up', *args,
                               '--no-attach'], env=env).returncode
        worst = max(worst, code)
        print(flush=True)
    from sidequest import sync, terminal_mode
    shared = terminal_mode.mode(os.environ, config.SETTINGS)
    box = None if terminal_mode.unavailable(shared) else terminal_mode.sessions(shared)
    taken = {row['session'] for row in rows}
    for name, windows, _ in sync.personal_sessions(config.SETTINGS.get('sessions'), '', str(Path.home())):
        print('== ' + name + ' ==', flush=True)
        if name in taken:
            print('session  skipped: a project already uses that tmux session')
        elif not windows:
            print('session  skipped: no windows')
        elif '--dry-run' in args:
            for window in windows:
                print('window   ' + window.name.ljust(12) + ' ' + window.path)
        elif not box:
            print('session  not opened: ' + terminal_mode.unavailable(shared))
        else:
            try:
                print('session  ' + name + ': ' + str(box.open_layout(name, windows)) + ' windows')
            except RuntimeError as exc:
                worst = max(worst, 1)
                print('failed   ' + box.noun + ' ' + name + ': ' + str(exc))
        print(flush=True)
    if '--no-attach' not in args and '--dry-run' not in args:
        session, _, window = (config.get('workspace', 'attach_to') or rows[0]['session']).partition(':')
        row = next((row for row in rows if row['session'] == session), None)
        chosen = (row or {}).get('terminal') or shared
        target = None if terminal_mode.unavailable(chosen) else terminal_mode.sessions(chosen)
        if target and not target.exists(session):
            print('attach   ' + session + ' is not open; attaching to ' + rows[0]['session'])
            session, window, chosen = rows[0]['session'], '', rows[0].get('terminal') or 'tmux'
            target = None if terminal_mode.unavailable(chosen) else terminal_mode.sessions(chosen)
        if target:
            if window:
                target.select_window(session, window)
            target.attach(session)
    return worst


if '--all' in sys.argv[1:]:
    raise SystemExit(up_all(sys.argv[1:]))
try:
    from sidequest import app_booking, cleanup, collector, config, github, sync, terminal_mode, tmux, updates
except ValueError as exc:
    print('sidequest up: ' + str(exc), file=sys.stderr)
    raise SystemExit(2)
from sidequest.snapshots import SnapshotStore
from sidequest.workspace import GitWorkspace
from sidequest.worktrees import parse_worktrees

SIDEQUEST = str(Path(__file__).resolve().with_name('sidequest'))
MODE = terminal_mode.mode(os.environ, config.SETTINGS)
NOTE = terminal_mode.unavailable(MODE)
BOX = None if NOTE else terminal_mode.sessions(MODE)


def shown(window):
    """What a window runs, as the dry run shows it."""
    command = tmux.process(window) if MODE == 'tmux' else window.command
    return '  $ ' + command if command else ''


def session_windows(snapshot, repository):
    """(session name, windows) from `git worktree list` and the settings."""
    listed = subprocess.run(['git', '-C', str(repository), 'worktree', 'list', '--porcelain'],
                            capture_output=True, text=True).stdout
    values = config.SETTINGS.get('workspace', {})
    extras = values.get('windows') or [{'name': 'sidequest', 'command': SIDEQUEST, 'at': 'start', 'stay': True}]
    root = values.get('worktrees_dir') or str(Path(repository).parent)
    session = values.get('tmux_session') or config.PROJECT or 'sidequest'
    remembered = sync.remember_order(config.STATE_DIR / 'window-order.json', snapshot)
    return session, sync.layout(snapshot, parse_worktrees(listed), extras, root, remembered)


def personal_sessions(dry_run):
    """(lines, problems): build each tmux session in the `sessions` setting (no network), or list it."""
    if os.environ.get('SIDEQUEST_UP_SESSIONS') == 'off':  # --all builds them once, under their own header
        return [], 0
    project_session = config.get('workspace', 'tmux_session') or config.PROJECT or 'sidequest'
    lines, problems = [], 0
    for name, windows, note in sync.personal_sessions(config.SETTINGS.get('sessions'), project_session,
                                                      str(Path.home())):
        if windows is None or not windows:
            lines.append('session  ' + name + ' ' + (note or 'skipped: no windows'))
        elif dry_run:
            lines.append('session  ' + name)
            lines += ['window   ' + window.name.ljust(12) + ' ' + window.path + shown(window) for window in windows]
        else:
            try:
                BOX.open_layout(name, windows)
                lines.append('session  ' + name + ': ' + str(len(windows)) + ' windows')
            except RuntimeError as exc:
                problems += 1
                lines.append('failed   ' + BOX.noun + ' ' + name + ': ' + str(exc))
    return lines, problems


def terminal_note():
    """Why windows are not opened, or '' when tmux or Herdr is used."""
    return NOTE


def main():
    parser = argparse.ArgumentParser(prog='sidequest up', description=__doc__.split('\n')[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    parser.add_argument('--dry-run', action='store_true', help='print the plan; change no Git state')
    parser.add_argument('-n', '--offline', action='store_true', help='use the last collected data; no collection or fetch')
    parser.add_argument('--no-attach', action='store_true', help='leave the tmux session (Herdr workspace) detached')
    parser.add_argument('--cleanup', action='store_true',
                        help='consider removing merged worktrees even when sync.cleanup is off (asks per worktree)')
    parser.add_argument('--yes', action='store_true', help='remove merged worktrees that pass every check without asking')
    parser.add_argument('-r', '--rebuild', action='store_true',
                        help='close the tmux session first (stops what runs in its windows), then build it again')
    parser.add_argument('--when-due', action='store_true',
                        help='sync only when the last sync is older than sync.every_minutes; else attach, or build offline')
    parser.add_argument('--all', action='store_true', help='every project in turn, one tmux session each')
    parser.add_argument('-u', '--update', action='store_true',
                        help='also merge the base into pushed branches that are behind it (sync.update on)')
    args = parser.parse_args()
    from sidequest import overview
    if overview.unclear():
        print('sidequest up: ' + overview.unclear(), file=sys.stderr)
        return 2
    repository = config.workspace_repository()
    if not repository:
        print('sidequest up: set workspace.repository for this project (sidequest-data project check)', file=sys.stderr)
        return 2
    values = config.SETTINGS.get('workspace', {})
    workspace = GitWorkspace(repository, values.get('worktrees_dir'), config.base_ref(),
                             shlex.split(values.get('copy_files') or ''))
    print('sidequest up: ' + (config.PROJECT or 'this project') + ' (' + str(repository) + ')', flush=True)
    if args.when_due and not args.offline:
        recent = sync.fresh(SnapshotStore(collector.DEFAULT_OUT).read(), config.get('sync', 'every_minutes'),
                            tz=config.get('identity', 'timezone', 'UTC'))
        session = values.get('tmux_session') or config.PROJECT or 'sidequest'
        try:
            is_open = bool(recent) and not NOTE and BOX.exists(session)
        except RuntimeError as exc:
            print('note     ' + str(exc))
            is_open = False
        if is_open:
            print(recent + '; session ' + session + ' is open')
            for line in personal_sessions(False)[0]:
                print(line)
            if not args.no_attach:
                BOX.attach(session)
            return 0
        if recent:
            print(recent + '; building without network')
            args.offline = True
    if not args.offline:
        print('Collecting from Jira and GitHub…', flush=True)
        for message in collector.collect(sync=True).get('failures', {}).values():
            print('note     ' + message)
    fetched = False
    if not args.offline and not args.dry_run:
        fetched = subprocess.run(['git', '-C', str(repository), 'fetch', '--quiet', 'origin'],
                                 capture_output=True, text=True).returncode == 0
        if not fetched:
            print('note     git fetch failed; branches are not updated this run')
    snapshot = SnapshotStore(collector.DEFAULT_OUT).read()
    plan = sync.discover(snapshot, workspace, open_prs=config.get('sync', 'open_prs') != 'off')
    hooks = config.get('workspace', 'on_up') or []
    note = terminal_note()
    merge_base = args.update or config.get('sync', 'update') == 'on'

    mode = config.get('sync', 'cleanup') or 'ask'
    if args.cleanup and mode == 'off':
        mode = 'ask'
    merged, merged_problem = sync.source(snapshot, 'merged_prs', 'prs')
    session_name = config.get('workspace', 'tmux_session') or config.PROJECT or 'sidequest'

    def close_window(name):
        if not note:
            try:
                BOX.close_window(session_name, name)
            except RuntimeError:
                pass

    def remove_merged(dry_run):
        if mode == 'off':
            return [], 0
        if merged_problem:
            return ['cleanup  skipped: ' + merged_problem], 0
        interactive = sys.stdin.isatty() and sys.stdout.isatty()
        lines, problems = cleanup.clean(
            repository, merged, cwd=os.getcwd(), busy=sync.busy_check(app_booking.read(), sync.agent_dirs()),
            live_pr=github.pr_state, confirm=sync.confirm_removal(mode, args.yes, interactive),
            close_window=close_window, dry_run=dry_run)
        if not interactive and not args.yes and mode == 'ask' and any(line.endswith('you chose to keep it') for line in lines):
            lines.append('cleanup  nobody to ask without a terminal: run sidequest up in one, or add --yes')
        return lines, problems

    def update_branches(dry_run):
        busy = sync.busy_check(app_booking.read(), sync.agent_dirs())
        return updates.update_all(repository, config.base_ref(), merge_base=merge_base, busy=busy, dry_run=dry_run)
    if args.dry_run:
        for line in remove_merged(True)[0]:
            print(line)
        for action in plan:
            print(action.line)
        for line in update_branches(True)[0]:
            print(line)
        if note:
            print('windows  not opened: ' + note)
        else:
            session, windows = session_windows(snapshot, repository)
            if args.rebuild:
                print('would close ' + BOX.noun + ' ' + session + ' first; this stops what runs in its windows')
            for window in windows:
                print('window   ' + window.name.ljust(12) + ' ' + window.path + shown(window))
            for line in personal_sessions(True)[0]:
                print(line)
        for command in hooks:
            print('would run ' + command)
        print('Dry run: nothing changed.')
        return 1 if any(action.kind == 'blocked' for action in plan) else 0
    problems = 0
    if args.offline:
        if mode != 'off':
            print('cleanup  skipped with --offline: GitHub is asked before anything is removed')
    else:
        lines, cleanup_problems = remove_merged(False)
        for line in lines:
            print(line)
        problems += cleanup_problems
        if any(line.startswith('removed') for line in lines):
            plan = sync.discover(snapshot, workspace, open_prs=config.get('sync', 'open_prs') != 'off')
    results = sync.apply(plan, workspace)
    for result in results:
        print(result.line)
    problems += sum(1 for result in results if not result.ok)
    if fetched:
        lines, update_problems = update_branches(False)
        for line in lines:
            print(line)
        problems += update_problems
    session = None
    if note:
        print('windows  not opened: ' + note)
    else:
        session, windows = session_windows(snapshot, repository)
        try:
            if args.rebuild:
                BOX.close_session(session)
                print('closed   ' + BOX.noun + ' ' + session + ' (rebuild)')
            count = BOX.open_layout(session, windows)
            print('windows  ' + str(count) + ' in ' + BOX.noun + ' ' + session)
        except RuntimeError as exc:
            problems += 1
            session = None
            print('failed   ' + MODE + ' layout: ' + str(exc))
        lines, session_problems = personal_sessions(False)
        for line in lines:
            print(line)
        problems += session_problems
    for command in hooks:
        try:
            argv = shlex.split(command)
            argv[0] = os.path.expanduser(argv[0])
            ran = subprocess.run(argv, cwd=str(repository), capture_output=True, text=True, timeout=300)
            code, detail = ran.returncode, (ran.stderr.strip() or ran.stdout.strip()).splitlines()
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            code, detail = -1, [str(exc)]
        if code == 0:
            print('hook     ' + command)
        else:
            problems += 1
            print('failed   ' + command + ' (exit ' + str(code) + (': ' + detail[-1][:120] if detail else '') + ')')
    created = sum(1 for result in results if result.line.startswith('created'))
    print('Done: ' + str(created) + ' created' + (', ' + str(problems) + ' need attention' if problems else '') + '.')
    if session and not args.no_attach:
        BOX.attach(session)
    return 1 if problems else 0


if __name__ == '__main__':
    raise SystemExit(main())
