#!/usr/bin/env python3
"""Complete PR feedback through the standalone GitHub adapter."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sidequest import github, identity
from sidequest.collector import collect_prs

parser = argparse.ArgumentParser(prog='sidequest-data pr-feedback')
parser.add_argument('number', type=int, nargs='?')
parser.add_argument('--json', action='store_true', help='no effect; the output is always JSON')
parser.add_argument('--activity', action='store_true')
args = parser.parse_args()
try:
    if not identity.GITHUB_REPO:
        raise RuntimeError('Configure github.repository first')
    if args.number:
        fields = 'number,title,url,headRefName,headRefOid,createdAt,updatedAt,isDraft,reviewDecision,reviewRequests,statusCheckRollup'
        header = json.loads(github.gh_output(['gh', 'pr', 'view', str(args.number), '--repo', identity.GITHUB_REPO, '--json', fields]))
        data = {'pr': github.enrich_pr(header, include_threads=True, include_activity=args.activity)}
    else:
        data = collect_prs()
    print(json.dumps(data, indent=2))
except (OSError, RuntimeError, ValueError):
    print('GitHub feedback unavailable; check configuration and gh auth login', file=sys.stderr)
    raise SystemExit(2)
