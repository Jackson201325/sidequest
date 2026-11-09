"""The shared local app's booking: one worktree at a time. bin/sqapp writes it; the dashboard reads it.

The lock line is '<worktree path>\\t<booked epoch>\\t<last active epoch>' in the state folder,
so each configuration (and its XDG_STATE_HOME) has its own booking.
"""
import time
from pathlib import Path

from sidequest import config
from sidequest.ticket_keys import ticket_key


def lock_path():
    return config.STATE_DIR / 'app.lock'


def minutes(name, default):
    return int(config.get('app', name) or default)


def ttl_seconds():
    return minutes('ttl_minutes', 30) * 60


def configured():
    return bool(config.get('app', 'switch_command'))


def parse(text, now_epoch, ttl):
    """{state: free} or {state: booked, path, owner, booked, idle_seconds}; an expired booking is free."""
    fields = (text or '').strip().split('\t')
    if len(fields) != 3 or not fields[1].isdigit() or not fields[2].isdigit():
        return {'state': 'free'}
    path, booked, seen = fields[0], int(fields[1]), int(fields[2])
    if now_epoch - seen > ttl:
        return {'state': 'free', 'expired': path}
    name = Path(path).name
    return {'state': 'booked', 'path': path, 'owner': ticket_key(name) or name, 'name': name,
            'booked': booked, 'idle_seconds': max(0, now_epoch - seen)}


def read(path=None, now_epoch=None):
    try:
        text = Path(path or lock_path()).read_text()
    except OSError:
        text = ''
    return parse(text, int(time.time()) if now_epoch is None else now_epoch, ttl_seconds())


def label(booking):
    if booking.get('state') != 'booked':
        return 'App free'
    idle = booking['idle_seconds'] // 60
    return f"App {booking['owner']} · idle {'<1' if idle < 1 else idle}m"
