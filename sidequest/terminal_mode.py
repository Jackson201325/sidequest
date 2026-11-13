"""Which terminal holds a project's session (tmux or Herdr), and one interface over both for `sidequest up`,
`start`, the overview and the launcher. Dashboard actions use sidequest.application instead."""
import os
import shutil
import subprocess

from sidequest import tmux
from sidequest.terminal import run_command


def mode(environ, settings):
    """tmux, herdr or shell: SIDEQUEST_TERMINAL, else workspace.terminal; auto prefers the terminal this runs
    in (tmux, then Herdr), else tmux."""
    value = environ.get('SIDEQUEST_TERMINAL') or (settings.get('workspace') or {}).get('terminal') or 'auto'
    if value != 'auto':
        return value
    if environ.get('TMUX'):
        return 'tmux'
    if environ.get('HERDR_ENV') == '1':
        return 'herdr'
    return 'tmux'


def action_mode(environ, settings):
    """shell, tmux or herdr for one dashboard or command action: SIDEQUEST_TERMINAL, else
    workspace.terminal. Unlike mode(), auto outside tmux and Herdr is the shell: an action never
    starts a session."""
    value = environ.get('SIDEQUEST_TERMINAL') or (settings.get('workspace') or {}).get('terminal') or 'auto'
    if value != 'auto':
        return value
    return 'tmux' if environ.get('TMUX') else 'herdr' if environ.get('HERDR_ENV') == '1' else 'shell'


def session_name(workspace, project):
    """The project's tmux session or Herdr workspace: workspace.tmux_session, else the project's name,
    else sidequest."""
    return (workspace or {}).get('tmux_session') or project or 'sidequest'


def unavailable(chosen):
    """Why sessions cannot be opened with `chosen`, or ''."""
    if chosen == 'shell':
        return 'workspace.terminal is shell'
    return '' if shutil.which(chosen) else chosen + ' is not installed'


def inside(environ):
    """True when this already runs in a tmux or Herdr pane."""
    return bool(environ.get('TMUX')) or environ.get('HERDR_ENV') == '1'


def run_tmux(args, timeout=45):
    """A tmux server passes the environment it starts with to every pane of every session, so it
    must not keep this project's selection; Sidequest in a pane then picks the project by folder."""
    env = {k: v for k, v in os.environ.items() if not k.startswith('SIDEQUEST_')}
    return run_command(args, timeout, env=env)


class Tmux:
    name = 'tmux'
    noun = 'tmux session'

    def __init__(self, run=run_tmux):
        self.run = run

    def exists(self, session):
        return subprocess.run(['tmux', 'has-session', '-t', '=' + session], capture_output=True).returncode == 0

    def inside(self, session):
        """True when this command runs in a pane of `session`, so closing the session stops it."""
        if not os.environ.get('TMUX'):
            return False
        ran = subprocess.run(['tmux', 'display-message', '-p', '#{session_name}'], capture_output=True, text=True)
        return ran.returncode == 0 and ran.stdout.strip() == session

    def open_layout(self, session, windows):
        return tmux.open_layout(self.run, session, windows)

    def select_window(self, session, name):
        subprocess.run(['tmux', 'select-window', '-t', session + ':=' + name], capture_output=True)

    def close_window(self, session, name):
        subprocess.run(['tmux', 'kill-window', '-t', session + ':=' + name], capture_output=True)

    def close_session(self, session):
        subprocess.run(['tmux', 'kill-session', '-t', '=' + session], capture_output=True)

    def attach(self, session):
        tmux.attach(session)


def sessions(chosen, environ=None):
    """The session interface for `chosen` (tmux or herdr)."""
    if chosen == 'herdr':
        from sidequest.herdr_session import Herdr
        return Herdr(os.environ if environ is None else environ)
    return Tmux()
