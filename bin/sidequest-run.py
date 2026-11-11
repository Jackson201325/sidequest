#!/usr/bin/env python3
"""sidequest-data run: the crew worker's step and state for a ticket (the ticket folder's run.json).

Writes only <tickets folder>/KEY/run.json (SIDEQUEST_TICKETS_DIR overrides the folder).
`sidequest crew --status` and the dashboard read it.

  sidequest-data run list [--json]
  sidequest-data run APP-123 show [--json]
  sidequest-data run APP-123 set STEP STATE [--note TEXT]
  sidequest-data run APP-123 hook prompt|stop|notify     (Claude Code hooks; always exits 0)

Steps: start, implement, qa-local, ship-check.
States: queued, working, waiting (on you), ready (for you), failed.
"""
import argparse
from datetime import datetime, timezone
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sidequest import runs
from sidequest.qa import ticket_dir, tickets_dir
from sidequest.ticket_keys import is_key


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
    event = commands.add_parser("hook")
    event.add_argument("event")
    for sub in (show, setting, event):
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
            return 0
        runs.update(path, key, options.step, options.state, options.note, at)
        print("UPDATED " + key + " " + options.step + " " + options.state + " " + str(path))
        return 0
    except (OSError, ValueError) as exc:
        print("sidequest-data run: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
