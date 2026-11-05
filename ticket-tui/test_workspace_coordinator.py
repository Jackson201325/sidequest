"""The UI submits workspace intent; an injected workflow owns its execution."""
import tempfile
import time
from pathlib import Path
import unittest
from unittest.mock import patch

from core import Store
from sidequest.terminal import LaunchResult
from tui import App


class Workflow:
    def __init__(self, path):
        self.path, self.calls = path, []

    def result(self):
        return LaunchResult(foreground={'argv': ['/bin/sh', '-i'], 'cwd': self.path, 'label': 'Workspace'})

    def start(self, key, summary):
        self.calls.append(('start', key, summary))
        return self.result()

    def open(self, key, path):
        self.calls.append(('open', key, path))
        return self.result()

    def agent(self, key, path, prompt):
        self.calls.append(('agent', key, path, prompt))
        return self.result()


class DashboardCoordinatorSpecs(unittest.TestCase):
    def test_dashboard_uses_the_same_injected_workflow_for_all_workspace_actions(self):
        with tempfile.TemporaryDirectory() as folder:
            flow = Workflow(folder)
            store = Store(':memory:')
            self.addCleanup(store.close)
            app = App(store, Path(folder), demo=True, workflow_factory=lambda: flow)
            app.demo = False
            ticket = app.selected()
            ticket.worktree = folder
            with patch('tui.run', side_effect=AssertionError('UI ran an external command')), \
                    patch('tui.config.SETTINGS', {'workspace': {'repository': folder}}), \
                    patch.object(app, 'choose', return_value=1):
                for operation in (app.jump, app.start_work, app.launch_agent):
                    app.foreground_target = None
                    operation(ticket)
                    deadline = time.monotonic() + 2
                    while app.jobs and time.monotonic() < deadline:
                        app.drain()
                        time.sleep(.01)
                    app.drain()
                    self.assertEqual(app.foreground_target['cwd'], folder)
            self.assertEqual([call[0] for call in flow.calls], ['open', 'start', 'agent'])
            self.assertIn(ticket.key, flow.calls[2][-1])


if __name__ == '__main__':
    unittest.main()
