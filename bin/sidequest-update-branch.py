#!/usr/bin/env python3
"""sidequest-data update-branch: bring this worktree's branch up to date with the base. Never pushes.

  sidequest-data update-branch                    fetch, then update with workspace.base_ref
  sidequest-data update-branch --keep-conflicts   leave a conflict open to resolve (exit 3)
  sidequest-data update-branch --base REF         use REF; --no-fetch skips the fetch

Same rules as `sidequest up`: new commits from the branch's own origin branch are fast-forwarded; a
branch never pushed is rebased onto the base; a pushed branch gets the base merged in (no force-push
needed later). A branch that diverged from its origin branch, or with a merge/rebase in progress, is
refused. Uncommitted work is autostashed. Exit 0: updated or up to date; 1: failed and aborted;
2: refused, nothing changed; 3: conflicts left open (--keep-conflicts).
"""
import argparse
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sidequest import config, updates


def main():
    parser = argparse.ArgumentParser(prog='sidequest-data update-branch', description=__doc__.split('\n')[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    parser.add_argument('--base', help='compare with REF instead of workspace.base_ref')
    parser.add_argument('--no-fetch', action='store_true', help='do not fetch the remote of the base first')
    parser.add_argument('--keep-conflicts', action='store_true', help='leave a conflict open instead of aborting')
    args = parser.parse_args()
    base = args.base or config.base_ref()
    if not args.no_fetch and '/' in base:
        fetched = subprocess.run(['git', 'fetch', '--quiet', base.split('/', 1)[0]], capture_output=True, text=True,
                                 timeout=120)
        if fetched.returncode:
            print('FAILED git fetch ' + base.split('/', 1)[0] + ': ' + (fetched.stderr.strip() or 'no output'),
                  file=sys.stderr)
            return 1
    code, lines = updates.update_branch(Path.cwd(), base, args.keep_conflicts)
    print('\n'.join(lines), file=sys.stdout if code in (0, 3) else sys.stderr)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
