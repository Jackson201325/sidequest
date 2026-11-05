#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sidequest.workspaces import branch_name

parser = argparse.ArgumentParser(prog="sidequest-data branch-name")
parser.add_argument("key")
parser.add_argument("--summary", required=True)
parser.add_argument("--type", default="", dest="issue_type")
parser.add_argument("--prefix", choices=("fix", "feature", "hotfix", "chore"))
args = parser.parse_args()
try:
    print(branch_name(args.key, args.summary, args.issue_type, args.prefix))
except ValueError as exc:
    parser.error(str(exc))
