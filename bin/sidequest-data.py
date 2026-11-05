#!/usr/bin/env python3
"""Bundled collection and workflow helpers; local changes require explicit commands."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sidequest.collector import DEFAULT_OUT, collect
from sidequest.jira import client
from sidequest.snapshots import SnapshotStore

LOCAL = {'branch-name': 'sidequest-workspace.py', 'worktree': 'sidequest-worktree.py',
         'workspace': 'sidequest-workspace-create.py', 'plan-init': 'sidequest-plan-init.py',
         'pr-body-check': 'sidequest-pr-body-check.py', 'ship-check': 'sidequest-ship-check.py',
         'qa-shot': 'sidequest-qa-shot.py', 'review-app': 'sidequest-review-app.py',
         'pr-feedback': 'sidequest-feedback.py', 'skills': 'sidequest-skills.py'}


def main():
    if len(sys.argv) > 1 and sys.argv[1] in LOCAL:
        import runpy
        script = Path(__file__).with_name(LOCAL[sys.argv[1]])
        sys.argv = [str(script), *sys.argv[2:]]
        runpy.run_path(str(script), run_name='__main__')
        return 0
    parser = argparse.ArgumentParser(prog='sidequest-data', description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in LOCAL:
        commands.add_parser(name, add_help=False, help='Bundled workflow helper; use ' + name + ' --help')
    for command in ('collect', 'snapshot'):
        sub = commands.add_parser(command)
        sub.add_argument('--out', type=Path, default=DEFAULT_OUT)
        sub.add_argument('--json', action='store_true')
        sub.add_argument('--quiet', action='store_true')
        sub.add_argument('--max-age', type=int, default=0)
    ticket = commands.add_parser('ticket')
    ticket.add_argument('key')
    ticket.add_argument('--json', action='store_true')
    ticket.add_argument('--activity', action='store_true')
    args = parser.parse_args()
    try:
        if args.command == 'ticket':
            data = client.fetch_one(args.key.upper(), include_activity=args.activity)
        else:
            data = collect(args.out, args.max_age) if args.command == 'collect' else SnapshotStore(args.out).read()
        if not getattr(args, 'quiet', False):
            print(json.dumps(data, indent=2))
        return 1 if data.get('failures') else 0
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
        print('Collection failed. Check configuration, network and service login. Previous data retained.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
