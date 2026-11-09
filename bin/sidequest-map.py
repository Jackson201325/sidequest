#!/usr/bin/env python3
"""Write an interactive HTML map of this checkout: calls, file writes, config reads and programs."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sidequest import codemap

parser = argparse.ArgumentParser(prog='sidequest-map', description='Read-only code map. Scans source files; never imports or runs them.')
parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1], help='checkout to scan (default: this one)')
parser.add_argument('--out', type=Path, default=Path(tempfile.gettempdir()) / 'sidequest-map.html', help='HTML file to write')
parser.add_argument('--tests', action='store_true', help='include test modules')
parser.add_argument('--json', action='store_true', help='print the scan as JSON instead of writing HTML')
args = parser.parse_args()
try:
    data = codemap.scan(args.root, tests=args.tests)
    if args.json:
        print(json.dumps(data, indent=1))
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(codemap.render(data), encoding='utf-8')
        print(args.out)
except (OSError, SyntaxError, ValueError) as exc:
    print('sidequest-map: ' + str(exc), file=sys.stderr)
    raise SystemExit(2)
