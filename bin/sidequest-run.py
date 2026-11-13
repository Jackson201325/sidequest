#!/usr/bin/env python3
"""sidequest-data run: the crew worker's step and state for a ticket (the ticket folder's run.json).

Writes only <tickets folder>/KEY/run.json (SIDEQUEST_TICKETS_DIR overrides the folder).
`sidequest crew --status` and the dashboard read it.

  sidequest-data run list [--json]
  sidequest-data run APP-123 show [--json]
  sidequest-data run APP-123 set STEP STATE [--note TEXT]
  sidequest-data run APP-123 ran STEP                  exit 0: STEP already finished on this same code
  sidequest-data run APP-123 hook prompt|stop|notify|tool  (Claude Code hooks; always exits 0)

Steps: start, implement, qa-local, ship-check, challenge, qa-review.
States: queued, working, waiting (on you), ready (for you), failed.

Run from the ticket's worktree, `set` also counts finished steps under "finished": a step finishes when it
is set ready or the worker moves on to a later step. Each count keeps a fingerprint of the code (commit,
uncommitted diff and untracked files), so `ran` can tell a worker to skip a step it already ran on that code.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sidequest import runs
from sidequest.qa import ticket_dir, tickets_dir
from sidequest.ticket_keys import is_key


def code_version(folder="."):
    """Fingerprint of the checkout's code: HEAD, the uncommitted diff and untracked files. None outside Git."""
    def git(*args):
        return subprocess.run(["git", "-C", str(folder), *args], capture_output=True, check=True, timeout=30).stdout
    try:
        digest = hashlib.sha1(git("rev-parse", "HEAD"))
        digest.update(git("diff", "HEAD", "--binary"))
        names = git("ls-files", "-z", "--others", "--exclude-standard").split(b"\0")
    except (OSError, subprocess.SubprocessError):
        return None
    for name in filter(None, names):
        digest.update(name + b"\0")
        try:
            digest.update(hashlib.sha1((Path(folder) / name.decode()).read_bytes()).digest())
        except (OSError, UnicodeDecodeError):
            continue
    return digest.hexdigest()[:12]


def main():
    argv = sys.argv[1:]
    if argv and argv[0] == "list":
        parser = argparse.ArgumentParser(prog="sidequest-data run list")
        parser.add_argument("--json", action="store_true")
        parser.add_argument("--at", help=argparse.SUPPRESS)
        options = parser.parse_args(argv[1:])
        clock = datetime.fromisoformat(options.at) if options.at else datetime.now(timezone.utc)
        records = runs.all_records(tickets_dir())
        print(json.dumps(records, indent=2) if options.json else "\n".join(runs.table(records, clock)))
        return 0
    parser = argparse.ArgumentParser(prog="sidequest-data run", description=__doc__.split("\n")[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    parser.add_argument("key")
    parser.add_argument("--at", help=argparse.SUPPRESS)
    commands = parser.add_subparsers(dest="command", required=True)
    show = commands.add_parser("show")
    show.add_argument("--json", action="store_true")
    setting = commands.add_parser("set")
    setting.add_argument("step", choices=runs.STEPS)
    setting.add_argument("state", choices=runs.STATES)
    setting.add_argument("--note", default="")
    asked = commands.add_parser("ran")
    asked.add_argument("step", choices=runs.STEPS)
    event = commands.add_parser("hook")
    event.add_argument("event")
    for sub in (show, setting, asked, event):
        sub.add_argument("--at", help=argparse.SUPPRESS)
    options = parser.parse_args(argv)
    key = options.key.upper()
    at = options.at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    if options.command == "hook":
        # A failing hook must never stop or block the worker.
        try:
            sys.stdin.read() if not sys.stdin.isatty() else None
            if is_key(key):
                runs.hook(ticket_dir(key) / "run.json", options.event, at)
        except (OSError, ValueError) as exc:
            print("sidequest-data run: " + str(exc), file=sys.stderr)
        return 0
    if not is_key(key):
        parser.error("expected a Jira key such as APP-123")
    path = ticket_dir(key) / "run.json"
    try:
        if options.command == "show":
            record = runs.read(path)
            if options.json:
                print(json.dumps(record, indent=2))
            else:
                print(runs.summary(record, datetime.fromisoformat(at)) if record else "No crew worker for " + key)
                if record and runs.finished_counts(record):
                    print("Finished: " + runs.finished_counts(record))
            return 0
        if options.command == "ran":
            already, message = runs.ran(runs.read(path), options.step, code_version())
            print(message)
            return 0 if already else 1
        runs.update(path, key, options.step, options.state, options.note, at, code_version())
        print("UPDATED " + key + " " + options.step + " " + options.state + " " + str(path))
        return 0
    except (OSError, ValueError) as exc:
        print("sidequest-data run: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
