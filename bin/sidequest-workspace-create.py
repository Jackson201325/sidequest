#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sidequest import config, terminal
from sidequest.application import build_workflow
import os

parser = argparse.ArgumentParser(prog='sidequest-data workspace', description='Preview a local worktree; --apply explicitly creates it. Never removes worktrees or changes Jira.')
parser.add_argument('key')
parser.add_argument('--summary', required=True)
parser.add_argument('--type', default='', dest='issue_type')
parser.add_argument('--prefix', choices=('fix', 'feature', 'hotfix', 'chore'))
parser.add_argument('--base', default=config.get('workspace', 'base_ref') or 'origin/main')
parser.add_argument('--apply', action='store_true')
parser.add_argument('--open', action='store_true', help='Create/reuse the worktree and open an interactive shell there; exit returns here')
parser.add_argument('--json', action='store_true')
args = parser.parse_args()
if args.open and args.json:
    parser.error('--open uses an interactive terminal and cannot be combined with --json')
try:
    workflow = build_workflow(config.SETTINGS, os.environ)
    if args.open:
        launch = workflow.start(args.key, args.summary, args.issue_type, args.prefix, args.base)
        result = launch.workspace
    else:
        result = workflow.prepare(args.key, args.summary, args.issue_type, args.prefix, args.base, args.apply)
    print(json.dumps(result, indent=2) if args.json else result['state'].upper() + ' ' + result['branch'] + '\nDIR ' + result['path'], flush=True)
    if args.open:
        raise SystemExit(terminal.run_request(launch.foreground))
except (OSError, RuntimeError, ValueError) as exc:
    print('sidequest-data: ' + str(exc), file=sys.stderr)
    raise SystemExit(2)
