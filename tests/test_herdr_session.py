"""Herdr workspaces for `sidequest up`: one workspace per session, one tab per window, against a fake server."""
import io
import json
from pathlib import Path
import sys
import unittest
from contextlib import redirect_stdout

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sidequest.herdr_session import Herdr, HerdrError, socket_from_status
from sidequest.sync import Window


class FakeServer:
    """Herdr 0.9.5 responses for the requests the layout sends, with the same ID scheme."""

    def __init__(self, running=True, workspaces=()):
        self.running, self.calls, self.cli, self.started = running, [], [], []
        self.spaces, self.tabs, self.next_ws, self.next_tab = [], [], 1, {}
        for label, tab_labels in workspaces:
            self._workspace(label, tab_labels, '/start')

    def _workspace(self, label, tab_labels, cwd):
        wid = 'w' + str(self.next_ws)
        self.next_ws += 1
        self.spaces.append({'workspace_id': wid, 'label': label})
        self.next_tab[wid] = 1
        made = [self._tab(wid, name, cwd) for name in tab_labels]
        return wid, made

    def _tab(self, wid, label, cwd):
        number = self.next_tab[wid]
        self.next_tab[wid] += 1
        tab = {'tab_id': wid + ':t' + str(number), 'workspace_id': wid, 'label': label, 'cwd': cwd,
               'pane_id': wid + ':p' + str(number)}
        self.tabs.append(tab)
        return tab

    def labels(self, wid):
        return [tab['label'] for tab in self.tabs if tab['workspace_id'] == wid]

    def request(self, method, params=None):
        params = params or {}
        self.calls.append((method, params))
        if not self.running:
            raise HerdrError('not running', running=False)
        if method == 'workspace.list':
            return {'type': 'workspace_list', 'workspaces': [
                dict(space, tab_count=len(self.labels(space['workspace_id']))) for space in self.spaces]}
        if method == 'workspace.create':
            wid, (tab,) = self._workspace(params['label'], ['1'], params['cwd'])
            return {'type': 'workspace_created', 'workspace': {'workspace_id': wid, 'label': params['label']},
                    'tab': {'tab_id': tab['tab_id'], 'workspace_id': wid},
                    'root_pane': {'pane_id': tab['pane_id'], 'tab_id': tab['tab_id'], 'workspace_id': wid}}
        if method == 'workspace.rename':
            next(s for s in self.spaces if s['workspace_id'] == params['workspace_id'])['label'] = params['label']
            return {'type': 'workspace_info', 'workspace': {'workspace_id': params['workspace_id']}}
        if method == 'tab.list':
            return {'type': 'tab_list', 'tabs': [{k: t[k] for k in ('tab_id', 'workspace_id', 'label')}
                                                 for t in self.tabs if t['workspace_id'] == params['workspace_id']]}
        if method == 'pane.list':
            return {'type': 'pane_list', 'panes': [{'pane_id': t['pane_id'], 'tab_id': t['tab_id'],
                                                    'workspace_id': t['workspace_id']}
                                                   for t in self.tabs if t['workspace_id'] == params['workspace_id']]}
        if method == 'tab.create':
            tab = self._tab(params['workspace_id'], params['label'], params['cwd'])
            return {'type': 'tab_created', 'tab': {'tab_id': tab['tab_id'], 'workspace_id': tab['workspace_id']},
                    'root_pane': {'pane_id': tab['pane_id'], 'tab_id': tab['tab_id'],
                                  'workspace_id': tab['workspace_id']}}
        if method == 'tab.rename':
            next(t for t in self.tabs if t['tab_id'] == params['tab_id'])['label'] = params['label']
            return {'type': 'tab_info', 'tab': {'tab_id': params['tab_id']}}
        if method == 'tab.move':
            tab = next(t for t in self.tabs if t['tab_id'] == params['tab_id'])
            same = [t for t in self.tabs if t['workspace_id'] == tab['workspace_id'] and t is not tab]
            same.insert(params['insert_index'], tab)
            others = [t for t in self.tabs if t['workspace_id'] != tab['workspace_id']]
            self.tabs = others + same
            return {'type': 'tab_list', 'tabs': []}
        if method in ('tab.close', 'tab.focus'):
            if method == 'tab.close':
                self.tabs = [t for t in self.tabs if t['tab_id'] != params['tab_id']]
            return {'type': 'tab_info' if method == 'tab.focus' else 'ok', 'tab': {'tab_id': params['tab_id']}}
        if method == 'workspace.close':
            self.spaces = [s for s in self.spaces if s['workspace_id'] != params['workspace_id']]
            self.tabs = [t for t in self.tabs if t['workspace_id'] != params['workspace_id']]
            return {'type': 'ok'}
        if method == 'workspace.focus':
            return {'type': 'workspace_info', 'workspace': {'workspace_id': params['workspace_id']}}
        raise AssertionError('unexpected request ' + method)

    def run_cli(self, args):
        self.cli.append(args)
        return ''

    def start(self, cwd):
        self.started.append(cwd)
        self.running = True
        self._workspace(Path(cwd).name, ['1'], cwd)


