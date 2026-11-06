#!/usr/bin/env python3
"""Bundled collection and workflow helpers; local changes require explicit commands."""
import argparse
import json
import re
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sidequest.access import NOTES, failure_record
from sidequest.collector import DEFAULT_OUT, collect
from sidequest.jira import client
from sidequest.snapshots import SnapshotStore

FAILURE_LINE = 'sidequest-data-failure: '  # one JSON record, read by the dashboard
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
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        failure, record = failure_record(exc, args.command)
        text = failure.terminal_text
        if isinstance(exc, client.JiraError) and (failure.cause == 'unknown' or exc.status == 301):
            # Jira's own words explain these (a bad key, a moved issue's new key); keep any note.
            text = jira_text(exc) + (' ' + NOTES[failure.note] + '.' if failure.note else '')
        print('sidequest-data: ' + text, file=sys.stderr)
        print(FAILURE_LINE + json.dumps(record), file=sys.stderr)
        return 2


def jira_text(exc):
    text = re.sub(r';\s*(previous data retained|retain the previous snapshot)\.?$', '', str(exc)).rstrip('.')
    return (text if 'jira' in text.lower() else 'Jira: ' + text) + '.'

if __name__ == '__main__':
    raise SystemExit(main())
