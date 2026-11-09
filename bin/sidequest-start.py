#!/usr/bin/env python3
"""sidequest start KEY [--yes] [--no-move] [--prefix P] [--no-attach]: start one ticket from a shell.

Does what Space n does in the dashboard. Moves KEY to jira.start_status (jira.start_from statuses
move; jira.start_ask statuses need --yes; --no-move leaves Jira alone), creates or reuses its
worktree, runs `sidequest up --offline --no-attach` so the window exists, selects that window and
prints "DIR <worktree>". A bare number takes the first of jira.projects (800 -> APP-800).
Exit 0: done; 1: the worktree or the window failed; 2: usage or settings.
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
try:
    from sidequest import config, start, terminal_mode
except ValueError as exc:
    raise SystemExit('sidequest start: ' + str(exc))
from sidequest.workspace import GitWorkspace

SIDEQUEST = str(Path(__file__).resolve().with_name('sidequest'))


def main():
    parser = argparse.ArgumentParser(prog='sidequest start', description=__doc__.split('\n')[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    parser.add_argument('key', help='a Jira key such as APP-123, or only its number')
    parser.add_argument('-y', '--yes', action='store_true', help='also move from a jira.start_ask status')
    parser.add_argument('--no-move', action='store_true', help='leave the Jira status alone')
    parser.add_argument('--prefix', choices=('fix', 'feature', 'hotfix', 'chore'), help='branch prefix for a new branch')
    parser.add_argument('--no-attach', action='store_true', help='do not switch to the window')
    args = parser.parse_args()
    try:
        key = start.full_key(args.key, config.get('jira', 'projects', []))
    except ValueError as exc:
        print('sidequest start: ' + str(exc), file=sys.stderr)
        return 2
    from sidequest import overview
    if overview.unclear():
        print('sidequest start: ' + overview.unclear(), file=sys.stderr)
        return 2
    repository = config.workspace_repository()
    if not repository:
        print('sidequest start: set workspace.repository for this project (sidequest-data project check)', file=sys.stderr)
        return 2
    from sidequest.jira import client
    values = config.SETTINGS.get('workspace', {})
    workspace = GitWorkspace(repository, values.get('worktrees_dir'), config.base_ref(),
                             shlex.split(values.get('copy_files') or ''))
    try:
        lines, made = start.start(key, client, workspace, move=not args.no_move, yes=args.yes, prefix=args.prefix)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print('sidequest start: ' + str(exc), file=sys.stderr)
        return 1
    for line in lines:
        print(line)
    print(made['state'].upper() + ' ' + made['branch'])
    up = subprocess.run([sys.executable, SIDEQUEST, 'up', '--offline', '--no-attach'],
                        capture_output=True, text=True, stdin=subprocess.DEVNULL)
    session = values.get('tmux_session') or config.PROJECT or 'sidequest'
    window = up.stdout.find('windows  ') >= 0 and 'not opened' not in up.stdout
    if up.returncode:
        print('note     the layout reported a problem; run sidequest up -n to see it', file=sys.stderr)
    box = terminal_mode.sessions(terminal_mode.mode(os.environ, config.SETTINGS)) if window else None
    try:
        if box:
            box.select_window(session, key)
        print('DIR ' + made['path'], flush=True)
        if box and not args.no_attach and sys.stdout.isatty():
            box.attach(session)
    except RuntimeError as exc:
        print('note     ' + str(exc), file=sys.stderr)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
