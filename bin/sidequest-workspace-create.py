#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sidequest.workspace import prepare

parser = argparse.ArgumentParser(prog='sidequest-data workspace', description='Preview a local worktree; --apply explicitly creates it. Never removes worktrees or changes Jira.')
parser.add_argument('key')
parser.add_argument('--summary', required=True)
parser.add_argument('--type', default='', dest='issue_type')
parser.add_argument('--prefix', choices=('fix', 'feature', 'hotfix', 'chore'))
parser.add_argument('--base', default='origin/main')
parser.add_argument('--apply', action='store_true')
parser.add_argument('--json', action='store_true')
args = parser.parse_args()
try:
    result = prepare(args.key, args.summary, args.issue_type, args.prefix, args.base, args.apply)
    print(json.dumps(result, indent=2) if args.json else result['state'].upper() + ' ' + result['branch'] + '\nDIR ' + result['path'])
except (OSError, RuntimeError, ValueError) as exc:
    print('sidequest-data: ' + str(exc), file=sys.stderr)
    raise SystemExit(2)
