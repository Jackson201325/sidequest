"""Herdr 0.9.5 sessions for `sidequest up`, `start` and the overview: one workspace (labelled with the
session name) per tmux-style session, one tab per window. Requests go to the server's socket, one JSON
line each; `herdr pane run` types a window's command. No Git, ticket or UI imports."""
import fcntl
import json
import os
from pathlib import Path
import pty
import select
import shutil
import socket
import struct
import subprocess
import sys
import termios
import time


class HerdrError(RuntimeError):
    def __init__(self, message, running=True):
        super().__init__(message)
        self.running = running


def socket_from_status(text):
    """The server socket from `herdr status` (it is listed even while the server is stopped)."""
    in_server = False
    for line in text.splitlines():
        if not line.startswith(' '):
            in_server = line.strip() == 'server:'
        elif in_server and line.strip().startswith('socket:'):
            return line.split(':', 1)[1].strip()
    raise HerdrError('Herdr did not report its socket; check `herdr status`')


class Herdr:
    name = 'herdr'
    noun = 'Herdr workspace'

    def __init__(self, environ=None, request=None, cli=None, start=None):
        self.environ = dict(os.environ if environ is None else environ)
        self._socket = self.environ.get('HERDR_SOCKET_PATH') or None
        self.request = request or self._socket_request
        self.cli = cli or self._run_cli
        self.start = start or self._start_server

    # Transport

    def _env(self):
        env = dict(self.environ)
        if self._socket:
            env['HERDR_SOCKET_PATH'] = self._socket
        return env

    def _socket_path(self):
        if not self._socket:
            ran = subprocess.run(['herdr', 'status'], capture_output=True, text=True, env=self._env(), timeout=15)
            self._socket = socket_from_status(ran.stdout)
        return self._socket

    def _socket_request(self, method, params=None):
        try:
            with socket.socket(socket.AF_UNIX) as conn:
                conn.settimeout(15)
                conn.connect(self._socket_path())
                conn.sendall((json.dumps({'id': 'sidequest:' + method, 'method': method, 'params': params or {}})
                              + '\n').encode())
                data = b''
                while not data.endswith(b'\n'):
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    data += chunk
        except (FileNotFoundError, ConnectionRefusedError):
            raise HerdrError('Herdr is not running', running=False) from None
        except OSError as exc:
            raise HerdrError('Herdr did not answer (' + str(exc) + '); inspect it before retrying') from None
        try:
            answer = json.loads(data.decode())
        except ValueError:
            raise HerdrError('Herdr returned an invalid response to ' + method) from None
        if isinstance(answer, dict) and isinstance(answer.get('error'), dict):
            raise HerdrError('Herdr refused ' + method + ': ' + str(answer['error'].get('message') or 'unknown error'))
        result = answer.get('result') if isinstance(answer, dict) else None
        if not isinstance(result, dict):
            raise HerdrError('Herdr returned an invalid response to ' + method)
        return result

    def _run_cli(self, args):
        ran = subprocess.run(['herdr', *args], capture_output=True, text=True, env=self._env(), timeout=15)
        if ran.returncode:
            raise HerdrError('herdr ' + args[0] + ' ' + args[1] + ' failed: ' + (ran.stderr.strip() or ran.stdout.strip())[:200])
        return ran.stdout

    def _start_server(self, cwd):
        """Start the server the way `tmux new-session -d` does: a client in a hidden terminal, closed once the
        server answers. The server keeps running; it does not inherit Sidequest's project selection."""
        env = {k: v for k, v in self.environ.items() if not k.startswith(('SIDEQUEST_', 'HERDR_'))}
        if self._socket:
            env['HERDR_SOCKET_PATH'] = self._socket
        try:
            columns, lines = os.get_terminal_size(sys.__stdout__.fileno())
        except (OSError, ValueError, AttributeError):
            columns, lines = 200, 50
        pid, fd = pty.fork()
        if pid == 0:  # pragma: no cover - the child only execs
            try:
                os.chdir(cwd)
                fcntl.ioctl(0, termios.TIOCSWINSZ, struct.pack('HHHH', lines, columns, 0, 0))
                os.execvpe('herdr', ['herdr'], env)
            finally:
                os._exit(127)
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if select.select([fd], [], [], 0.1)[0]:
                    try:
                        os.read(fd, 65536)  # macOS holds a process until its terminal output is read
                    except OSError:
                        break
                if self.running():
                    return
            raise HerdrError('Herdr did not start within 15 seconds; run `herdr` once to check it')
        finally:
            os.close(fd)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not os.waitpid(pid, os.WNOHANG)[0]:
                time.sleep(0.05)

    # Reads

    def running(self):
        try:
            self.request('workspace.list')
            return True
        except HerdrError as exc:
            if exc.running:
                raise
            return False

    def _workspaces(self):
        spaces = self.request('workspace.list').get('workspaces')
        if not isinstance(spaces, list) or not all(isinstance(s, dict) and isinstance(s.get('workspace_id'), str)
                                                   for s in spaces):
            raise HerdrError('Herdr returned an invalid workspace list')
        return spaces

    def _find(self, label):
        try:
            return next((space for space in self._workspaces() if space.get('label') == label), None)
        except HerdrError as exc:
            if exc.running:
                raise
            return None

    def _tabs(self, wid):
        tabs = self.request('tab.list', {'workspace_id': wid}).get('tabs')
        if not isinstance(tabs, list) or not all(isinstance(t, dict) and isinstance(t.get('tab_id'), str)
                                                 and t.get('workspace_id') == wid for t in tabs):
            raise HerdrError('Herdr returned an invalid tab list')
        return tabs

    def exists(self, session):
        return self._find(session) is not None

    def inside(self, session):
        """True when this command runs in a pane of workspace `session`, so closing it stops this command."""
        if self.environ.get('HERDR_ENV') != '1':
            return False
        space = self._find(session)
        return space is not None and space['workspace_id'] == self.environ.get('HERDR_WORKSPACE_ID')

    def window_count(self, session):
        space = self._find(session)
        if space is None:
            return None
        count = space.get('tab_count')
        return count if isinstance(count, int) else len(self._tabs(space['workspace_id']))

    # Layout

    def _pane(self, value, wid):
        if not isinstance(value, dict) or value.get('workspace_id') != wid or not isinstance(value.get('pane_id'), str):
            raise HerdrError('Herdr returned an invalid pane; inspect the workspace before retrying')
        return value['pane_id']

    def _type(self, pane, window):
        for text in (window.command, window.keys):
            if text:
                self.cli(['pane', 'run', pane, text])

    def open_layout(self, session, windows):
        """Make workspace `session` hold `windows` as tabs in order: reuse tabs by label (the main checkout's
        is renamed when its ticket changes), create missing ones and type their command once, and move the
        person's own tabs after the worktrees and before the end windows. Nothing is closed."""
        started = False
        if not self.running():
            self.start(windows[0].path)
            started = True
        space = self._find(session)
        fresh = []
        if space is None:
            spaces = self._workspaces()
            if started and len(spaces) == 1:  # the workspace a new server opens with
                space = spaces[0]
                wid = space['workspace_id']
                self.request('workspace.rename', {'workspace_id': wid, 'label': session})
                panes = self.request('pane.list', {'workspace_id': wid}).get('panes') or []
                first = panes[0] if panes and isinstance(panes[0], dict) else None
                pane, tab = self._pane(first, wid), first.get('tab_id')
            else:
                made = self.request('workspace.create', {'label': session, 'cwd': windows[0].path, 'focus': False})
                space = made.get('workspace') or {}
                wid = space.get('workspace_id')
                pane, tab = self._pane(made.get('root_pane'), wid), (made.get('tab') or {}).get('tab_id')
            self.request('tab.rename', {'tab_id': tab, 'label': windows[0].name})
            fresh.append((pane, windows[0]))
        wid = space['workspace_id']
        rows = self._tabs(wid)
        ids = {tab.get('label'): tab['tab_id'] for tab in rows}
        main = next((w for w in windows if w.name == 'Main' or w.name.startswith('Main ')), None)
        if main and main.name not in ids:
            old = next((label for label in ids if label in ('Main', 'main') or str(label).startswith('Main ')), None)
            if old:
                self.request('tab.rename', {'tab_id': ids[old], 'label': main.name})
                ids[main.name] = ids.pop(old)
        for window in windows:
            if window.name not in ids:
                made = self.request('tab.create', {'workspace_id': wid, 'label': window.name, 'cwd': window.path,
                                                   'focus': False})
                ids[window.name] = (made.get('tab') or {}).get('tab_id')
                fresh.append((self._pane(made.get('root_pane'), wid), window))
        for pane, window in fresh:
            self._type(pane, window)
        wanted = [ids[w.name] for w in windows if not w.end]
        tail = [ids[w.name] for w in windows if w.end]
        own = [tab['tab_id'] for tab in rows if tab['tab_id'] not in wanted and tab['tab_id'] not in tail]
        order = wanted + own + tail
        for index, tab_id in enumerate(order):
            self.request('tab.move', {'tab_id': tab_id, 'insert_index': index})
        return len(order)

    # Controls

    def _tab_id(self, session, name):
        space = self._find(session)
        if space is None:
            return None
        return next((tab['tab_id'] for tab in self._tabs(space['workspace_id']) if tab.get('label') == name), None)

    def select_window(self, session, name):
        tab = self._tab_id(session, name)
        if tab:
            self.request('tab.focus', {'tab_id': tab})

    def close_window(self, session, name):
        tab = self._tab_id(session, name)
        if tab:
            self.request('tab.close', {'tab_id': tab})

    def close_session(self, session):
        space = self._find(session)
        if space is not None:
            self.request('workspace.close', {'workspace_id': space['workspace_id']})

    def attach(self, session):
        """Focus the workspace; outside Herdr also attach a client in this terminal (and wait for it)."""
        space = self._find(session)
        if space is not None:
            self.request('workspace.focus', {'workspace_id': space['workspace_id']})
        if self.environ.get('HERDR_ENV') == '1':
            return
        if sys.stdin.isatty() and sys.stdout.isatty() and shutil.which('herdr'):
            sys.stdout.flush()
            subprocess.run(['herdr'], env=self._env())
        else:
            print('attach   herdr')