def herdr(server, environ=None):
    return Herdr(environ or {}, request=server.request, cli=server.run_cli, start=server.start)


WINDOWS = [Window('queue', '/code/app', 'sidequest', stay=True), Window('Main APP-1', '/code/app'),
           Window('APP-2', '/code/APP-2'), Window('report', '/code/app', 'sidequest --report', end=True)]


class LayoutTests(unittest.TestCase):
    def test_a_new_session_becomes_a_workspace_with_one_tab_per_window_in_order(self):
        server = FakeServer(workspaces=[('other', ['x'])])
        count = herdr(server).open_layout('proj', WINDOWS)
        self.assertEqual(count, 4)
        wid = next(s['workspace_id'] for s in server.spaces if s['label'] == 'proj')
        self.assertEqual(server.labels(wid), ['queue', 'Main APP-1', 'APP-2', 'report'])
        self.assertEqual(server.labels('w1'), ['x'], 'other workspaces are left alone')
        cwd = {t['label']: t['cwd'] for t in server.tabs if t['workspace_id'] == wid}
        self.assertEqual(cwd['APP-2'], '/code/APP-2')
        self.assertEqual(server.cli, [['pane', 'run', wid + ':p1', 'sidequest'],
                                      ['pane', 'run', wid + ':p4', 'sidequest --report']],
                         'commands are typed into each new tab once; the shell stays when they end')

    def test_a_second_run_reuses_tabs_and_keeps_the_persons_own_tabs_before_the_end_windows(self):
        server = FakeServer(workspaces=[('proj', ['report', 'Main APP-1', 'scratch', 'queue'])])
        count = herdr(server).open_layout('proj', WINDOWS)
        self.assertEqual(server.labels('w1'), ['queue', 'Main APP-1', 'APP-2', 'scratch', 'report'])
        self.assertEqual(count, 5)
        self.assertEqual([m for m, _ in server.calls].count('tab.create'), 1)
        self.assertEqual(server.cli, [], 'existing tabs never get their command again')
        self.assertNotIn('tab.close', [m for m, _ in server.calls], 'nothing is closed')

    def test_the_main_tab_is_renamed_when_its_ticket_changes(self):
        server = FakeServer(workspaces=[('proj', ['queue', 'Main APP-9'])])
        herdr(server).open_layout('proj', WINDOWS)
        self.assertEqual(server.labels('w1'), ['queue', 'Main APP-1', 'APP-2', 'report'])

    def test_with_no_server_one_is_started_and_its_first_workspace_is_used(self):
        server = FakeServer(running=False)
        herdr(server).open_layout('proj', WINDOWS)
        self.assertEqual(server.started, ['/code/app'], 'started in the first window\'s folder')
        self.assertEqual([s['label'] for s in server.spaces], ['proj'], 'no stray workspace is left')
        self.assertEqual(server.labels('w1'), ['queue', 'Main APP-1', 'APP-2', 'report'])


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.server = FakeServer(workspaces=[('proj', ['queue', 'APP-2'])])

    def test_count_close_and_select_find_the_workspace_by_label(self):
        box = herdr(self.server)
        self.assertTrue(box.exists('proj'))
        self.assertFalse(box.exists('nope'))
        self.assertEqual(box.window_count('proj'), 2)
        self.assertIsNone(box.window_count('nope'))
        box.select_window('proj', 'APP-2')
        self.assertIn(('tab.focus', {'tab_id': 'w1:t2'}), self.server.calls)
        box.close_window('proj', 'APP-2')
        self.assertEqual(self.server.labels('w1'), ['queue'])
        box.close_window('proj', 'missing')
        box.close_session('proj')
        self.assertEqual(self.server.spaces, [])

    def test_a_stopped_server_has_no_sessions(self):
        box = herdr(FakeServer(running=False))
        self.assertFalse(box.exists('proj'))
        self.assertIsNone(box.window_count('proj'))

    def test_attach_inside_herdr_focuses_the_workspace_and_outside_without_a_terminal_says_how(self):
        herdr(self.server, {'HERDR_ENV': '1'}).attach('proj')
        self.assertIn(('workspace.focus', {'workspace_id': 'w1'}), self.server.calls)
        self.assertEqual(self.server.cli, [], 'inside Herdr no client is started')
        shown = io.StringIO()
        with redirect_stdout(shown):
            herdr(self.server).attach('proj')
        self.assertIn('attach   herdr', shown.getvalue())

    def test_the_socket_comes_from_herdr_status_when_not_inside_herdr(self):
        status = ('client:\n  version: 0.9.5\n\nserver:\n  status: not running\n'
                  '  socket: /home/me/.config/herdr/herdr.sock\n')
        self.assertEqual(socket_from_status(status), '/home/me/.config/herdr/herdr.sock')
        with self.assertRaises(HerdrError):
            socket_from_status('client:\n  version: 0.9.5\n')


