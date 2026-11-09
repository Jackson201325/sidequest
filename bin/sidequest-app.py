#!/usr/bin/env python3
"""sqapp: let one worktree at a time use the project's shared local app.

  sqapp              book the app for this worktree and point it at this worktree's code
                     (instant if it already runs this worktree; refreshes your booking)
  sqapp --wait       same, but wait up to app.wait_minutes (default 9) for another worktree to finish
  sqapp --release    done testing: free the app for the next worktree
  sqapp --status     who has the app booked, and which worktree it runs
  sqapp --force      take the app now, even if another worktree has it booked (for humans)

Configure the "app" section: switch_command (run in the worktree to point the app at it,
e.g. "make up"), current_command (prints the folder the app runs), running_command
(exit 0 and not "false" means the app is up), url, required_files, ttl_minutes (default 30).
Exit codes: 0 ok, 75 busy (another worktree has it; retry later), 1 error.
"""
import argparse
import fcntl
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time
from contextlib import contextmanager

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sidequest.project_flag import take

take(sys.argv)
from sidequest import app_booking, config

BUSY = 75


def ago(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds}s" if seconds < 60 else f"{seconds // 60}m"


@contextmanager
def held():
    """Hold the booking mutex while reading or writing the lock file."""
    lock = app_booking.lock_path()
    lock.parent.mkdir(parents=True, exist_ok=True)
    with open(str(lock) + '.mutex', 'w') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def write(path, booked, seen):
    lock = app_booking.lock_path()
    temporary = lock.with_suffix('.tmp')
    temporary.write_text(f"{path}\t{booked}\t{seen}\n")
    os.replace(temporary, lock)


def command(name, cwd):
    """(exit code, trimmed output) of a configured command, or None when it is not configured."""
    argv = shlex.split(config.get('app', name))
    if not argv:
        return None
    try:
        result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return 1, ''
    return result.returncode, result.stdout.strip()


def current(cwd):
    """(folder the app runs or '', whether it is up)."""
    found = command('current_command', cwd)
    folder = str(Path(found[1]).resolve()) if found and found[0] == 0 and found[1] else ''
    up = command('running_command', cwd)
    running = up is not None and up[0] == 0 and up[1].casefold() not in ('false', '0')
    return folder, running


def release(here, quiet=False):
    with held():
        booking = app_booking.read()
        if booking['state'] != 'booked':
            message = "sqapp: app wasn't booked"
        elif booking['path'] != here:
            message = f"sqapp: app is booked by {booking['name']}, not this worktree; leaving it"
        else:
            app_booking.lock_path().unlink()
            message = 'sqapp: released the app'
    if not quiet:
        print(message)


def book(here, force):
    """0 when booked for here, BUSY when another live booking holds it; also returns the booking seen."""
    with held():
        booking = app_booking.read()
        now = int(time.time())
        if booking['state'] == 'booked' and booking['path'] != here and not force:
            return BUSY, booking
        booked = booking['booked'] if booking.get('path') == here else now
        write(here, booked, now)
        return 0, booking


def main():
    parser = argparse.ArgumentParser(prog='sqapp', description=__doc__.split('\n')[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    mode = parser.add_mutually_exclusive_group()
    for flag in ('--wait', '--release', '--status', '--force'):
        mode.add_argument(flag, action='store_true')
    options = parser.parse_args()
    found = subprocess.run(['git', 'rev-parse', '--show-toplevel'], capture_output=True, text=True)
    if found.returncode != 0:
        print('sqapp: run this inside a git worktree of your project', file=sys.stderr)
        return 1
    here = str(Path(found.stdout.strip()).resolve())
    url = config.get('app', 'url')

    if options.release:
        release(here)
        return 0
    if options.status:
        booking = app_booking.read()
        if booking['state'] == 'booked':
            now = int(time.time())
            print(f"booked:  {booking['name']} for {ago(now - booking['booked'])} (last active "
                  f"{ago(booking['idle_seconds'])} ago)" + (' (this worktree)' if booking['path'] == here else ''))
        else:
            print('booked:  free')
        if app_booking.configured():
            folder, running = current(here)
            name = Path(folder).name if folder else ''
            print('running: ' + (f"{name}" + (f"  ({url})" if url else '') if folder and running else
                                 f"stopped (last used {name})" if folder else 'unknown (current_command not set)'
                                 if not config.get('app', 'current_command') else 'app not created'))
        return 0

    if not app_booking.configured():
        print('sqapp: set app.switch_command in your Sidequest config (for example "make up")', file=sys.stderr)
        return 1
    missing = [name for name in shlex.split(config.get('app', 'required_files')) if not (Path(here) / name).exists()]
    if missing:
        print(f"sqapp: {here} has no {', '.join(missing)}; copy it from the main checkout first", file=sys.stderr)
        return 1

    start, said = time.monotonic(), 0.0
    wait = app_booking.minutes('wait_minutes', 9) * 60
    while True:
        code, seen = book(here, options.force)
        if code == 0:
            break
        if not options.wait or time.monotonic() - start >= wait:
            print(f"sqapp: busy, {seen['name']} has been using the app for {ago(time.time() - seen['booked'])} "
                  f"(active {ago(seen['idle_seconds'])} ago).", file=sys.stderr)
            print("       Retry later (or 'sqapp --wait'). A human can take it with 'sqapp --force'.", file=sys.stderr)
            return BUSY
        if time.monotonic() - said >= 30:
            print(f"sqapp: waiting for {seen['name']} to finish…", flush=True)
            said = time.monotonic()
        time.sleep(5)
    if seen.get('expired') and seen['expired'] != here:
        print(f"sqapp: took over an expired booking from {Path(seen['expired']).name}")

    folder, running = current(here)
    # Docker Desktop reports bind mounts under a VM prefix such as /host_mnt.
    if (folder == here or folder.endswith(here)) and running:
        print(f"sqapp: app is yours and already runs {Path(here).name}" + (f"  ({url})" if url else ''))
        print("       run 'sqapp --release' when you're done testing")
        return 0
    print(f"sqapp: switching app {('from ' + Path(folder).name + ' ') if folder else ''}to {Path(here).name}", flush=True)
    try:
        switched = subprocess.run(shlex.split(config.get('app', 'switch_command')), cwd=here).returncode
    except OSError:
        switched = 1
    if switched != 0:
        print('sqapp: switch_command failed; releasing the booking', file=sys.stderr)
        release(here, quiet=True)
        return 1
    print('sqapp: ' + (url + ', ' if url else '') + "run 'sqapp --release' when you're done testing")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
