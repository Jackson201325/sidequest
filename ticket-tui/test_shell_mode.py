import os
import subprocess
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from core import Store
from tui import App


def drain(app):
    deadline = time.monotonic() + 2
    while app.jobs and time.monotonic() < deadline:
        app.drain()
        time.sleep(.01)
    app.drain()


class PlainTerminalTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name).resolve()
        self.store = Store(':memory:')
        self.app = App(self.store, self.path, demo=True)
        self.app.demo = False
        self.app.evidence.windows = {'DEMO-901': str(self.path)}
        self.app.rebuild()
        self.ticket = next(ticket for ticket in self.app.tickets if ticket.key == 'DEMO-901')
        self.env = patch.dict(os.environ, {'SHELL': '/bin/sh', 'TMUX': ''})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.store.close()
        self.folder.cleanup()

    def test_workspace_jump_without_tmux_queues_a_shell_at_the_worktree(self):
        with patch('tui.run', return_value='') as run:
            self.app.jump(self.ticket)
            drain(self.app)
        run.assert_not_called()
        request = getattr(self.app, 'foreground_target', None)
        self.assertIsNotNone(request)
        self.assertEqual(request['cwd'], str(self.path))
        self.assertEqual(request['argv'], ['/bin/sh', '-i'])

    def test_agent_without_tmux_runs_the_configured_cli_in_the_worktree(self):
        from sidequest import config
        with patch.object(config, 'SETTINGS', {'workspace': {'agent_command': 'codex'}}), \
                patch.object(self.app, 'choose', return_value=1), patch('tui.run') as run:
            self.app.launch_agent(self.ticket)
            drain(self.app)
        run.assert_not_called()
        request = getattr(self.app, 'foreground_target', None)
        self.assertIsNotNone(request)
        self.assertEqual(request['cwd'], str(self.path))
        self.assertEqual(request['argv'][0], 'codex')
        self.assertIn(self.ticket.key, request['argv'][-1])

    def test_local_start_creates_or_reuses_then_opens_without_jira_changes(self):
        from sidequest import config
        for args in (['init', '-q', '-b', 'main'], ['-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                                                  'commit', '--allow-empty', '-qm', 'Base']):
            subprocess.run(['git', '-C', str(self.path), *args], check=True)
        settings = {'workspace': {'repository': str(self.path), 'base_ref': 'main',
                                  'worktrees_dir': str(self.path / 'worktrees')}}
        with patch.object(config, 'SETTINGS', settings), patch('tui.run') as run:
            for _ in range(2):
                self.app.start_work(self.ticket)
                drain(self.app)
                self.assertTrue((Path(self.app.foreground_target['cwd']) / '.git').is_file())
        run.assert_not_called()
        self.assertEqual(Path(self.app.foreground_target['cwd']).parent, self.path / 'worktrees')
        self.assertEqual(subprocess.check_output(['git', '-C', str(self.path), 'branch', '--show-current'], text=True).strip(), 'main')


if __name__ == '__main__':
    unittest.main()
