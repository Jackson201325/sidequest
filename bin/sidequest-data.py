#!/usr/bin/env python3
"""Bundled collection and workflow helpers; local changes require explicit commands."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sidequest.project_flag import take

take(sys.argv)
try:
    from sidequest import config
except ValueError as exc:
    print('sidequest-data: ' + str(exc), file=sys.stderr)
    raise SystemExit(2)
from sidequest.access import clip, describe_failure
from sidequest.collector import DEFAULT_OUT, collect
from sidequest.jira import client
from sidequest.qa import attachments_dir
from sidequest.snapshots import SnapshotStore
from sidequest.ticket_keys import is_key

FAILURE_LINE = 'sidequest-data-failure: '  # {"text": dashboard message}, read by the dashboard
LOCAL = {'branch-name': 'sidequest-workspace.py', 'worktree': 'sidequest-worktree.py',
         'workspace': 'sidequest-workspace-create.py', 'plan-init': 'sidequest-plan-init.py',
         'pr-body-check': 'sidequest-pr-body-check.py', 'ship-check': 'sidequest-ship-check.py',
         'qa-shot': 'sidequest-qa-shot.py', 'review-app': 'sidequest-review-app.py',
         'pr-feedback': 'sidequest-feedback.py', 'skills': 'sidequest-skills.py',
         'questions': 'sidequest-questions.py', 'app': 'sidequest-app.py',
         'run': 'sidequest-run.py', 'update-branch': 'sidequest-update-branch.py'}


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
    ticket.add_argument('--attachments', metavar='DIR', nargs='?', const='',
                        help="download every attachment (default: the ticket folder's attachments/)")
    project = commands.add_parser('project', help='show the selected project; init NAME --repo PATH; check; wiring')
    project.add_argument('action', nargs='?', choices=('show', 'init', 'check', 'wiring'), default='show')
    project.add_argument('name', nargs='?', help='for init: the new project name')
    project.add_argument('--repo', help="for init: the project's main checkout")
    skill = commands.add_parser('skill', help="print a workflow skill with the current project's additions")
    skill.add_argument('name')
    start = commands.add_parser('jira-start', help='move a ticket to jira.start_status (opt-in; the only Jira write)')
    start.add_argument('key')
    start.add_argument('--yes', action='store_true', help='also move from a jira.start_ask status')
    start.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if (args.command == 'jira-start' or getattr(args, 'attachments', None) is not None) and not is_key(args.key):
        parser.error('expected a Jira key such as APP-123')
    if args.command == 'skill':
        from sidequest import skills
        try:
            print(skills.instructions(args.name), end='')
        except ValueError as exc:
            print('sidequest-data: ' + str(exc), file=sys.stderr)
            return 2
        return 0
    if args.command == 'project' and args.action in ('init', 'check', 'wiring'):
        from sidequest import projects
        try:
            if args.action == 'init':
                if not args.name or not args.repo:
                    raise ValueError('Usage: sidequest-data project init NAME --repo PATH')
                lines, failed = projects.init(args.name, args.repo), False
            elif args.action == 'wiring':
                lines, failed = projects.wiring()
            else:
                lines, failed = projects.check()
        except (OSError, ValueError) as exc:
            print('sidequest-data: ' + str(exc), file=sys.stderr)
            return 2
        print('\n'.join(lines))
        return 1 if failed else 0
    if args.command == 'project':
        print('project: ' + (config.PROJECT or 'none (shared settings only)'))
        print('settings: ' + str(config.CONFIG_PATH) + (' + ' + str(config.PROJECT_PATH) if config.PROJECT_PATH else ''))
        print('data: ' + str(config.DATA_DIR))
        print('state: ' + str(config.STATE_DIR))
        print('known: ' + (', '.join(config.profiles()) or 'none'))
        return 0
    try:
        if args.command == 'jira-start':
            code, message = client.start_ticket(args.key.upper(), yes=args.yes, dry_run=args.dry_run)
            print(message, file=sys.stdout if code == 0 else sys.stderr)
            if code:
                # The dashboard shows only a failure record; without one Space n loses the reason.
                print(FAILURE_LINE + json.dumps({'text': clip(message)}), file=sys.stderr)
            return code
        if args.command == 'ticket' and args.attachments is not None:
            folder = Path(args.attachments) if args.attachments else attachments_dir(args.key.upper())
            rows = client.download_attachments(args.key.upper(), folder)
            for row in rows:
                print(('ERROR ' + row['error'] + ': ' + row['filename']) if row.get('error') else 'SAVED ' + row['path'])
            if not rows:
                print('No attachments on ' + args.key.upper())
            return 1 if any(row.get('error') for row in rows) else 0
        if args.command == 'ticket':
            data = client.fetch_one(args.key.upper(), include_activity=args.activity)
        else:
            data = collect(args.out, args.max_age) if args.command == 'collect' else SnapshotStore(args.out).read()
        if not getattr(args, 'quiet', False):
            print(json.dumps(data, indent=2))
        return 1 if data.get('failures') else 0
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        terminal, dashboard = describe_failure(exc, args.command)
        print('sidequest-data: ' + terminal, file=sys.stderr)
        print(FAILURE_LINE + json.dumps({'text': dashboard}), file=sys.stderr)
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
