"""A tmux server started by Sidequest must not carry one project's selection into every pane."""
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sidequest import terminal_mode
from sidequest.sync import Window


class TmuxEnvironmentTests(unittest.TestCase):
    def test_new_session_does_not_inherit_project_selection(self):
        calls = []

        def fake_run(args, **kwargs):
            calls.append((args, kwargs))
            if args[:2] == ['tmux', 'has-session']:
                return subprocess.CompletedProcess(args, 1, '', 'no server running')
            if args[:2] == ['tmux', 'list-windows']:
                return subprocess.CompletedProcess(args, 0, '0 @1 Main\n', '')
            return subprocess.CompletedProcess(args, 0, '', '')

        environ = dict(os.environ, SIDEQUEST_PROJECT='tierrewards', SIDEQUEST_TERMINAL='tmux', PATH='/usr/bin')
        with patch.dict(os.environ, environ, clear=True), patch('sidequest.terminal.subprocess.run', fake_run):
            terminal_mode.sessions('tmux').open_layout('wedin', [Window('Main', '/repo/wedin')])

        started = [kwargs.get('env') for args, kwargs in calls if args[:2] == ['tmux', 'new-session']]
        self.assertEqual(len(started), 1)
        self.assertIsNotNone(started[0])
        self.assertFalse([key for key in started[0] if key.startswith('SIDEQUEST_')])
        self.assertEqual(started[0].get('PATH'), '/usr/bin')


if __name__ == '__main__':
    unittest.main()
