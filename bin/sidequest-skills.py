#!/usr/bin/env python3
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sidequest.skills import install

parser = argparse.ArgumentParser(prog='sidequest-data skills', description='Preview skill installation. --apply installs; --check detects drift without writing.')
parser.add_argument('--dest', required=True, type=Path)
mode = parser.add_mutually_exclusive_group()
mode.add_argument('--apply', action='store_true')
mode.add_argument('--check', action='store_true')
args = parser.parse_args()
try:
    changed = install(args.dest, args.apply, args.check)
    print('\n'.join(changed) if changed else 'Skills are synchronized')
    raise SystemExit(1 if args.check and changed else 0)
except (OSError, ValueError) as exc:
    print('sidequest-data: ' + str(exc), file=sys.stderr)
    raise SystemExit(2)
