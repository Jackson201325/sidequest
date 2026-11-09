"""The project overview: one row per profile, the picker's text lines and its quick actions. No curses."""
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import time
from zoneinfo import ZoneInfo

from sidequest import app_booking, config
from sidequest.worktrees import parse_worktrees

HELP = ['Enter/a attach (up -n if no session)   u up   r up -r   d dry run',
        's start ticket…   q queue (dashboard)   c check settings   Esc quit']
KEYS = {'u': ('sidequest', ['up']), 'r': ('confirm', ['up', '-r']), 'd': ('sidequest', ['up', '--dry-run']),
        's': ('ask_key', ['start']), 'q': ('sidequest', []), 'c': ('data', ['project', 'check'])}


def _run(argv):
    try:
        ran = subprocess.run(argv, capture_output=True, text=True, timeout=10)
        return ran.returncode, ran.stdout
    except (OSError, subprocess.SubprocessError):
        return 1, ''


def _json(path):
    try:
        data = json.loads(Path(path).read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def project_rows(root=None, state_home=None, run=_run):
    """[{name, repo, session, windows, synced, worktrees, booked}], read-only, one per profile."""
    root = Path(root or config.PROJECTS_DIR)
    state_home = Path(state_home or os.environ.get('XDG_STATE_HOME') or Path.home() / '.local/state')
    rows = []
    for name, path in config.profiles(root).items():
        settings = _json(path)
        workspace = settings.get('workspace') if isinstance(settings.get('workspace'), dict) else {}
        app = settings.get('app') if isinstance(settings.get('app'), dict) else {}
        repo, session = workspace.get('repository') or '', workspace.get('tmux_session') or name
        state = state_home / config.NAMESPACE / 'projects' / name
        worktrees = None
        if repo:
            code, out = run(['git', '-C', str(Path(repo).expanduser()), 'worktree', 'list', '--porcelain'])
            worktrees = max(len(parse_worktrees(out)) - 1, 0) if code == 0 else None
        code, out = run(['tmux', 'list-windows', '-F', '#{window_id}', '-t', '=' + session])
        try:
            lock = (state / 'app.lock').read_text()
        except OSError:
            lock = ''
        ttl = int(app.get('ttl_minutes') or 30) * 60
        booking = app_booking.parse(lock, int(time.time()), ttl)
        rows.append({'name': name, 'repo': repo, 'session': session,
                     'windows': len(out.splitlines()) if code == 0 else None,
                     'synced': str(_json(state / 'snapshots' / 'snapshot.json').get('generated_at') or ''),
                     'worktrees': worktrees, 'booked': booking.get('owner', '') if booking['state'] == 'booked' else ''})
    return rows


def _when(stamp, now, tz):
    try:
        moment = datetime.fromisoformat(stamp.replace('Z', '+00:00')).astimezone(tz)
    except (AttributeError, ValueError):
        return 'never'
    today = datetime.fromisoformat(now.replace('Z', '+00:00')).astimezone(tz).date() if now else datetime.now(tz).date()
    return moment.strftime('%H:%M') if moment.date() == today else moment.strftime('%b %d %H:%M')


def render(rows, selected, width, now=None, tz=None):
    """Text lines for the picker (also the plain `sidequest projects` output when selected is None)."""
    tz = ZoneInfo(tz or config.get('identity', 'timezone', 'UTC'))
    lines = []
    for index, row in enumerate(rows):
        mark = '> ' if index == selected else '  '
        tmux = 'tmux: running   ' + str(row['windows']) + ' windows' if row['windows'] is not None else 'tmux: none'
        lines.append(mark + row['name'].ljust(14) + tmux.ljust(28) + 'synced ' + _when(row['synced'], now, tz))
        lines.append(' ' * 16 + 'repo ' + (row['repo'] or 'not set (workspace.repository)'))
        detail = (str(row['worktrees']) + ' worktrees' if row['worktrees'] is not None else 'no Git checkout found')
        if row['booked']:
            detail += ' · app booked: ' + row['booked']
        lines.append(' ' * 16 + detail)
    return [line[:width] for line in lines]


def action(key, row):
    """What a key does for the selected row, or None. Enter/a attaches, or builds the session offline."""
    if key in ('\n', '\r', 'a'):
        return ('attach', row['session']) if row['windows'] is not None else ('sidequest', ['up', '-n'])
    return KEYS.get(key)


def several(projects):
    return ('Several projects: ' + ', '.join(projects) + '. Run this inside a project folder, add --project NAME, '
            'or run sidequest projects to pick one.')


def unclear():
    """The message when several profiles exist and none was selected, else ''."""
    if config.PROJECT or os.environ.get('SIDEQUEST_CONFIG') or len(config.profiles()) < 2:
        return ''
    return several(config.profiles())