@unittest.skipUnless(__import__('shutil').which('herdr'), 'Herdr is not installed')
class RealHerdrTests(unittest.TestCase):
    """`sidequest up` against a real Herdr server that lives only in a temporary config folder."""

    def setUp(self):
        import os, shutil, subprocess, tempfile
        self.os, self.subprocess = os, subprocess
        self.home = Path(tempfile.mkdtemp(prefix='sqh', dir='/tmp')).resolve()  # short: socket paths are limited
        self.addCleanup(shutil.rmtree, self.home, True)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(('SIDEQUEST_', 'HERDR_', 'TMUX'))}
        self.env.update(HOME=str(self.home), XDG_CONFIG_HOME=str(self.home / 'c'), XDG_STATE_HOME=str(self.home / 's'),
                        XDG_DATA_HOME=str(self.home / 'd'), SIDEQUEST_CONFIG=str(self.home / 'settings.json'))
        self.addCleanup(self.stop_server)
        repo = self.home / 'repo'
        subprocess.run(['git', 'init', '-q', '-b', 'main', str(repo)], check=True)
        (self.home / 'dots').mkdir()
        (self.home / 'settings.json').write_text(json.dumps({
            'workspace': {'repository': str(repo), 'terminal': 'herdr', 'tmux_session': 'proj',
                          'windows': [{'name': 'queue', 'command': 'echo queue-ready', 'stay': True}]},
            'sessions': {'dotfiles': [{'name': 'dots', 'cwd': '~/dots'}]}}))
        self.repo = repo

    def stop_server(self):
        status = self.subprocess.run(['herdr', 'status'], capture_output=True, text=True, env=self.env).stdout
        try:
            path = socket_from_status(status)
        except HerdrError:
            return
        if path.startswith(str(self.home) + '/'):  # never the person's own server
            self.subprocess.run(['herdr', 'server', 'stop'], capture_output=True, env=self.env, timeout=20)

    def test_up_builds_the_project_and_personal_workspaces_once(self):
        for _ in range(2):
            ran = self.subprocess.run([sys.executable, '-B', str(ROOT / 'bin/sidequest'), 'up', '-n', '--no-attach'],
                                      cwd=self.repo, env=self.env, capture_output=True, text=True,
                                      stdin=self.subprocess.DEVNULL, timeout=120)
            self.assertNotEqual(ran.returncode, 2, ran.stdout + ran.stderr)
            self.assertIn('windows  2 in Herdr workspace proj', ran.stdout, ran.stdout + ran.stderr)
            self.assertIn('session  dotfiles: 1 windows', ran.stdout)
        box = Herdr(self.env)
        labels = sorted(space['label'] for space in box._workspaces())
        self.assertEqual(labels, ['dotfiles', 'proj'], 'one workspace each, nothing stray')
        tabs = [tab['label'] for tab in box._tabs(box._find('proj')['workspace_id'])]
        self.assertEqual(tabs, ['queue', 'Main'])
        self.assertEqual(box.window_count('dotfiles'), 1)


if __name__ == '__main__':
    unittest.main()
