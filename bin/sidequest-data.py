#!/usr/bin/env python3
"""Read-only helpers bundled with the standalone TUI."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sidequest.collector import DEFAULT_OUT, collect
from sidequest.jira import client
from sidequest.snapshots import SnapshotStore


def main():
    parser = argparse.ArgumentParser(prog='sidequest-data', description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
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
